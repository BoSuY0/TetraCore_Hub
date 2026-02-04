// Package http provides HTTP delivery layer for TetraCore Hub.
package http

import (
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/compress"
	"github.com/gofiber/fiber/v2/middleware/cors"
	"github.com/gofiber/fiber/v2/middleware/recover"
	"github.com/tetra/core-hub/internal/delivery/http/handler"
	"github.com/tetra/core-hub/internal/delivery/http/middleware"
	"github.com/tetra/core-hub/internal/infrastructure/security"
	"github.com/tetra/core-hub/pkg/logger"
)

// RouterConfig holds router configuration.
type RouterConfig struct {
	App            *fiber.App
	AuthMiddleware *middleware.AuthMiddleware
	RateLimiter    security.RateLimiter
	AllowedOrigins []string
	EnableCompress bool
}

// Router sets up all HTTP routes.
type Router struct {
	config RouterConfig
	log    logger.LogFields
}

// NewRouter creates a new HTTP router.
func NewRouter(cfg RouterConfig) *Router {
	return &Router{
		config: cfg,
		log:    logger.LogFields{"component": "http-router"},
	}
}

// Handlers holds all HTTP handlers.
type Handlers struct {
	Health   *handler.HealthHandler
	Auth     *handler.AuthHandler
	Client   *handler.ClientHandler
	Task     *handler.TaskHandler
	Session  *handler.SessionHandler
	Metrics  *handler.MetricsHandler
	Schedule *handler.ScheduleHandler
	Webhook  *handler.WebhookHandler
	Audit    *handler.AuditHandler
	TOTP     *handler.TOTPHandler
	User     *handler.UserHandler
	Role     *handler.RoleHandler
	APIKey   *handler.APIKeyHandler
	Secrets  *handler.SecretsHandler
	DLQ      *handler.DLQHandler
	Template *handler.TemplateHandler
	Plugins  *handler.PluginsHandler
}

// Setup configures all routes and middleware.
func (r *Router) Setup(handlers Handlers) {
	log := logger.WithFields(r.log)
	log.Info().Msg("Setting up HTTP routes")

	// Global middleware
	r.setupMiddleware()

	// API routes
	r.setupRoutes(handlers)
}

func (r *Router) setupMiddleware() {
	app := r.config.App

	// Recovery middleware
	app.Use(recover.New(recover.Config{
		EnableStackTrace: true,
	}))

	// Request ID middleware
	app.Use(middleware.RequestID())

	// Logger middleware
	app.Use(middleware.Logger())

	// Security headers middleware
	app.Use(middleware.SecurityHeaders())

	// CORS middleware
	origins := stringSliceToString(r.config.AllowedOrigins)
	// AllowCredentials cannot be true with wildcard origins
	allowCredentials := origins != "*"
	app.Use(cors.New(cors.Config{
		AllowOrigins:     origins,
		AllowMethods:     "GET,POST,PUT,DELETE,OPTIONS,PATCH",
		AllowHeaders:     "Origin,Content-Type,Accept,Authorization,X-Request-ID,X-Refresh-Token",
		AllowCredentials: allowCredentials,
		ExposeHeaders:    "Content-Length,Content-Type,X-Request-ID",
		MaxAge:           int(12 * time.Hour / time.Second),
	}))

	// Compression middleware
	if r.config.EnableCompress {
		app.Use(compress.New(compress.Config{
			Level: compress.LevelDefault,
		}))
	}

	// Rate limiter middleware (if configured)
	if r.config.RateLimiter != nil {
		app.Use(middleware.RateLimit(r.config.RateLimiter))
	}
}

