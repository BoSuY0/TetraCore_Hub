// Package main is the entry point for TetraCore Hub.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gofiber/fiber/v2"

	"github.com/tetra/core-hub/internal/delivery/http"
	"github.com/tetra/core-hub/internal/delivery/http/adapter"
	"github.com/tetra/core-hub/internal/delivery/http/handler"
	httpMw "github.com/tetra/core-hub/internal/delivery/http/middleware"
	"github.com/tetra/core-hub/internal/delivery/websocket"
	"github.com/tetra/core-hub/internal/infrastructure/eventbus"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/internal/infrastructure/repository"
	"github.com/tetra/core-hub/internal/infrastructure/secrets"
	"github.com/tetra/core-hub/internal/infrastructure/security"
	"github.com/tetra/core-hub/internal/plugins"
	"github.com/tetra/core-hub/internal/usecase/apikey"
	"github.com/tetra/core-hub/internal/usecase/auth"
	"github.com/tetra/core-hub/internal/usecase/client"
	"github.com/tetra/core-hub/internal/usecase/hub"
	"github.com/tetra/core-hub/internal/usecase/rbac"
	"github.com/tetra/core-hub/internal/usecase/task"
	"github.com/tetra/core-hub/pkg/config"
	"github.com/tetra/core-hub/pkg/logger"
)

// Version and build info (set via ldflags)
var (
	Version   = "dev"
	BuildTime = "unknown"
)

