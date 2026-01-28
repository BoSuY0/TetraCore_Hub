// Package config provides configuration loading for TetraCore Hub.
package config

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/joho/godotenv"
	"github.com/spf13/viper"
	"github.com/tetra/core-hub/pkg/logger"
)

// Environment represents deployment environment type.
type Environment string

const (
	EnvDevelopment Environment = "development"
	EnvProduction  Environment = "production"
	EnvTesting     Environment = "testing"
)

// Config holds all application configuration.
type Config struct {
	App       AppConfig       `mapstructure:"app"`
	Server    ServerConfig    `mapstructure:"server"`
	WebSocket WebSocketConfig `mapstructure:"websocket"`
	Auth      AuthConfig      `mapstructure:"auth"`
	Redis     RedisConfig     `mapstructure:"redis"`
	Logging   logger.Config   `mapstructure:"logging"`
	Security  SecurityConfig  `mapstructure:"security"`
	Metrics   MetricsConfig   `mapstructure:"metrics"`
	Secrets   SecretsConfig   `mapstructure:"secrets"`
	Plugins   PluginsConfig   `mapstructure:"plugins"`
	EventBus  EventBusConfig  `mapstructure:"eventbus"`
}

// AppConfig holds application settings.
type AppConfig struct {
	Name        string      `mapstructure:"name"`
	Version     string      `mapstructure:"version"`
	Environment Environment `mapstructure:"environment"`
	Debug       bool        `mapstructure:"debug"`
}

// ServerConfig holds HTTP server settings.
type ServerConfig struct {
	Host           string        `mapstructure:"host"`
	Port           int           `mapstructure:"port"`
	CustomDomain   string        `mapstructure:"custom_domain"`
	ReadTimeout    time.Duration `mapstructure:"read_timeout"`
	WriteTimeout   time.Duration `mapstructure:"write_timeout"`
	IdleTimeout    time.Duration `mapstructure:"idle_timeout"`
	MaxConnections int           `mapstructure:"max_connections"`
}

// WebSocketConfig holds WebSocket settings.
type WebSocketConfig struct {
	Path              string        `mapstructure:"path"`
	Timeout           time.Duration `mapstructure:"timeout"`
	HeartbeatInterval time.Duration `mapstructure:"heartbeat_interval"`
	MaxConnections    int           `mapstructure:"max_connections"`
	ReadBufferSize    int           `mapstructure:"read_buffer_size"`
	WriteBufferSize   int           `mapstructure:"write_buffer_size"`
}

// AuthConfig holds authentication settings.
type AuthConfig struct {
	RequireAuth           bool          `mapstructure:"require_auth"`
	AdminUsername         string        `mapstructure:"admin_username"`
	AdminPassword         string        `mapstructure:"admin_password"`
	AdminPasswordHash     string        `mapstructure:"admin_password_hash"`
	JWTSecret             string        `mapstructure:"jwt_secret"`
	JWTIssuer             string        `mapstructure:"jwt_issuer"`
	SessionDuration       time.Duration `mapstructure:"session_duration"`
	TokenRefreshThreshold time.Duration `mapstructure:"token_refresh_threshold"`
	MaxLoginAttempts      int           `mapstructure:"max_login_attempts"`
	LockoutDuration       time.Duration `mapstructure:"lockout_duration"`
	CleanupInterval       time.Duration `mapstructure:"cleanup_interval"`
}

