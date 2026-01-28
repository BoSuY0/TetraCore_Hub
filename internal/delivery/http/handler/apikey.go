// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/usecase/apikey"
	"github.com/tetra/core-hub/pkg/logger"
)

// APIKeyHandler handles API key-related HTTP requests.
type APIKeyHandler struct {
	apiKeyUseCase *apikey.UseCase
	log           logger.LogFields
}

// NewAPIKeyHandler creates a new APIKeyHandler.
func NewAPIKeyHandler(apiKeyUseCase *apikey.UseCase) *APIKeyHandler {
	return &APIKeyHandler{
		apiKeyUseCase: apiKeyUseCase,
		log:           logger.LogFields{"component": "apikey-handler"},
	}
}

// CreateAPIKeyRequest represents a create API key request.
type CreateAPIKeyRequest struct {
	Name        string               `json:"name" validate:"required,min=1,max=100"`
	RoleID      entity.RoleID        `json:"role_id" validate:"required"`
	Permissions []entity.Permission  `json:"permissions,omitempty"`
	RateLimit   int                  `json:"rate_limit,omitempty"`
	ExpiresIn   string               `json:"expires_in,omitempty"` // Duration string like "24h", "30d"
	Metadata    entity.APIKeyMetadata `json:"metadata,omitempty"`
}

// GetAPIKeys returns all API keys for the current user.
func (h *APIKeyHandler) GetAPIKeys(c *fiber.Ctx) error {
	userID := c.Locals("user_id")
	if userID == nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Unauthorized",
		})
	}

	keys, err := h.apiKeyUseCase.ListUserKeys(c.Context(), userID.(string))
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get API keys",
		})
	}

	// Convert to public representation
	publicKeys := make([]entity.APIKeyPublic, len(keys))
	for i, key := range keys {
		publicKeys[i] = key.ToPublic()
	}

	return c.JSON(fiber.Map{
		"api_keys": publicKeys,
		"count":    len(publicKeys),
	})
}

// GetAllAPIKeys returns all API keys (admin only).
func (h *APIKeyHandler) GetAllAPIKeys(c *fiber.Ctx) error {
	filter := repository.APIKeyFilter{
		UserID: c.Query("user_id"),
		Limit:  c.QueryInt("limit", 50),
		Offset: c.QueryInt("offset", 0),
	}

	if c.Query("active") == "true" {
		active := true
		filter.IsActive = &active
	} else if c.Query("active") == "false" {
		active := false
		filter.IsActive = &active
	}

	keys, err := h.apiKeyUseCase.ListKeys(c.Context(), filter)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get API keys",
		})
	}

	publicKeys := make([]entity.APIKeyPublic, len(keys))
	for i, key := range keys {
		publicKeys[i] = key.ToPublic()
	}

	return c.JSON(fiber.Map{
		"api_keys": publicKeys,
		"count":    len(publicKeys),
	})
}

// GetAPIKey returns a single API key by ID.
func (h *APIKeyHandler) GetAPIKey(c *fiber.Ctx) error {
	id := c.Params("id")
	userID := c.Locals("user_id")

	key, err := h.apiKeyUseCase.GetKey(c.Context(), id)
	if err != nil {
		if err == entity.ErrAPIKeyNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "API key not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get API key",
		})
	}

	// Check ownership (unless admin)
	roleID := c.Locals("role_id")
	if roleID != nil && entity.RoleID(roleID.(string)) != entity.RoleAdmin {
		if userID != nil && key.UserID != userID.(string) {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
			})
		}
	}

	return c.JSON(key.ToPublic())
}

// CreateAPIKey creates a new API key.
func (h *APIKeyHandler) CreateAPIKey(c *fiber.Ctx) error {
	userID := c.Locals("user_id")
	if userID == nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Unauthorized",
		})
	}

	var req CreateAPIKeyRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	input := apikey.CreateKeyInput{
		Name:        req.Name,
		UserID:      userID.(string),
		RoleID:      req.RoleID,
		Permissions: req.Permissions,
		RateLimit:   req.RateLimit,
		Metadata:    req.Metadata,
	}

	// Parse expiration duration
	if req.ExpiresIn != "" {
		duration, err := time.ParseDuration(req.ExpiresIn)
		if err != nil {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"error":   true,
				"message": "Invalid expires_in format",
			})
		}
		input.ExpiresIn = &duration
	}

	result, err := h.apiKeyUseCase.CreateKey(c.Context(), input)
	if err != nil {
		log := logger.WithFields(h.log)
		log.Error().Err(err).Msg("Failed to create API key")
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": err.Error(),
		})
	}

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"api_key":   result.APIKey.ToPublic(),
		"plain_key": result.PlainKey,
		"warning":   "Store this key securely. It will not be shown again.",
	})
}

// DeleteAPIKey deletes an API key.
func (h *APIKeyHandler) DeleteAPIKey(c *fiber.Ctx) error {
	id := c.Params("id")
	userID := c.Locals("user_id")

	// Check ownership
	key, err := h.apiKeyUseCase.GetKey(c.Context(), id)
	if err != nil {
		if err == entity.ErrAPIKeyNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "API key not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get API key",
		})
	}

	// Check ownership (unless admin)
	roleID := c.Locals("role_id")
	if roleID != nil && entity.RoleID(roleID.(string)) != entity.RoleAdmin {
		if userID != nil && key.UserID != userID.(string) {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
			})
		}
	}

	if err := h.apiKeyUseCase.DeleteKey(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete API key",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "API key deleted",
	})
}

// RotateAPIKey rotates an API key.
func (h *APIKeyHandler) RotateAPIKey(c *fiber.Ctx) error {
	id := c.Params("id")
	userID := c.Locals("user_id")

	// Check ownership
	key, err := h.apiKeyUseCase.GetKey(c.Context(), id)
	if err != nil {
		if err == entity.ErrAPIKeyNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "API key not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get API key",
		})
	}

	// Check ownership (unless admin)
	roleID := c.Locals("role_id")
	if roleID != nil && entity.RoleID(roleID.(string)) != entity.RoleAdmin {
		if userID != nil && key.UserID != userID.(string) {
			return c.Status(fiber.StatusForbidden).JSON(fiber.Map{
				"error":   true,
				"message": "Access denied",
			})
		}
	}

	result, err := h.apiKeyUseCase.RotateKey(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to rotate API key",
		})
	}

	return c.JSON(fiber.Map{
		"api_key":      result.APIKey.ToPublic(),
		"plain_key":    result.PlainKey,
		"old_key_id":   id,
		"warning":      "Store this key securely. It will not be shown again.",
	})
}

// DeactivateAPIKey deactivates an API key.
func (h *APIKeyHandler) DeactivateAPIKey(c *fiber.Ctx) error {
	id := c.Params("id")

	if err := h.apiKeyUseCase.DeactivateKey(c.Context(), id); err != nil {
		if err == entity.ErrAPIKeyNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "API key not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to deactivate API key",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "API key deactivated",
	})
}

// ActivateAPIKey activates an API key.
func (h *APIKeyHandler) ActivateAPIKey(c *fiber.Ctx) error {
	id := c.Params("id")

	if err := h.apiKeyUseCase.ActivateKey(c.Context(), id); err != nil {
		if err == entity.ErrAPIKeyNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "API key not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to activate API key",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "API key activated",
	})
}
