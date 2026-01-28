// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"net/url"
	"strings"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// WebhookService provides webhook management operations.
type WebhookService interface {
	Create(ctx context.Context, input CreateWebhookInput) (*entity.Webhook, error)
	GetByID(ctx context.Context, id string) (*entity.Webhook, error)
	GetAll(ctx context.Context) ([]*entity.Webhook, error)
	Update(ctx context.Context, id string, input UpdateWebhookInput) (*entity.Webhook, error)
	Delete(ctx context.Context, id string) error
	Enable(ctx context.Context, id string) error
	Disable(ctx context.Context, id string) error
	Test(ctx context.Context, id string) error
}

// CreateWebhookInput represents webhook creation input.
type CreateWebhookInput struct {
	Name   string                 `json:"name"`
	URL    string                 `json:"url"`
	Secret string                 `json:"secret"`
	Events []entity.WebhookEvent  `json:"events"`
}

// UpdateWebhookInput represents webhook update input.
type UpdateWebhookInput struct {
	Name   *string                 `json:"name,omitempty"`
	URL    *string                 `json:"url,omitempty"`
	Secret *string                 `json:"secret,omitempty"`
	Events *[]entity.WebhookEvent  `json:"events,omitempty"`
}

// WebhookHandler handles webhook management endpoints.
type WebhookHandler struct {
	service WebhookService
}

// NewWebhookHandler creates a new webhook handler.
func NewWebhookHandler(service WebhookService) *WebhookHandler {
	return &WebhookHandler{service: service}
}

// GetWebhooks handles GET /api/v1/webhooks
func (h *WebhookHandler) GetWebhooks(c *fiber.Ctx) error {
	webhooks, err := h.service.GetAll(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve webhooks",
		})
	}

	return c.JSON(fiber.Map{
		"webhooks": webhooks,
		"total":    len(webhooks),
	})
}

// CreateWebhook handles POST /api/v1/webhooks
func (h *WebhookHandler) CreateWebhook(c *fiber.Ctx) error {
	var req CreateWebhookInput
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	if req.Name == "" || req.URL == "" || len(req.Events) == 0 {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Name, URL, and at least one event are required",
		})
	}

	// Validate URL format
	if err := validateWebhookURL(req.URL); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": err.Error(),
		})
	}

	webhook, err := h.service.Create(c.Context(), req)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create webhook",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"message": "Webhook created",
		"webhook": webhook,
	})
}

// GetWebhook handles GET /api/v1/webhooks/:id
func (h *WebhookHandler) GetWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	webhook, err := h.service.GetByID(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Webhook not found",
		})
	}

	return c.JSON(webhook)
}

// UpdateWebhook handles PUT /api/v1/webhooks/:id
func (h *WebhookHandler) UpdateWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	var req UpdateWebhookInput
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	// Validate URL format if provided
	if req.URL != nil && *req.URL != "" {
		if err := validateWebhookURL(*req.URL); err != nil {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"error":   true,
				"message": err.Error(),
			})
		}
	}

	webhook, err := h.service.Update(c.Context(), id, req)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update webhook",
		})
	}

	return c.JSON(fiber.Map{
		"message": "Webhook updated",
		"webhook": webhook,
	})
}

// DeleteWebhook handles DELETE /api/v1/webhooks/:id
func (h *WebhookHandler) DeleteWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	if err := h.service.Delete(c.Context(), id); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Webhook not found",
		})
	}

	return c.JSON(fiber.Map{"message": "Webhook deleted"})
}

// EnableWebhook handles POST /api/v1/webhooks/:id/enable
func (h *WebhookHandler) EnableWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	if err := h.service.Enable(c.Context(), id); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Webhook not found",
		})
	}

	return c.JSON(fiber.Map{"message": "Webhook enabled"})
}

// DisableWebhook handles POST /api/v1/webhooks/:id/disable
func (h *WebhookHandler) DisableWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	if err := h.service.Disable(c.Context(), id); err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Webhook not found",
		})
	}

	return c.JSON(fiber.Map{"message": "Webhook disabled"})
}

// TestWebhook handles POST /api/v1/webhooks/:id/test
func (h *WebhookHandler) TestWebhook(c *fiber.Ctx) error {
	id := c.Params("id")
	if err := h.service.Test(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Webhook test failed",
		})
	}

	return c.JSON(fiber.Map{"message": "Webhook test sent successfully"})
}

// GetWebhookEvents handles GET /api/v1/webhooks/events
func (h *WebhookHandler) GetWebhookEvents(c *fiber.Ctx) error {
	events := []string{
		string(entity.WebhookEventTaskCreated),
		string(entity.WebhookEventTaskStarted),
		string(entity.WebhookEventTaskCompleted),
		string(entity.WebhookEventTaskFailed),
		string(entity.WebhookEventTaskCancelled),
		string(entity.WebhookEventClientConnected),
		string(entity.WebhookEventClientDisconnected),
		string(entity.WebhookEventWorkerIdle),
		string(entity.WebhookEventWorkerBusy),
	}

	return c.JSON(fiber.Map{"events": events})
}

// validateWebhookURL validates that the URL is a valid HTTP/HTTPS URL.
func validateWebhookURL(rawURL string) error {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return fiber.NewError(fiber.StatusBadRequest, "Invalid URL format")
	}

	// Must have http or https scheme
	scheme := strings.ToLower(parsed.Scheme)
	if scheme != "http" && scheme != "https" {
		return fiber.NewError(fiber.StatusBadRequest, "URL must use http or https scheme")
	}

	// Must have a host
	if parsed.Host == "" {
		return fiber.NewError(fiber.StatusBadRequest, "URL must have a valid host")
	}

	return nil
}
