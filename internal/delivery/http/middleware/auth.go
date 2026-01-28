// Package middleware provides HTTP middleware for TetraCore Hub.
package middleware

import (
	"context"
	"strings"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/infrastructure/security"
)

// SessionValidator validates authentication tokens.
type SessionValidator interface {
	ValidateToken(ctx context.Context, token string) (*entity.Session, error)
}

// AuthMiddleware handles JWT authentication.
type AuthMiddleware struct {
	jwtManager       *security.JWTManager
	sessionValidator SessionValidator
}

// NewAuthMiddleware creates a new auth middleware.
func NewAuthMiddleware(jwtManager *security.JWTManager, sessionValidator SessionValidator) *AuthMiddleware {
	return &AuthMiddleware{
		jwtManager:       jwtManager,
		sessionValidator: sessionValidator,
	}
}

// Handler returns the Fiber middleware handler.
func (m *AuthMiddleware) Handler() fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Get token from Authorization header
		authHeader := c.Get("Authorization")
		if authHeader == "" {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Missing authorization header",
				"code":    "UNAUTHORIZED",
			})
		}

		// Extract token from "Bearer <token>" format
		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || strings.ToLower(parts[0]) != "bearer" {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid authorization header format",
				"code":    "INVALID_AUTH_FORMAT",
			})
		}

		tokenString := parts[1]

		// Validate token using session validator
		session, err := m.sessionValidator.ValidateToken(c.Context(), tokenString)
		if err != nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid or expired token",
				"code":    "INVALID_TOKEN",
			})
		}

		// Store session info in context
		c.Locals("session", session)
		c.Locals("session_id", session.SessionID)
		c.Locals("user_id", session.UserID)
		c.Locals("token", tokenString)

		// Check if token needs refresh
		if session.ShouldRefresh {
			c.Set("X-Token-Refresh", "true")
		}

		return c.Next()
	}
}

// Auth creates JWT authentication middleware (legacy function for backward compatibility).
func Auth(secret string) fiber.Handler {
	return func(c *fiber.Ctx) error {
		// Get token from Authorization header
		authHeader := c.Get("Authorization")
		if authHeader == "" {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Missing authorization header",
				"code":    "UNAUTHORIZED",
			})
		}

		// Extract token from "Bearer <token>" format
		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || strings.ToLower(parts[0]) != "bearer" {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid authorization header format",
				"code":    "INVALID_AUTH_FORMAT",
			})
		}

		tokenString := parts[1]

		// Create temporary JWT manager for validation
		jwtMgr := security.NewJWTManagerSimple(secret, "")
		claims, err := jwtMgr.ValidateToken(tokenString)
		if err != nil {
			return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid or expired token",
				"code":    "INVALID_TOKEN",
			})
		}

		// Store user info in context
		c.Locals("user_id", claims.Subject)
		c.Locals("token", tokenString)

		return c.Next()
	}
}

// RequireRole creates middleware that requires a specific role.
func RequireRole(roles ...string) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userRole := c.Locals("role")
		if userRole == nil {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
				"code":    "FORBIDDEN",
			})
		}

		role := userRole.(string)

		// Admin has access to everything
		if role == "admin" {
			return c.Next()
		}

		// Check if user has required role
		for _, r := range roles {
			if role == r {
				return c.Next()
			}
		}

		return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
			"error":   true,
			"message": "Insufficient permissions",
			"code":    "INSUFFICIENT_PERMISSIONS",
		})
	}
}

// RateLimit creates rate limiting middleware.
func RateLimit(limiter security.RateLimiter) fiber.Handler {
	return func(c *fiber.Ctx) error {
		key := c.IP()

		result, err := limiter.Allow(c.Context(), key)
		if err != nil {
			// On error, allow the request
			return c.Next()
		}

		if !result.Allowed {
			return c.Status(fiber.StatusTooManyRequests).JSON(fiber.Map{
				"error":   true,
				"message": "Rate limit exceeded",
				"code":    "RATE_LIMITED",
			})
		}

		return c.Next()
	}
}

// OptionalAuth creates optional authentication middleware.
// It validates the token if present but allows requests without a token.
func OptionalAuth(jwtManager *security.JWTManager) fiber.Handler {
	return func(c *fiber.Ctx) error {
		authHeader := c.Get("Authorization")
		if authHeader == "" {
			return c.Next()
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || strings.ToLower(parts[0]) != "bearer" {
			return c.Next()
		}

		tokenString := parts[1]

		claims, err := jwtManager.ValidateToken(tokenString)
		if err != nil {
			return c.Next()
		}

		c.Locals("user_id", claims.Subject)
		c.Locals("token", tokenString)

		return c.Next()
	}
}