// RedisConfig holds Redis connection settings.
type RedisConfig struct {
	URL                 string        `mapstructure:"url"`
	TLSEnabled          bool          `mapstructure:"tls_enabled"`
	MaxConnections      int           `mapstructure:"max_connections"`
	MinIdleConns        int           `mapstructure:"min_idle_conns"`
	ConnMaxIdleTime     time.Duration `mapstructure:"conn_max_idle_time"`
	ConnMaxLifetime     time.Duration `mapstructure:"conn_max_lifetime"`
	RetryOnTimeout      bool          `mapstructure:"retry_on_timeout"`
	HealthCheckInterval time.Duration `mapstructure:"health_check_interval"`

	// Sentinel settings
	SentinelURLs        []string `mapstructure:"sentinel_urls"`
	SentinelServiceName string   `mapstructure:"sentinel_service_name"`

	// Cluster settings
	ClusterNodes []string `mapstructure:"cluster_nodes"`

	// Pipeline settings
	PipelineEnabled       bool          `mapstructure:"pipeline_enabled"`
	PipelineBatchSize     int           `mapstructure:"pipeline_batch_size"`
	PipelineFlushInterval time.Duration `mapstructure:"pipeline_flush_interval"`

	// TTL settings
	DefaultTTL      time.Duration `mapstructure:"default_ttl"`
	CleanupInterval time.Duration `mapstructure:"cleanup_interval"`

	// Pub/Sub channels
	TaskChannel      string `mapstructure:"task_channel"`
	ResultChannel    string `mapstructure:"result_channel"`
	BroadcastChannel string `mapstructure:"broadcast_channel"`
	HealthChannel    string `mapstructure:"health_channel"`

	// Stream settings
	TaskStream         string        `mapstructure:"task_stream"`
	TaskStreamGroup    string        `mapstructure:"task_stream_group"`
	TaskStreamConsumer string        `mapstructure:"task_stream_consumer"`
	TaskStreamBlock    time.Duration `mapstructure:"task_stream_block"`
	TaskStreamBatch    int64         `mapstructure:"task_stream_batch"`
	TaskStreamMaxLen   int64         `mapstructure:"task_stream_max_len"`
}

// SecurityConfig holds security settings.
type SecurityConfig struct {
	AllowedOrigins      []string      `mapstructure:"allowed_origins"`
	AuthToken           string        `mapstructure:"auth_token"`
	AuthTokenActive     string        `mapstructure:"auth_token_active"`
	AuthTokenNext       string        `mapstructure:"auth_token_next"`
	EnableTokenRotation bool          `mapstructure:"enable_token_rotation"`
	TokenRotationInterval time.Duration `mapstructure:"token_rotation_interval"`
	RateLimitRequests   int           `mapstructure:"rate_limit_requests"`
	RateLimitWindow     time.Duration `mapstructure:"rate_limit_window"`
	EnableCompression   bool          `mapstructure:"enable_compression"`
}

// MetricsConfig holds metrics settings.
type MetricsConfig struct {
	Enabled             bool   `mapstructure:"enabled"`
	Port                int    `mapstructure:"port"`
	HealthCheckEndpoint string `mapstructure:"health_check_endpoint"`
}

// SecretsConfig holds secrets manager settings.
type SecretsConfig struct {
	EncryptionKey string `mapstructure:"encryption_key"`
	CacheSize     int    `mapstructure:"cache_size"`
}

// PluginsConfig holds plugins settings.
type PluginsConfig struct {
	Enabled     bool          `mapstructure:"enabled"`
	Directory   string        `mapstructure:"directory"`
	PoolSize    int           `mapstructure:"pool_size"`
	MaxExecTime time.Duration `mapstructure:"max_exec_time"`
	MaxMemory   int64         `mapstructure:"max_memory"`
}

// EventBusConfig holds event bus settings.
type EventBusConfig struct {
	BufferSize  int `mapstructure:"buffer_size"`
	WorkerCount int `mapstructure:"worker_count"`
}

// TaskConfig holds task processing settings.
type TaskConfig struct {
	Timeout               time.Duration `mapstructure:"timeout"`
	MaxRetries            int           `mapstructure:"max_retries"`
	RetryDelay            time.Duration `mapstructure:"retry_delay"`
	WorkerSelectionStrategy string      `mapstructure:"worker_selection_strategy"`
	QueueSize             int           `mapstructure:"queue_size"`
	WorkerPoolSize        int           `mapstructure:"worker_pool_size"`
}

