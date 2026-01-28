// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/infrastructure/secrets"
	"github.com/tetra/core-hub/pkg/logger"
)

// SecretsHandler handles secrets-related HTTP requests.
type SecretsHandler struct {
	manager *secrets.Manager
	log     logger.LogFields
}

// NewSecretsHandler creates a new SecretsHandler.
func NewSecretsHandler(manager *secrets.Manager) *SecretsHandler {
	return &SecretsHandler{
		manager: manager,
		log:     logger.LogFields{"component": "secrets-handler"},
	}
}

// CreateSecretRequest represents a create secret request.
type CreateSecretRequest struct {
	Key         string            `json:"key" validate:"required,min=1,max=255"`
	Value       string            `json:"value" validate:"required"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
}

// UpdateSecretRequest represents an update secret request.
type UpdateSecretRequest struct {
	Value       string            `json:"value" validate:"required"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
}

// GetSecrets returns all secrets (metadata only, no values).
func (h *SecretsHandler) GetSecrets(c *fiber.Ctx) error {
	tag := c.Query("tag")

	var secretsList []secrets.SecretPublic
	var err error

	if tag != "" {
		secretsList, err = h.manager.ListByTag(c.Context(), tag)
	} else {
		secretsList, err = h.manager.List(c.Context())
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to list secrets",
		})
	}

	return c.JSON(fiber.Map{
		"secrets": secretsList,
		"count":   len(secretsList),
	})
}

// GetSecret returns a single secret's metadata (no value).
func (h *SecretsHandler) GetSecret(c *fiber.Ctx) error {
	key := c.Params("key")

	secret, err := h.manager.GetSecret(c.Context(), key)
	if err != nil {
		if err == secrets.ErrSecretNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Secret not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get secret",
		})
	}

	return c.JSON(secret.ToPublic())
}

// GetSecretValue returns a secret's value.
func (h *SecretsHandler) GetSecretValue(c *fiber.Ctx) error {
	key := c.Params("key")

	value, err := h.manager.Get(c.Context(), key)
	if err != nil {
		if err == secrets.ErrSecretNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Secret not found",
			})
		}
		log := logger.WithFields(h.log)
		log.Error().Err(err).Str("key", key).Msg("Failed to get secret value")
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get secret value",
		})
	}

	return c.JSON(fiber.Map{
		"key":   key,
		"value": value,
	})
}

// CreateSecret creates a new secret.
func (h *SecretsHandler) CreateSecret(c *fiber.Ctx) error {
	var req CreateSecretRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	// Check if secret already exists
	exists, _ := h.manager.Exists(c.Context(), req.Key)
	if exists {
		return c.Status(fiber.StatusConflict).JSON(fiber.Map{
			"error":   true,
			"message": "Secret already exists",
		})
	}

	// Get user ID from context
	userID := ""
	if id := c.Locals("user_id"); id != nil {
		userID = id.(string)
	}

	opts := []secrets.SetOption{
		secrets.WithDescription(req.Description),
		secrets.WithTags(req.Tags...),
		secrets.WithMetadata(req.Metadata),
		secrets.WithCreatedBy(userID),
		secrets.WithUpdatedBy(userID),
	}

	if err := h.manager.Set(c.Context(), req.Key, req.Value, opts...); err != nil {
		log := logger.WithFields(h.log)
		log.Error().Err(err).Str("key", req.Key).Msg("Failed to create secret")
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create secret",
		})
	}

	secret, _ := h.manager.GetSecret(c.Context(), req.Key)

	return c.Status(fiber.StatusCreated).JSON(secret.ToPublic())
}

// UpdateSecret updates an existing secret.
func (h *SecretsHandler) UpdateSecret(c *fiber.Ctx) error {
	key := c.Params("key")

	// Check if secret exists
	exists, _ := h.manager.Exists(c.Context(), key)
	if !exists {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Secret not found",
		})
	}

	var req UpdateSecretRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	// Get user ID from context
	userID := ""
	if id := c.Locals("user_id"); id != nil {
		userID = id.(string)
	}

	opts := []secrets.SetOption{
		secrets.WithDescription(req.Description),
		secrets.WithTags(req.Tags...),
		secrets.WithMetadata(req.Metadata),
		secrets.WithUpdatedBy(userID),
	}

	if err := h.manager.Set(c.Context(), key, req.Value, opts...); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update secret",
		})
	}

	secret, _ := h.manager.GetSecret(c.Context(), key)

	return c.JSON(secret.ToPublic())
}

// DeleteSecret deletes a secret.
func (h *SecretsHandler) DeleteSecret(c *fiber.Ctx) error {
	key := c.Params("key")

	if err := h.manager.Delete(c.Context(), key); err != nil {
		if err == secrets.ErrSecretNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Secret not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete secret",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Secret deleted",
	})
}
