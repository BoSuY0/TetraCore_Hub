// Package middleware provides HTTP middleware for TetraCore Hub.
package middleware

import (
	"strings"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/usecase/apikey"
	"github.com/tetra/core-hub/pkg/logger"
)

// APIKeyMiddleware provides API key authentication middleware.
type APIKeyMiddleware struct {
	apiKeyUseCase *apikey.UseCase
	log           logger.LogFields
}

// NewAPIKeyMiddleware creates a new API key middleware.
func NewAPIKeyMiddleware(apiKeyUseCase *apikey.UseCase) *APIKeyMiddleware {
	return &APIKeyMiddleware{
		apiKeyUseCase: apiKeyUseCase,
		log:           logger.LogFields{"component": "apikey-middleware"},
	}
}

// Handler returns the API key authentication middleware handler.
// This middleware checks for API key in X-API-Key header or Authorization header.
func (m *APIKeyMiddleware) Handler() fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Get API key from header
		apiKeyStr := c.Get("X-API-Key")
		if apiKeyStr == "" {
			// Try Authorization header with Bearer prefix
			auth := c.Get("Authorization")
			if strings.HasPrefix(auth, "Bearer tk_") {
				apiKeyStr = strings.TrimPrefix(auth, "Bearer ")
			}
		}

		if apiKeyStr == "" {
			return c.Next() // No API key, let other auth methods handle it
		}

		// Validate API key
		ip := c.IP()
		key, err := m.apiKeyUseCase.ValidateKeyWithIP(c.Context(), apiKeyStr, ip)
		if err != nil {
			log := logger.WithFields(m.log)
			switch err {
			case entity.ErrAPIKeyInvalid:
				log.Debug().Str("ip", ip).Msg("Invalid API key")
				return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
					"error":   true,
					"message": "Invalid API key",
				})
			case entity.ErrAPIKeyExpired:
				return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
					"error":   true,
					"message": "API key has expired",
				})
			case entity.ErrAPIKeyInactive:
				return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
					"error":   true,
					"message": "API key is inactive",
				})
			case entity.ErrAPIKeyIPNotAllowed:
				log.Warn().Str("ip", ip).Str("key_id", key.ID).Msg("IP not allowed for API key")
				return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
					"error":   true,
					"message": "IP address not allowed",
				})
			default:
				log.Error().Err(err).Msg("Failed to validate API key")
				return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
					"error":   true,
					"message": "Authentication failed",
				})
			}
		}

		// Record usage (async, don't block request)
		go func() {
			_ = m.apiKeyUseCase.RecordUsage(c.Context(), key.ID, ip)
		}()

		// Set context values
		c.Locals("api_key_id", key.ID)
		c.Locals("user_id", key.UserID)
		c.Locals("role_id", string(key.RoleID))
		c.Locals("auth_method", "api_key")

		// Load permissions
		perms, err := m.apiKeyUseCase.GetKeyPermissions(c.Context(), key.ID)
		if err == nil {
			c.Locals("permissions", perms)
		}

		return c.Next()
	}
}

// RequireAPIKey returns middleware that requires API key authentication.
func (m *APIKeyMiddleware) RequireAPIKey() fiber.Handler {
	return func(c *fiber.Ctx) error {
		if c.Locals("api_key_id") == nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "API key required",
			})
		}
		return c.Next()
	}
}

// OptionalAPIKey returns middleware that accepts but doesn't require API key.
// Useful for endpoints that have different behavior for authenticated vs anonymous.
func (m *APIKeyMiddleware) OptionalAPIKey() fiber.Handler {
	return m.Handler()
}

// GetAPIKeyID returns the API key ID from context.
func GetAPIKeyID(c *fiber.Ctx) string {
	id := c.Locals("api_key_id")
	if id == nil {
		return ""
	}
	return id.(string)
}

// GetAuthMethod returns the authentication method from context.
func GetAuthMethod(c *fiber.Ctx) string {
	method := c.Locals("auth_method")
	if method == nil {
		return ""
	}
	return method.(string)
}

// IsAPIKeyAuth returns true if the request was authenticated via API key.
func IsAPIKeyAuth(c *fiber.Ctx) bool {
	return GetAuthMethod(c) == "api_key"
}
