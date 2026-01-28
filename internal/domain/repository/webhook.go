// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// ErrWebhookNotFound is returned when a webhook is not found.
var ErrWebhookNotFound = errors.New("webhook not found")

// WebhookRepository defines operations for webhook persistence.
type WebhookRepository interface {
	// Save saves a webhook (create or update).
	Save(ctx context.Context, webhook *entity.Webhook) error

	// GetByID retrieves a webhook by ID.
	GetByID(ctx context.Context, id string) (*entity.Webhook, error)

	// GetAll retrieves all webhooks.
	GetAll(ctx context.Context) ([]*entity.Webhook, error)

	// GetEnabled retrieves all enabled webhooks.
	GetEnabled(ctx context.Context) ([]*entity.Webhook, error)

	// GetByEvent retrieves webhooks subscribed to an event.
	GetByEvent(ctx context.Context, event entity.WebhookEvent) ([]*entity.Webhook, error)

	// Delete deletes a webhook.
	Delete(ctx context.Context, id string) error

	// Count returns the total number of webhooks.
	Count(ctx context.Context) (int64, error)
}