// Default returns a Config with default values.
func Default() *Config {
	return &Config{
		App: AppConfig{
			Name:        "TetraCore StreamHub",
			Version:     "2.0.0",
			Environment: EnvDevelopment,
			Debug:       false,
		},
		Server: ServerConfig{
			Host:           "0.0.0.0",
			Port:           8000,
			CustomDomain:   "hub.tetra-core.website",
			ReadTimeout:    30 * time.Second,
			WriteTimeout:   30 * time.Second,
			IdleTimeout:    120 * time.Second,
			MaxConnections: 1000,
		},
		WebSocket: WebSocketConfig{
			Path:              "/ws",
			Timeout:           10 * time.Minute,
			HeartbeatInterval: 60 * time.Second,
			MaxConnections:    1000,
			ReadBufferSize:    1024,
			WriteBufferSize:   1024,
		},
		Auth: AuthConfig{
			RequireAuth:           false, // Disabled by default for development
			JWTIssuer:             "tetracore-hub",
			SessionDuration:       24 * time.Hour,
			TokenRefreshThreshold: 1 * time.Hour,
			MaxLoginAttempts:      5,
			LockoutDuration:       15 * time.Minute,
			CleanupInterval:       1 * time.Hour,
		},
		Redis: RedisConfig{
			MaxConnections:        50,
			MinIdleConns:          5,
			ConnMaxIdleTime:       5 * time.Minute,
			ConnMaxLifetime:       30 * time.Minute,
			RetryOnTimeout:        true,
			HealthCheckInterval:   2 * time.Minute,
			SentinelServiceName:   "tetracore-master",
			PipelineEnabled:       true,
			PipelineBatchSize:     100,
			PipelineFlushInterval: 100 * time.Millisecond,
			DefaultTTL:            24 * time.Hour,
			CleanupInterval:       1 * time.Hour,
			TaskChannel:           "tetra:tasks",
			ResultChannel:         "tetra:results",
			BroadcastChannel:      "tetra:broadcast",
			HealthChannel:         "tetra:health",
			TaskStream:            "tetra:tasks:stream",
			TaskStreamGroup:       "hub",
			TaskStreamBlock:       5 * time.Second,
			TaskStreamBatch:       10,
			TaskStreamMaxLen:      10000,
		},
		Logging: logger.Config{
			Level:      "info",
			Format:     "json",
			TimeFormat: "2006-01-02T15:04:05Z07:00",
			CallerInfo: false,
		},
		Security: SecurityConfig{
			AllowedOrigins:        []string{"*"},
			RateLimitRequests:     1000,
			RateLimitWindow:       1 * time.Minute,
			EnableCompression:     true,
			TokenRotationInterval: 24 * time.Hour,
		},
		Metrics: MetricsConfig{
			Enabled:             true,
			Port:                9090,
			HealthCheckEndpoint: "/health",
		},
		Secrets: SecretsConfig{
			CacheSize: 100,
		},
		Plugins: PluginsConfig{
			Enabled:     true,
			Directory:   "./plugins",
			PoolSize:    4,
			MaxExecTime: 5 * time.Second,
			MaxMemory:   64 * 1024 * 1024, // 64MB
		},
		EventBus: EventBusConfig{
			BufferSize:  1000,
			WorkerCount: 4,
		},
	}
}

// Load loads configuration from environment variables and config files.
func Load() (*Config, error) {
	// Load .env file if exists
	_ = godotenv.Load()

	cfg := Default()

	// Setup viper
	v := viper.New()
	v.SetConfigName("config")
	v.SetConfigType("yaml")
	v.AddConfigPath(".")
	v.AddConfigPath("./config")
	v.AddConfigPath("/etc/tetracore/")

	// Read config file if exists
	if err := v.ReadInConfig(); err != nil {
		if _, ok := err.(viper.ConfigFileNotFoundError); !ok {
			return nil, fmt.Errorf("error reading config file: %w", err)
		}
	}

	// Bind environment variables
	v.AutomaticEnv()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

	// Load from environment with custom mappings
	cfg.loadFromEnv()

	return cfg, nil
}

