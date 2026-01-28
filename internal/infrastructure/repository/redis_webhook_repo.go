// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	webhookKeyPrefix     = "webhook:"
	webhookSetKey        = "webhooks"
	webhookEventSetKey   = "webhooks:event:"
)

// RedisWebhookRepository implements WebhookRepository using Redis.
type RedisWebhookRepository struct {
	client *redis.Client
	log    logger.LogFields
}

// NewRedisWebhookRepository creates a new Redis webhook repository.
func NewRedisWebhookRepository(client *redis.Client) *RedisWebhookRepository {
	return &RedisWebhookRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-webhook-repo"},
	}
}

// Save stores a webhook.
func (r *RedisWebhookRepository) Save(ctx context.Context, webhook *entity.Webhook) error {
	data, err := json.Marshal(webhook)
	if err != nil {
		return fmt.Errorf("failed to marshal webhook: %w", err)
	}

	key := webhookKeyPrefix + webhook.ID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, 0)
	pipe.SAdd(ctx, webhookSetKey, webhook.ID)

	// Index by events
	for _, event := range webhook.Events {
		pipe.SAdd(ctx, webhookEventSetKey+string(event), webhook.ID)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// GetByID retrieves a webhook by ID.
func (r *RedisWebhookRepository) GetByID(ctx context.Context, id string) (*entity.Webhook, error) {
	key := webhookKeyPrefix + id
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrWebhookNotFound
	}

	var webhook entity.Webhook
	if err := json.Unmarshal([]byte(data), &webhook); err != nil {
		return nil, fmt.Errorf("failed to unmarshal webhook: %w", err)
	}

	return &webhook, nil
}

// GetAll retrieves all webhooks.
func (r *RedisWebhookRepository) GetAll(ctx context.Context) ([]*entity.Webhook, error) {
	webhookIDs, err := r.client.SMembers(ctx, webhookSetKey)
	if err != nil {
		return nil, err
	}

	webhooks := make([]*entity.Webhook, 0, len(webhookIDs))
	for _, id := range webhookIDs {
		webhook, err := r.GetByID(ctx, id)
		if err != nil {
			continue
		}
		webhooks = append(webhooks, webhook)
	}

	return webhooks, nil
}

// GetByEvent retrieves webhooks subscribed to an event.
func (r *RedisWebhookRepository) GetByEvent(ctx context.Context, event entity.WebhookEvent) ([]*entity.Webhook, error) {
	webhookIDs, err := r.client.SMembers(ctx, webhookEventSetKey+string(event))
	if err != nil {
		return nil, err
	}

	webhooks := make([]*entity.Webhook, 0, len(webhookIDs))
	for _, id := range webhookIDs {
		webhook, err := r.GetByID(ctx, id)
		if err != nil {
			continue
		}
		webhooks = append(webhooks, webhook)
	}

	return webhooks, nil
}

// GetEnabled retrieves all enabled webhooks.
func (r *RedisWebhookRepository) GetEnabled(ctx context.Context) ([]*entity.Webhook, error) {
	all, err := r.GetAll(ctx)
	if err != nil {
		return nil, err
	}

	enabled := make([]*entity.Webhook, 0)
	for _, webhook := range all {
		if webhook.Enabled {
			enabled = append(enabled, webhook)
		}
	}

	return enabled, nil
}

// Delete removes a webhook.
func (r *RedisWebhookRepository) Delete(ctx context.Context, id string) error {
	// Get webhook to remove event indexes
	webhook, err := r.GetByID(ctx, id)
	if err != nil {
		return err
	}

	key := webhookKeyPrefix + id

	pipe := r.client.Pipeline()
	pipe.Del(ctx, key)
	pipe.SRem(ctx, webhookSetKey, id)

	// Remove from event indexes
	for _, event := range webhook.Events {
		pipe.SRem(ctx, webhookEventSetKey+string(event), id)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Count returns the total number of webhooks.
func (r *RedisWebhookRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, webhookSetKey)
}

// Ensure interface compliance
var _ repository.WebhookRepository = (*RedisWebhookRepository)(nil)