func (r *Router) setupRoutes(h Handlers) {
	app := r.config.App

	// Health check (no auth required)
	app.Get("/health", h.Health.HealthCheck)
	app.Get("/ready", h.Health.ReadyCheck)
	app.Get("/live", h.Health.LiveCheck)
	app.Get("/stats", h.Health.Stats)

	// Metrics (no auth required for Prometheus scraping)
	if h.Metrics != nil {
		app.Get("/metrics", h.Metrics.PrometheusMetrics)
	}

	// Admin UI (static files)
	app.Static("/admin", "./web/admin")

	// Auth routes (no auth required)
	auth := app.Group("/auth")
	auth.Post("/login", h.Auth.Login)
	auth.Post("/refresh", h.Auth.RefreshToken)

	// Logout requires auth
	auth.Post("/logout", r.config.AuthMiddleware.Handler(), h.Auth.Logout)

	// Backward/alternate compatibility routes (some clients expect versioned auth under /v1).
	v1auth := app.Group("/v1/auth")
	v1auth.Post("/login", h.Auth.Login)
	v1auth.Post("/refresh", h.Auth.RefreshToken)
	v1auth.Post("/logout", r.config.AuthMiddleware.Handler(), h.Auth.Logout)

	// API routes (auth required)
	api := app.Group("/api/v1")
	api.Use(r.config.AuthMiddleware.Handler())

	// Client management
	api.Get("/clients/stats", h.Client.GetClientStats)
	api.Get("/clients", h.Client.GetClients)
	api.Get("/clients/:id", h.Client.GetClient)
	api.Delete("/clients/:id", h.Client.DeleteClient)
	api.Post("/clients/:id/disconnect", h.Client.DisconnectClient)

	// Task management
	api.Get("/tasks/stats", h.Task.GetTaskStats)
	api.Get("/tasks", h.Task.GetTasks)
	api.Post("/tasks", h.Task.SubmitTask)
	api.Get("/tasks/:id", h.Task.GetTask)
	api.Delete("/tasks/:id", h.Task.DeleteTask)
	api.Post("/tasks/:id/cancel", h.Task.CancelTask)
	api.Post("/tasks/:id/retry", h.Task.RetryTask)

	// Sessions
	api.Get("/sessions/stats", h.Session.GetSessionStats)
	api.Get("/sessions", h.Session.GetSessions)
	api.Get("/sessions/:id", h.Session.GetSession)
	api.Delete("/sessions/:id", h.Session.DeleteSession)
	api.Delete("/sessions/user/:user_id", h.Session.DeleteUserSessions)

	// Schedules (if handler is configured)
	if h.Schedule != nil {
		api.Get("/schedules", h.Schedule.GetSchedules)
		api.Post("/schedules", h.Schedule.CreateSchedule)
		api.Get("/schedules/:id", h.Schedule.GetSchedule)
		api.Put("/schedules/:id", h.Schedule.UpdateSchedule)
		api.Delete("/schedules/:id", h.Schedule.DeleteSchedule)
		api.Post("/schedules/:id/enable", h.Schedule.EnableSchedule)
		api.Post("/schedules/:id/disable", h.Schedule.DisableSchedule)
	}

	// Webhooks (if handler is configured)
	if h.Webhook != nil {
		api.Get("/webhooks/events", h.Webhook.GetWebhookEvents)
		api.Get("/webhooks", h.Webhook.GetWebhooks)
		api.Post("/webhooks", h.Webhook.CreateWebhook)
		api.Get("/webhooks/:id", h.Webhook.GetWebhook)
		api.Put("/webhooks/:id", h.Webhook.UpdateWebhook)
		api.Delete("/webhooks/:id", h.Webhook.DeleteWebhook)
		api.Post("/webhooks/:id/enable", h.Webhook.EnableWebhook)
		api.Post("/webhooks/:id/disable", h.Webhook.DisableWebhook)
		api.Post("/webhooks/:id/test", h.Webhook.TestWebhook)
	}

	// Audit logs (if handler is configured)
	if h.Audit != nil {
		api.Get("/audit/actions", h.Audit.GetAuditActions)
		api.Get("/audit", h.Audit.GetAuditLogs)
		api.Get("/audit/:id", h.Audit.GetAuditEntry)
	}

	// 2FA routes (requires auth)
	if h.TOTP != nil {
		twoFA := app.Group("/auth/2fa")
		twoFA.Use(r.config.AuthMiddleware.Handler())
		twoFA.Post("/setup", h.TOTP.Setup)
		twoFA.Post("/verify", h.TOTP.Verify)
		twoFA.Post("/disable", h.TOTP.Disable)
		twoFA.Get("/status", h.TOTP.Status)
		twoFA.Post("/backup-codes", h.TOTP.RegenerateBackupCodes)
	}

	// User management (if handler is configured)
	if h.User != nil {
		api.Get("/users/me", h.User.GetCurrentUser)
		api.Put("/users/me/password", h.User.ChangePassword)
		api.Get("/users", h.User.GetUsers)
		api.Post("/users", h.User.CreateUser)
		api.Get("/users/:id", h.User.GetUser)
		api.Put("/users/:id", h.User.UpdateUser)
		api.Delete("/users/:id", h.User.DeleteUser)
		api.Post("/users/:id/reset-password", h.User.ResetPassword)
	}

	// Role management (if handler is configured)
	if h.Role != nil {
		api.Get("/roles/permissions", h.Role.GetPermissions)
		api.Get("/roles", h.Role.GetRoles)
		api.Post("/roles", h.Role.CreateRole)
		api.Get("/roles/:id", h.Role.GetRole)
		api.Put("/roles/:id", h.Role.UpdateRole)
		api.Delete("/roles/:id", h.Role.DeleteRole)
	}

	// API Key management (if handler is configured)
	if h.APIKey != nil {
		api.Get("/apikeys", h.APIKey.GetAPIKeys)
		api.Post("/apikeys", h.APIKey.CreateAPIKey)
		api.Get("/apikeys/all", h.APIKey.GetAllAPIKeys) // Admin only
		api.Get("/apikeys/:id", h.APIKey.GetAPIKey)
		api.Delete("/apikeys/:id", h.APIKey.DeleteAPIKey)
		api.Post("/apikeys/:id/rotate", h.APIKey.RotateAPIKey)
		api.Post("/apikeys/:id/activate", h.APIKey.ActivateAPIKey)
		api.Post("/apikeys/:id/deactivate", h.APIKey.DeactivateAPIKey)
	}

	// Secrets management (if handler is configured)
	if h.Secrets != nil {
		api.Get("/secrets", h.Secrets.GetSecrets)
		api.Post("/secrets", h.Secrets.CreateSecret)
		api.Get("/secrets/:key", h.Secrets.GetSecret)
		api.Get("/secrets/:key/value", h.Secrets.GetSecretValue)
		api.Put("/secrets/:key", h.Secrets.UpdateSecret)
		api.Delete("/secrets/:key", h.Secrets.DeleteSecret)
	}

	// Dead Letter Queue (if handler is configured)
	if h.DLQ != nil {
		api.Get("/dlq/stats", h.DLQ.GetDLQStats)
		api.Get("/dlq", h.DLQ.GetDLQEntries)
		api.Get("/dlq/:id", h.DLQ.GetDLQEntry)
		api.Post("/dlq/:id/retry", h.DLQ.RetryDLQEntry)
		api.Post("/dlq/:id/schedule", h.DLQ.ScheduleRetryDLQEntry)
		api.Delete("/dlq/:id", h.DLQ.DeleteDLQEntry)
		api.Post("/dlq/retry-all", h.DLQ.RetryAllDLQEntries)
		api.Delete("/dlq/purge", h.DLQ.PurgeDLQ)
	}

	// Task Templates (if handler is configured)
	if h.Template != nil {
		api.Get("/templates/my", h.Template.GetMyTemplates)
		api.Get("/templates", h.Template.GetTemplates)
		api.Post("/templates", h.Template.CreateTemplate)
		api.Get("/templates/:id", h.Template.GetTemplate)
		api.Put("/templates/:id", h.Template.UpdateTemplate)
		api.Delete("/templates/:id", h.Template.DeleteTemplate)
		api.Post("/templates/:id/execute", h.Template.ExecuteTemplate)
	}

	// Plugins (if handler is configured)
	if h.Plugins != nil {
		api.Get("/plugins/hooks", h.Plugins.GetHooks)
		api.Get("/plugins/hooks/:hook", h.Plugins.GetHookPlugins)
		api.Get("/plugins", h.Plugins.GetPlugins)
		api.Post("/plugins", h.Plugins.LoadPlugin)
		api.Post("/plugins/reload", h.Plugins.ReloadPlugins)
		api.Get("/plugins/:id", h.Plugins.GetPlugin)
		api.Delete("/plugins/:id", h.Plugins.UnloadPlugin)
		api.Post("/plugins/:id/enable", h.Plugins.EnablePlugin)
		api.Post("/plugins/:id/disable", h.Plugins.DisablePlugin)
	}

}

// SetupNotFound registers the catch-all 404 handler.
// Must be called AFTER all routes (including WebSocket) are registered.
func (r *Router) SetupNotFound() {
	r.config.App.Use(notFoundHandler)
}

// ErrorHandler is the global error handler for Fiber.
func ErrorHandler(c *fiber.Ctx, err error) error {
	code := fiber.StatusInternalServerError
	message := "Internal server error"

	if e, ok := err.(*fiber.Error); ok {
		code = e.Code
		message = e.Message
	}

	return c.Status(code).JSON(fiber.Map{
		"error":   true,
		"message": message,
		"code":    code,
	})
}

// 404 handler
func notFoundHandler(c *fiber.Ctx) error {
	return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
		"error":   true,
		"message": "Not found",
		"code":    404,
	})
}

// Helper function to convert string slice to comma-separated string
func stringSliceToString(s []string) string {
	if len(s) == 0 {
		return "*"
	}
	result := ""
	for i, v := range s {
		if i > 0 {
			result += ","
		}
		result += v
	}
	return result
}