// loadFromEnv loads configuration from environment variables.
func (c *Config) loadFromEnv() {
	// App settings
	if env := os.Getenv("ENVIRONMENT"); env != "" {
		c.App.Environment = Environment(strings.ToLower(env))
	}
	if isHeroku() {
		c.App.Environment = EnvProduction
	}
	c.App.Debug = envBool("DEBUG", c.App.Debug)

	// Server settings
	c.Server.Host = envString("HOST", c.Server.Host)
	c.Server.Port = envInt("PORT", c.Server.Port)

	// Auth settings
	c.Auth.RequireAuth = envBool("REQUIRE_AUTHENTICATION", c.Auth.RequireAuth)
	c.Auth.AdminUsername = envString("ADMIN_USERNAME", c.Auth.AdminUsername)
	c.Auth.AdminPassword = envString("ADMIN_PASSWORD", c.Auth.AdminPassword)
	c.Auth.AdminPasswordHash = envString("ADMIN_PASSWORD_HASH", c.Auth.AdminPasswordHash)
	c.Auth.JWTSecret = envString("JWT_SECRET", c.Auth.JWTSecret)
	c.Auth.JWTIssuer = envString("JWT_ISSUER", c.Auth.JWTIssuer)

	// Redis settings - check multiple URL sources
	if url := os.Getenv("REDIS_TLS_URL"); url != "" {
		c.Redis.URL = url
	} else if url := os.Getenv("REDIS_URL"); url != "" {
		c.Redis.URL = url
	} else if url := os.Getenv("UPSTASH_REDIS_URL"); url != "" {
		c.Redis.URL = url
	} else if url := os.Getenv("REDISCLOUD_URL"); url != "" {
		c.Redis.URL = url
	}
	c.Redis.TLSEnabled = envBool("REDIS_TLS_ENABLED", c.Redis.TLSEnabled)
	c.Redis.TaskStream = envString("REDIS_TASK_STREAM", c.Redis.TaskStream)
	c.Redis.TaskStreamGroup = envString("REDIS_TASK_STREAM_GROUP", c.Redis.TaskStreamGroup)
	c.Redis.TaskStreamConsumer = envString("REDIS_TASK_STREAM_CONSUMER", c.Redis.TaskStreamConsumer)
	c.Redis.TaskStreamBlock = envDuration("REDIS_TASK_STREAM_BLOCK", c.Redis.TaskStreamBlock)
	c.Redis.TaskStreamBatch = envInt64("REDIS_TASK_STREAM_BATCH", c.Redis.TaskStreamBatch)
	c.Redis.TaskStreamMaxLen = envInt64("REDIS_TASK_STREAM_MAX_LEN", c.Redis.TaskStreamMaxLen)

	// Sentinel URLs
	if urls := os.Getenv("REDIS_SENTINEL_URLS"); urls != "" {
		c.Redis.SentinelURLs = strings.Split(urls, ",")
		for i := range c.Redis.SentinelURLs {
			c.Redis.SentinelURLs[i] = strings.TrimSpace(c.Redis.SentinelURLs[i])
		}
	}

	// Cluster nodes
	if nodes := os.Getenv("REDIS_CLUSTER_NODES"); nodes != "" {
		c.Redis.ClusterNodes = strings.Split(nodes, ",")
		for i := range c.Redis.ClusterNodes {
			c.Redis.ClusterNodes[i] = strings.TrimSpace(c.Redis.ClusterNodes[i])
		}
	}

	// Security settings
	c.Security.AuthToken = envString("AUTH_TOKEN", c.Security.AuthToken)
	c.Security.AuthTokenActive = envString("AUTH_TOKEN_ACTIVE", c.Security.AuthTokenActive)
	c.Security.AuthTokenNext = envString("AUTH_TOKEN_NEXT", c.Security.AuthTokenNext)
	c.Security.EnableTokenRotation = envBool("ENABLE_TOKEN_ROTATION", c.Security.EnableTokenRotation)

	// CORS origins
	if origins := os.Getenv("ALLOWED_ORIGINS"); origins != "" {
		c.Security.AllowedOrigins = strings.Split(origins, ",")
		for i := range c.Security.AllowedOrigins {
			c.Security.AllowedOrigins[i] = strings.TrimSpace(c.Security.AllowedOrigins[i])
		}
	}

	// Logging
	c.Logging.Level = envString("LOG_LEVEL", c.Logging.Level)

	// Secrets settings
	c.Secrets.EncryptionKey = envString("SECRETS_ENCRYPTION_KEY", c.Secrets.EncryptionKey)
	c.Secrets.CacheSize = envInt("SECRETS_CACHE_SIZE", c.Secrets.CacheSize)

	// Plugins settings
	c.Plugins.Enabled = envBool("PLUGINS_ENABLED", c.Plugins.Enabled)
	c.Plugins.Directory = envString("PLUGINS_DIRECTORY", c.Plugins.Directory)

	// Apply environment-specific overrides
	c.applyEnvironmentOverrides()
}

