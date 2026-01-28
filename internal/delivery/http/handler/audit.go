// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// AuditService provides audit log operations.
type AuditService interface {
	Query(ctx context.Context, filter entity.AuditFilter) ([]*entity.AuditEntry, error)
	Count(ctx context.Context, filter entity.AuditFilter) (int64, error)
	GetByID(ctx context.Context, id string) (*entity.AuditEntry, error)
}

// AuditHandler handles audit log endpoints.
type AuditHandler struct {
	service AuditService
}

// NewAuditHandler creates a new audit handler.
func NewAuditHandler(service AuditService) *AuditHandler {
	return &AuditHandler{service: service}
}

// GetAuditLogs handles GET /api/v1/audit
func (h *AuditHandler) GetAuditLogs(c *fiber.Ctx) error {
	filter := entity.AuditFilter{
		Limit:  100,
		Offset: 0,
	}

	// Parse query parameters
	if userID := c.Query("user_id"); userID != "" {
		filter.UserID = userID
	}
	if action := c.Query("action"); action != "" {
		filter.Action = entity.AuditAction(action)
	}
	if resource := c.Query("resource"); resource != "" {
		filter.Resource = resource
	}
	if resourceID := c.Query("resource_id"); resourceID != "" {
		filter.ResourceID = resourceID
	}
	if from := c.Query("from"); from != "" {
		if t, err := time.Parse(time.RFC3339, from); err == nil {
			filter.StartTime = &t
		}
	}
	if to := c.Query("to"); to != "" {
		if t, err := time.Parse(time.RFC3339, to); err == nil {
			filter.EndTime = &t
		}
	}
	if success := c.Query("success"); success != "" {
		b := success == "true"
		filter.Success = &b
	}
	if limit := c.Query("limit"); limit != "" {
		if l, err := strconv.Atoi(limit); err == nil && l > 0 && l <= 1000 {
			filter.Limit = l
		}
	}
	if offset := c.Query("offset"); offset != "" {
		if o, err := strconv.Atoi(offset); err == nil && o >= 0 {
			filter.Offset = o
		}
	}

	entries, err := h.service.Query(c.Context(), filter)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve audit logs",
		})
	}

	total, _ := h.service.Count(c.Context(), filter)

	return c.JSON(fiber.Map{
		"entries": entries,
		"total":   total,
		"limit":   filter.Limit,
		"offset":  filter.Offset,
	})
}

// GetAuditEntry handles GET /api/v1/audit/:id
func (h *AuditHandler) GetAuditEntry(c *fiber.Ctx) error {
	id := c.Params("id")
	entry, err := h.service.GetByID(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Audit entry not found",
		})
	}

	return c.JSON(entry)
}

// GetAuditActions handles GET /api/v1/audit/actions
func (h *AuditHandler) GetAuditActions(c *fiber.Ctx) error {
	actions := []string{
		string(entity.AuditActionLogin),
		string(entity.AuditActionLoginFailed),
		string(entity.AuditActionLogout),
		string(entity.AuditActionTokenRefresh),
		string(entity.AuditAction2FASetup),
		string(entity.AuditAction2FADisabled),
		string(entity.AuditActionTaskCreate),
		string(entity.AuditActionTaskStart),
		string(entity.AuditActionTaskComplete),
		string(entity.AuditActionTaskFail),
		string(entity.AuditActionTaskCancel),
		string(entity.AuditActionClientConnect),
		string(entity.AuditActionClientDisconnect),
		string(entity.AuditActionClientDelete),
		string(entity.AuditActionSessionCreate),
		string(entity.AuditActionSessionDelete),
		string(entity.AuditActionScheduleCreate),
		string(entity.AuditActionScheduleUpdate),
		string(entity.AuditActionScheduleDelete),
		string(entity.AuditActionWebhookCreate),
		string(entity.AuditActionWebhookUpdate),
		string(entity.AuditActionWebhookDelete),
	}

	return c.JSON(fiber.Map{"actions": actions})
}
