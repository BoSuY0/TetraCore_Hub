// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// SessionService provides session management operations.
type SessionService interface {
	GetSession(ctx context.Context, sessionID string) (*entity.Session, error)
	GetAllSessions(ctx context.Context) ([]*entity.Session, error)
	GetSessionsByUser(ctx context.Context, userID string) ([]*entity.Session, error)
	InvalidateSession(ctx context.Context, sessionID string) error
	InvalidateUserSessions(ctx context.Context, userID string) error
	GetSessionCount(ctx context.Context) (int64, error)
}

// SessionHandler handles session management endpoints.
type SessionHandler struct {
	sessionService SessionService
}

// NewSessionHandler creates a new session handler.
func NewSessionHandler(sessionService SessionService) *SessionHandler {
	return &SessionHandler{
		sessionService: sessionService,
	}
}

// SessionResponse represents a session in API responses.
type SessionResponse struct {
	SessionID     string   `json:"session_id"`
	UserID        string   `json:"user_id"`
	Username      string   `json:"username"`
	Role          string   `json:"role"`
	Permissions   []string `json:"permissions"`
	CreatedAt     string   `json:"created_at"`
	ExpiresAt     string   `json:"expires_at"`
	LastActivity  string   `json:"last_activity"`
	IPAddress     string   `json:"ip_address,omitempty"`
	UserAgent     string   `json:"user_agent,omitempty"`
	IsActive      bool     `json:"is_active"`
	IsValid       bool     `json:"is_valid"`
	TimeRemaining string   `json:"time_remaining"`
}

// sessionToResponse converts a session entity to API response.
func sessionToResponse(s *entity.Session) *SessionResponse {
	return &SessionResponse{
		SessionID:     s.SessionID,
		UserID:        s.UserID,
		Username:      s.Username,
		Role:          s.Role,
		Permissions:   s.Permissions,
		CreatedAt:     s.CreatedAt.Format("2006-01-02T15:04:05Z"),
		ExpiresAt:     s.ExpiresAt.Format("2006-01-02T15:04:05Z"),
		LastActivity:  s.LastActivity.Format("2006-01-02T15:04:05Z"),
		IPAddress:     s.IPAddress,
		UserAgent:     s.UserAgent,
		IsActive:      s.IsActive,
		IsValid:       s.IsValid(),
		TimeRemaining: s.GetTimeRemaining().String(),
	}
}

// GetSessions handles GET /api/v1/sessions
func (h *SessionHandler) GetSessions(c *fiber.Ctx) error {
	// Parse query parameters
	userID := c.Query("user_id")

	var sessions []*entity.Session
	var err error

	if userID != "" {
		sessions, err = h.sessionService.GetSessionsByUser(c.Context(), userID)
	} else {
		sessions, err = h.sessionService.GetAllSessions(c.Context())
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve sessions",
			"code":    "INTERNAL_ERROR",
		})
	}

	// Convert to response format
	response := make([]*SessionResponse, len(sessions))
	for i, session := range sessions {
		response[i] = sessionToResponse(session)
	}

	return c.JSON(fiber.Map{
		"sessions": response,
		"total":    len(response),
	})
}

// GetSession handles GET /api/v1/sessions/:id
func (h *SessionHandler) GetSession(c *fiber.Ctx) error {
	sessionID := c.Params("id")
	if sessionID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Session ID is required",
			"code":    "MISSING_SESSION_ID",
		})
	}

	session, err := h.sessionService.GetSession(c.Context(), sessionID)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Session not found",
			"code":    "SESSION_NOT_FOUND",
		})
	}

	return c.JSON(sessionToResponse(session))
}

// DeleteSession handles DELETE /api/v1/sessions/:id
func (h *SessionHandler) DeleteSession(c *fiber.Ctx) error {
	sessionID := c.Params("id")
	if sessionID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Session ID is required",
			"code":    "MISSING_SESSION_ID",
		})
	}

	if err := h.sessionService.InvalidateSession(c.Context(), sessionID); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Session not found",
			"code":    "SESSION_NOT_FOUND",
		})
	}

	return c.JSON(fiber.Map{
		"message":    "Session invalidated successfully",
		"session_id": sessionID,
	})
}

// DeleteUserSessions handles DELETE /api/v1/sessions/user/:user_id
func (h *SessionHandler) DeleteUserSessions(c *fiber.Ctx) error {
	userID := c.Params("user_id")
	if userID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "User ID is required",
			"code":    "MISSING_USER_ID",
		})
	}

	if err := h.sessionService.InvalidateUserSessions(c.Context(), userID); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to invalidate sessions",
			"code":    "INTERNAL_ERROR",
		})
	}

	return c.JSON(fiber.Map{
		"message": "All user sessions invalidated successfully",
		"user_id": userID,
	})
}

// GetSessionStats handles GET /api/v1/sessions/stats
func (h *SessionHandler) GetSessionStats(c *fiber.Ctx) error {
	count, err := h.sessionService.GetSessionCount(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve stats",
			"code":    "INTERNAL_ERROR",
		})
	}

	return c.JSON(fiber.Map{
		"total_sessions": count,
	})
}
