// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// AuthService provides authentication operations.
type AuthService interface {
	Login(ctx context.Context, input LoginInput) (*LoginOutput, error)
	Logout(ctx context.Context, sessionID string) error
	RefreshToken(ctx context.Context, refreshToken string) (*LoginOutput, error)
	ValidateToken(ctx context.Context, token string) (*entity.Session, error)
}

// LoginInput represents login credentials.
type LoginInput struct {
	Username  string
	Password  string
	IPAddress string
	UserAgent string
}

// LoginOutput represents successful login result.
type LoginOutput struct {
	Session      *entity.Session
	AccessToken  string
	RefreshToken string
	ExpiresAt    time.Time
}

// AuthHandler handles authentication endpoints.
type AuthHandler struct {
	authService AuthService
}

// NewAuthHandler creates a new auth handler.
func NewAuthHandler(authService AuthService) *AuthHandler {
	return &AuthHandler{
		authService: authService,
	}
}

// LoginRequest represents a login request.
type LoginRequest struct {
	Username string `json:"username" validate:"required"`
	Password string `json:"password" validate:"required"`
}

// LoginResponse represents a login response.
type LoginResponse struct {
	AccessToken  string    `json:"access_token"`
	RefreshToken string    `json:"refresh_token"`
	TokenType    string    `json:"token_type"`
	ExpiresAt    time.Time `json:"expires_at"`
	SessionID    string    `json:"session_id"`
}

// Login handles the /auth/login endpoint.
func (h *AuthHandler) Login(c *fiber.Ctx) error {
	var req LoginRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	if req.Username == "" || req.Password == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Username and password are required",
			"code":    "MISSING_CREDENTIALS",
		})
	}

	// Get client info
	ipAddress := c.IP()
	userAgent := c.Get("User-Agent")

	// Attempt login
	result, err := h.authService.Login(c.Context(), LoginInput{
		Username:  req.Username,
		Password:  req.Password,
		IPAddress: ipAddress,
		UserAgent: userAgent,
	})
	if err != nil {
		// Check for rate limiting
		if isRateLimitError(err) {
			return c.Status(fiber.StatusTooManyRequests).JSON(fiber.Map{
				"error":   true,
				"message": err.Error(),
				"code":    "TOO_MANY_ATTEMPTS",
			})
		}
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid credentials",
			"code":    "INVALID_CREDENTIALS",
		})
	}

	return c.JSON(LoginResponse{
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		TokenType:    "Bearer",
		ExpiresAt:    result.ExpiresAt,
		SessionID:    result.Session.SessionID,
	})
}

// RefreshRequest represents a token refresh request.
type RefreshRequest struct {
	RefreshToken string `json:"refresh_token" validate:"required"`
}

// RefreshToken handles the /auth/refresh endpoint.
func (h *AuthHandler) RefreshToken(c *fiber.Ctx) error {
	var req RefreshRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	if req.RefreshToken == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Refresh token is required",
			"code":    "MISSING_TOKEN",
		})
	}

	// Refresh tokens
	result, err := h.authService.RefreshToken(c.Context(), req.RefreshToken)
	if err != nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid or expired refresh token",
			"code":    "INVALID_REFRESH_TOKEN",
		})
	}

	return c.JSON(LoginResponse{
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		TokenType:    "Bearer",
		ExpiresAt:    result.ExpiresAt,
		SessionID:    result.Session.SessionID,
	})
}

// Logout handles the /auth/logout endpoint.
func (h *AuthHandler) Logout(c *fiber.Ctx) error {
	// Get session ID from context (set by auth middleware)
	sessionID := c.Locals("session_id")
	if sessionID == nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "No active session",
			"code":    "NO_SESSION",
		})
	}

	if err := h.authService.Logout(c.Context(), sessionID.(string)); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to logout",
			"code":    "LOGOUT_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"message": "Logged out successfully",
	})
}

// isRateLimitError checks if the error is a rate limit error.
func isRateLimitError(err error) bool {
	if err == nil {
		return false
	}
	// Check error message for rate limit indicators
	msg := err.Error()
	return len(msg) > 0 && (msg[0] == 'A' && len(msg) > 20) // "Account locked" prefix
}
