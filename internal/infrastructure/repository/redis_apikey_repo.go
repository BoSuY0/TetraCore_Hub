// Package repository provides Redis-based repository implementations.
package repository

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	apiKeyKeyPrefix    = "apikeys:"
	apiKeyPrefixIndex  = "apikeys:index:prefix:"
	apiKeyUserIndex    = "apikeys:index:user:"
	apiKeyListKey      = "apikeys:list"
)

// RedisAPIKeyRepository implements APIKeyRepository using Redis.
type RedisAPIKeyRepository struct {
	client redis.UniversalClient
	log    logger.LogFields
}

// NewRedisAPIKeyRepository creates a new RedisAPIKeyRepository.
func NewRedisAPIKeyRepository(client redis.UniversalClient) *RedisAPIKeyRepository {
	return &RedisAPIKeyRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-apikey-repo"},
	}
}

// Create creates a new API key.
func (r *RedisAPIKeyRepository) Create(ctx context.Context, key *entity.APIKey) error {
	data, err := json.Marshal(key)
	if err != nil {
		return fmt.Errorf("failed to marshal api key: %w", err)
	}

	pipe := r.client.Pipeline()

	// Store key data
	pipe.Set(ctx, apiKeyKeyPrefix+key.ID, data, 0)

	// Create indexes
	pipe.Set(ctx, apiKeyPrefixIndex+key.Prefix, key.ID, 0)
	pipe.SAdd(ctx, apiKeyUserIndex+key.UserID, key.ID)
	pipe.SAdd(ctx, apiKeyListKey, key.ID)

	_, err = pipe.Exec(ctx)
	return err
}

// GetByID retrieves an API key by ID.
func (r *RedisAPIKeyRepository) GetByID(ctx context.Context, id string) (*entity.APIKey, error) {
	data, err := r.client.Get(ctx, apiKeyKeyPrefix+id).Bytes()
	if err == redis.Nil {
		return nil, entity.ErrAPIKeyNotFound
	}
	if err != nil {
		return nil, err
	}

	var key entity.APIKey
	if err := json.Unmarshal(data, &key); err != nil {
		return nil, fmt.Errorf("failed to unmarshal api key: %w", err)
	}
	return &key, nil
}

// GetByPrefix retrieves an API key by prefix.
func (r *RedisAPIKeyRepository) GetByPrefix(ctx context.Context, prefix string) (*entity.APIKey, error) {
	id, err := r.client.Get(ctx, apiKeyPrefixIndex+prefix).Result()
	if err == redis.Nil {
		return nil, entity.ErrAPIKeyNotFound
	}
	if err != nil {
		return nil, err
	}
	return r.GetByID(ctx, id)
}

// Update updates an existing API key.
func (r *RedisAPIKeyRepository) Update(ctx context.Context, key *entity.APIKey) error {
	// Check if key exists
	_, err := r.GetByID(ctx, key.ID)
	if err != nil {
		return err
	}

	data, err := json.Marshal(key)
	if err != nil {
		return fmt.Errorf("failed to marshal api key: %w", err)
	}

	return r.client.Set(ctx, apiKeyKeyPrefix+key.ID, data, 0).Err()
}

// Delete deletes an API key by ID.
func (r *RedisAPIKeyRepository) Delete(ctx context.Context, id string) error {
	key, err := r.GetByID(ctx, id)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()

	// Delete key data
	pipe.Del(ctx, apiKeyKeyPrefix+id)

	// Delete indexes
	pipe.Del(ctx, apiKeyPrefixIndex+key.Prefix)
	pipe.SRem(ctx, apiKeyUserIndex+key.UserID, id)
	pipe.SRem(ctx, apiKeyListKey, id)

	_, err = pipe.Exec(ctx)
	return err
}

// ListByUser returns all API keys for a user.
func (r *RedisAPIKeyRepository) ListByUser(ctx context.Context, userID string) ([]*entity.APIKey, error) {
	ids, err := r.client.SMembers(ctx, apiKeyUserIndex+userID).Result()
	if err != nil {
		return nil, err
	}

	keys := make([]*entity.APIKey, 0, len(ids))
	for _, id := range ids {
		key, err := r.GetByID(ctx, id)
		if err != nil {
			continue
		}
		keys = append(keys, key)
	}

	return keys, nil
}

// List returns all API keys with optional filtering.
func (r *RedisAPIKeyRepository) List(ctx context.Context, filter repository.APIKeyFilter) ([]*entity.APIKey, error) {
	var keyIDs []string

	if filter.UserID != "" {
		ids, err := r.client.SMembers(ctx, apiKeyUserIndex+filter.UserID).Result()
		if err != nil {
			return nil, err
		}
		keyIDs = ids
	} else {
		ids, err := r.client.SMembers(ctx, apiKeyListKey).Result()
		if err != nil {
			return nil, err
		}
		keyIDs = ids
	}

	keys := make([]*entity.APIKey, 0, len(keyIDs))
	for _, id := range keyIDs {
		key, err := r.GetByID(ctx, id)
		if err != nil {
			continue
		}

		// Apply active filter
		if filter.IsActive != nil && key.IsActive != *filter.IsActive {
			continue
		}

		keys = append(keys, key)
	}

	// Apply pagination
	start := filter.Offset
	if start > len(keys) {
		return []*entity.APIKey{}, nil
	}

	end := len(keys)
	if filter.Limit > 0 && start+filter.Limit < end {
		end = start + filter.Limit
	}

	return keys[start:end], nil
}

// Count returns the total number of API keys.
func (r *RedisAPIKeyRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, apiKeyListKey).Result()
}

// CountByUser returns the number of API keys for a user.
func (r *RedisAPIKeyRepository) CountByUser(ctx context.Context, userID string) (int64, error) {
	return r.client.SCard(ctx, apiKeyUserIndex+userID).Result()
}

// Ensure interface compliance
var _ repository.APIKeyRepository = (*RedisAPIKeyRepository)(nil)