// applyEnvironmentOverrides applies environment-specific configuration.
func (c *Config) applyEnvironmentOverrides() {
	switch c.App.Environment {
	case EnvDevelopment:
		c.App.Debug = true
		c.Logging.Level = "debug"
		c.Logging.Format = "console"
	case EnvProduction:
		c.App.Debug = false
		c.Logging.Level = "warn"
		c.Logging.Format = "json"
		c.Security.EnableCompression = true
		// Add production CORS origins
		c.Security.AllowedOrigins = append(c.Security.AllowedOrigins,
			"https://hub.tetra-core.website",
			"https://tetra-core-hub-29fb6c8b7947.herokuapp.com",
		)
	case EnvTesting:
		c.App.Debug = true
		c.Logging.Level = "debug"
		c.Metrics.Enabled = false
	}
}

// Validate validates the configuration.
func (c *Config) Validate() error {
	// Validate port
	if c.Server.Port < 0 || c.Server.Port > 65535 {
		return fmt.Errorf("server port must be between 0 and 65535")
	}

	// Validate JWT secret when auth is required
	if c.Auth.RequireAuth && c.Auth.JWTSecret == "" {
		return fmt.Errorf("JWT_SECRET must be set when authentication is required")
	}

	// Production-specific validations
	if c.App.Environment == EnvProduction {
		if c.Auth.AdminUsername == "" || c.Auth.AdminPassword == "" {
			return fmt.Errorf("ADMIN_USERNAME and ADMIN_PASSWORD must be set in production")
		}
		if len(c.Auth.AdminPassword) < 8 {
			return fmt.Errorf("ADMIN_PASSWORD must be at least 8 characters")
		}
	}
	return nil
}

// IsProduction returns true if running in production environment.
func (c *Config) IsProduction() bool {
	return c.App.Environment == EnvProduction
}

// IsDevelopment returns true if running in development environment.
func (c *Config) IsDevelopment() bool {
	return c.App.Environment == EnvDevelopment
}

// IsTesting returns true if running in testing environment.
func (c *Config) IsTesting() bool {
	return c.App.Environment == EnvTesting
}

// GetServerAddress returns the server address string.
func (c *Config) GetServerAddress() string {
	return fmt.Sprintf("%s:%d", c.Server.Host, c.Server.Port)
}

// GetAppURL returns the application URL.
func (c *Config) GetAppURL() string {
	if c.IsProduction() {
		return "https://hub.tetra-core.website"
	}
	return fmt.Sprintf("http://localhost:%d", c.Server.Port)
}

// GetWebSocketURL returns the WebSocket URL.
func (c *Config) GetWebSocketURL() string {
	appURL := c.GetAppURL()
	protocol := "ws"
	if strings.HasPrefix(appURL, "https") {
		protocol = "wss"
	}
	domain := strings.TrimPrefix(strings.TrimPrefix(appURL, "https://"), "http://")
	return fmt.Sprintf("%s://%s%s", protocol, domain, c.WebSocket.Path)
}

// Helper functions

func isHeroku() bool {
	return os.Getenv("DYNO") != "" || (os.Getenv("PORT") != "" && os.Getenv("HOME") == "/app")
}

func envString(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func envInt(key string, defaultVal int) int {
	if val := os.Getenv(key); val != "" {
		var i int
		if _, err := fmt.Sscanf(val, "%d", &i); err == nil {
			return i
		}
	}
	return defaultVal
}

func envBool(key string, defaultVal bool) bool {
	if val := os.Getenv(key); val != "" {
		lower := strings.ToLower(val)
		return lower == "true" || lower == "1" || lower == "yes"
	}
	return defaultVal
}

func envInt64(key string, defaultVal int64) int64 {
	if val := os.Getenv(key); val != "" {
		var i int64
		if _, err := fmt.Sscanf(val, "%d", &i); err == nil {
			return i
		}
	}
	return defaultVal
}

func envDuration(key string, defaultVal time.Duration) time.Duration {
	if val := os.Getenv(key); val != "" {
		if parsed, err := time.ParseDuration(val); err == nil {
			return parsed
		}
	}
	return defaultVal
}