func main() {
	// Load configuration
	cfg, err := config.Load()
	if err != nil {
		// Use fmt.Fprintf to stderr since logger isn't initialized yet
		os.Stderr.WriteString("FATAL: Failed to load configuration: " + err.Error() + "\n")
		os.Exit(1)
	}

	// Initialize logger
	logger.Init(cfg.Logging)
	log := logger.WithComponent("main")

	log.Info().
		Str("app", cfg.App.Name).
		Str("version", Version).
		Str("build_time", BuildTime).
		Str("environment", string(cfg.App.Environment)).
		Msg("Starting TetraCore Hub")

	// Validate configuration
	if err := cfg.Validate(); err != nil {
		log.Fatal().Err(err).Msg("Configuration validation failed")
	}

	// Create root context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// ==================== Infrastructure ====================

	// Initialize Redis client
	log.Info().Msg("Connecting to Redis...")
	redisClient, err := redis.NewClient(&cfg.Redis)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to Redis")
	}
	defer redisClient.Close()

	// Test Redis connection
	if err := redisClient.Ping(ctx); err != nil {
		log.Fatal().Err(err).Msg("Redis connection test failed")
	}
	log.Info().Msg("Redis connected successfully")

	// Initialize Pub/Sub manager
	pubsub := redis.NewPubSubManager(redisClient, redis.PubSubConfig{
		BufferSize:     1000,
		ReconnectDelay: time.Second * 5,
	})
	defer pubsub.Close()

	var streamMgr *redis.StreamManager
	if cfg.Redis.TaskStream != "" {
		consumer := cfg.Redis.TaskStreamConsumer
		if consumer == "" {
			host, err := os.Hostname()
			if err != nil {
				consumer = "hub-consumer"
			} else {
				consumer = host
			}
		}
		group := cfg.Redis.TaskStreamGroup
		if group == "" {
			group = "hub"
		}
		streamMgr = redis.NewStreamManager(redisClient, redis.StreamConfig{
			Stream:   cfg.Redis.TaskStream,
			Group:    group,
			Consumer: consumer,
			Block:    cfg.Redis.TaskStreamBlock,
			Batch:    cfg.Redis.TaskStreamBatch,
			MaxLen:   cfg.Redis.TaskStreamMaxLen,
		})
	}

	// Initialize Event Bus
	log.Info().Msg("Initializing event bus...")
	eventBus := eventbus.New(eventbus.Config{
		BufferSize:  cfg.EventBus.BufferSize,
		WorkerCount: cfg.EventBus.WorkerCount,
	})
	defer eventBus.Close()

	// Initialize Secrets Manager (optional, requires encryption key)
	var secretsManager *secrets.Manager
	if cfg.Secrets.EncryptionKey != "" {
		log.Info().Msg("Initializing secrets manager...")
		var err error
		secretsManager, err = secrets.NewManager(redisClient.Underlying(), secrets.ManagerConfig{
			EncryptionKey: cfg.Secrets.EncryptionKey,
			CacheSize:     cfg.Secrets.CacheSize,
		}, eventBus)
		if err != nil {
			log.Warn().Err(err).Msg("Failed to initialize secrets manager, secrets API will be disabled")
		}
	}

	// Initialize Plugin Registry (optional)
	var pluginRegistry *plugins.Registry
	if cfg.Plugins.Enabled {
		log.Info().Msg("Initializing plugin registry...")
		var err error
		pluginRegistry, err = plugins.NewRegistry(plugins.RegistryConfig{
			PluginsDir:  cfg.Plugins.Directory,
			PoolSize:    cfg.Plugins.PoolSize,
			MaxExecTime: cfg.Plugins.MaxExecTime,
			MaxMemory:   cfg.Plugins.MaxMemory,
		})
		if err != nil {
			log.Warn().Err(err).Msg("Failed to initialize plugin registry, plugins will be disabled")
		} else {
			defer pluginRegistry.Close()
			// Load all plugins from directory
			if err := pluginRegistry.LoadAllPlugins(); err != nil {
				log.Warn().Err(err).Msg("Failed to load plugins")
			}
		}
	}

	// Initialize JWT manager
	jwtManager := security.NewJWTManagerSimple(cfg.Auth.JWTSecret, cfg.Auth.JWTIssuer)

	// Initialize password hasher
	hasher := security.NewBCryptHasher(security.DefaultCost)

	// Hash admin password if not already hashed
	adminPasswordHash := cfg.Auth.AdminPasswordHash
	if adminPasswordHash == "" && cfg.Auth.AdminPassword != "" {
		hash, err := hasher.Hash(cfg.Auth.AdminPassword)
		if err != nil {
			log.Fatal().Err(err).Msg("Failed to hash admin password")
		}
		adminPasswordHash = hash
	}

	// Initialize rate limiter
	rateLimiter := security.NewInMemoryRateLimiter(security.RateLimitConfig{
		Requests:  cfg.Security.RateLimitRequests,
		Window:    cfg.Security.RateLimitWindow,
		BurstSize: cfg.Security.RateLimitRequests / 2,
	})

	// ==================== Repositories ====================

	// Initialize repositories
	sessionRepo := repository.NewRedisSessionRepository(redisClient, cfg.Auth.SessionDuration)
	loginAttemptRepo := repository.NewRedisLoginAttemptRepository(
		redisClient,
		cfg.Auth.MaxLoginAttempts,
		cfg.Auth.LockoutDuration,
		cfg.Auth.LockoutDuration,
	)
	tokenBlacklistRepo := repository.NewRedisTokenBlacklistRepository(redisClient)
	clientRepo := repository.NewRedisClientRepository(redisClient, cfg.Redis.DefaultTTL)
	taskRepo := repository.NewRedisTaskRepository(redisClient, cfg.Redis.DefaultTTL)

	// New repositories for RBAC, API Keys, DLQ, Templates
	userRepo := repository.NewRedisUserRepository(redisClient.Underlying())
	roleRepo := repository.NewRedisRoleRepository(redisClient.Underlying())
	apiKeyRepo := repository.NewRedisAPIKeyRepository(redisClient.Underlying())
	dlqRepo := repository.NewRedisDLQRepository(redisClient.Underlying())
	templateRepo := repository.NewRedisTemplateRepository(redisClient.Underlying())

	// ==================== Use Cases ====================

	// Initialize auth use case
	authUC := auth.NewUseCase(
		sessionRepo,
		loginAttemptRepo,
		tokenBlacklistRepo,
		jwtManager,
		hasher,
		auth.Config{
			AdminUsername:         cfg.Auth.AdminUsername,
			AdminPasswordHash:     adminPasswordHash,
			SessionDuration:       cfg.Auth.SessionDuration,
			TokenRefreshThreshold: cfg.Auth.TokenRefreshThreshold,
			MaxLoginAttempts:      cfg.Auth.MaxLoginAttempts,
			LockoutDuration:       cfg.Auth.LockoutDuration,
		},
	)

	// Initialize client use case
	clientUC := client.NewUseCase(
		clientRepo,
		client.Config{
			HeartbeatTimeout:     cfg.WebSocket.HeartbeatInterval * 2,
			CleanupInterval:      cfg.Auth.CleanupInterval,
			AllowReconnect:       true,
			ReconnectGracePeriod: time.Minute,
		},
	)

	// Initialize task use case (with Redis client for enhanced pipeline components)
	taskUC := task.NewUseCase(
		taskRepo,
		clientUC, // WorkerSelector interface
		task.Config{
			DefaultTimeout:    cfg.WebSocket.Timeout,
			MaxRetries:        3,
			RetryDelay:        time.Second * 5,
			CleanupAge:        cfg.Redis.DefaultTTL,
			EnableIdempotency: true,
		},
		redisClient,
	)

	// Initialize hub use case
	hubUC := hub.NewUseCase(
		authUC,
		clientUC,
		taskUC,
		pubsub,
		streamMgr,
		hub.Config{
			TaskChannel:        cfg.Redis.TaskChannel,
			ResultChannel:      cfg.Redis.ResultChannel,
			BroadcastChannel:   cfg.Redis.BroadcastChannel,
			HealthChannel:      cfg.Redis.HealthChannel,
			TaskStream:         cfg.Redis.TaskStream,
			TaskStreamGroup:    cfg.Redis.TaskStreamGroup,
			TaskStreamConsumer: cfg.Redis.TaskStreamConsumer,
			TaskStreamBlock:    cfg.Redis.TaskStreamBlock,
			TaskStreamBatch:    cfg.Redis.TaskStreamBatch,
			CleanupInterval:    cfg.Redis.CleanupInterval,
			HeartbeatInterval:  cfg.WebSocket.HeartbeatInterval,
		},
	)

	// Initialize RBAC use case
	rbacUC := rbac.NewUseCase(userRepo, roleRepo, eventBus)

	// Initialize default roles and admin user
	if err := rbacUC.InitializeDefaults(ctx, cfg.Auth.AdminUsername, cfg.Auth.AdminPassword); err != nil {
		log.Warn().Err(err).Msg("Failed to initialize RBAC defaults")
	}

	// Initialize API Key use case
	apiKeyUC := apikey.NewUseCase(apiKeyRepo, roleRepo, eventBus)

	// ==================== Delivery Layer ====================

	// Create Fiber app
	app := fiber.New(fiber.Config{
		AppName:               cfg.App.Name,
		ReadTimeout:           cfg.Server.ReadTimeout,
		WriteTimeout:          cfg.Server.WriteTimeout,
		IdleTimeout:           cfg.Server.IdleTimeout,
		DisableStartupMessage: true,
		ErrorHandler:          http.ErrorHandler,
	})

	// Setup auth middleware for protected routes
	authMiddleware := httpMw.NewAuthMiddleware(jwtManager, authUC)

	// Create adapters for handlers
	authAdapter := adapter.NewAuthAdapter(authUC)
	hubAdapter := adapter.NewHubAdapter(hubUC)
	clientAdapter := adapter.NewClientAdapter(clientUC)
	taskAdapter := adapter.NewTaskAdapter(taskUC)
	sessionAdapter := adapter.NewSessionAdapter(authUC)

	// Initialize handlers
	healthHandler := handler.NewHealthHandler(redisClient, hubAdapter)
	authHandler := handler.NewAuthHandler(authAdapter)
	clientHandler := handler.NewClientHandler(clientAdapter)
	taskHandler := handler.NewTaskHandler(taskAdapter)
	sessionHandler := handler.NewSessionHandler(sessionAdapter)

	// Initialize new handlers
	userHandler := handler.NewUserHandler(rbacUC)
	roleHandler := handler.NewRoleHandler(rbacUC)
	apiKeyHandler := handler.NewAPIKeyHandler(apiKeyUC)
	dlqHandler := handler.NewDLQHandler(dlqRepo)
	templateHandler := handler.NewTemplateHandler(templateRepo)

	// Initialize optional handlers
	var secretsHandler *handler.SecretsHandler
	if secretsManager != nil {
		secretsHandler = handler.NewSecretsHandler(secretsManager)
	}

	var pluginsHandler *handler.PluginsHandler
	if pluginRegistry != nil {
		pluginsHandler = handler.NewPluginsHandler(pluginRegistry)
	}

	// Setup router
	router := http.NewRouter(http.RouterConfig{
		App:            app,
		AuthMiddleware: authMiddleware,
		RateLimiter:    rateLimiter,
		AllowedOrigins: cfg.Security.AllowedOrigins,
		EnableCompress: cfg.Security.EnableCompression,
	})
	router.Setup(http.Handlers{
		Health:   healthHandler,
		Auth:     authHandler,
		Client:   clientHandler,
		Task:     taskHandler,
		Session:  sessionHandler,
		User:     userHandler,
		Role:     roleHandler,
		APIKey:   apiKeyHandler,
		Secrets:  secretsHandler,
		DLQ:      dlqHandler,
		Template: templateHandler,
		Plugins:  pluginsHandler,
	})

	// Initialize WebSocket handler
	wsHandler := websocket.NewHandler(websocket.Config{
		Path:              cfg.WebSocket.Path,
		Timeout:           cfg.WebSocket.Timeout,
		HeartbeatInterval: cfg.WebSocket.HeartbeatInterval,
		MaxConnections:    cfg.WebSocket.MaxConnections,
		ReadBufferSize:    cfg.WebSocket.ReadBufferSize,
		WriteBufferSize:   cfg.WebSocket.WriteBufferSize,
		RequireAuth:       cfg.Auth.RequireAuth,
	}, jwtManager, authUC)

	// Set connection manager for hub
	hubUC.SetConnectionManager(wsHandler)

	// Setup WebSocket routes
	wsHandler.SetupRoutes(app, hubUC)

	// Register 404 handler AFTER all routes (including WebSocket) are set up.
	// This must be the last route registration to avoid blocking dynamic paths like /ws.
	router.SetupNotFound()

	// Start hub orchestration
	if err := hubUC.Start(); err != nil {
		log.Fatal().Err(err).Msg("Failed to start hub orchestration")
	}

	// ==================== Server Startup ====================

	// Setup graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start server in goroutine
	serverAddr := cfg.GetServerAddress()
	go func() {
		log.Info().
			Str("address", serverAddr).
			Str("websocket", cfg.GetWebSocketURL()).
			Msg("Server starting")

		if err := app.Listen(serverAddr); err != nil {
			log.Error().Err(err).Msg("Server error")
		}
	}()

	// Print startup info
	log.Info().
		Str("address", serverAddr).
		Str("websocket_path", cfg.WebSocket.Path).
		Str("health_endpoint", "/health").
		Msg("TetraCore Hub is running")

	// ==================== Graceful Shutdown ====================

	// Wait for shutdown signal
	sig := <-sigChan
	log.Info().Str("signal", sig.String()).Msg("Received shutdown signal")

	// Initiate graceful shutdown
	log.Info().Msg("Initiating graceful shutdown...")

	// Create shutdown context with timeout
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	// 1. Stop hub orchestration (stops accepting new tasks)
	if err := hubUC.Stop(); err != nil {
		log.Warn().Err(err).Msg("Error stopping hub orchestration")
	}

	// 2. Close WebSocket connections
	wsHandler.CloseAll("server_shutdown")

	// 3. Shutdown HTTP server
	if err := app.ShutdownWithContext(shutdownCtx); err != nil {
		log.Warn().Err(err).Msg("Error shutting down HTTP server")
	}

	// 4. Close Redis connections (handled by defer)

	log.Info().Msg("TetraCore Hub shutdown complete")
}

// initFromEnv initializes configuration from environment variables.
// This is called before config.Load() if needed for early setup.
func initFromEnv() {
	// Set defaults from environment if not already set
	if os.Getenv("REDIS_URL") == "" {
		os.Setenv("REDIS_URL", "redis://localhost:6379")
	}
}

func init() {
	initFromEnv()
}
