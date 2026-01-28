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
	totpKeyPrefix = "totp:"
)

// RedisTOTPRepository implements TOTPRepository using Redis.
type RedisTOTPRepository struct {
	client *redis.Client
	log    logger.LogFields
}

// NewRedisTOTPRepository creates a new Redis TOTP repository.
func NewRedisTOTPRepository(client *redis.Client) *RedisTOTPRepository {
	return &RedisTOTPRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-totp-repo"},
	}
}

// Save stores a TOTP configuration.
func (r *RedisTOTPRepository) Save(ctx context.Context, config *entity.TOTPConfig) error {
	data, err := json.Marshal(config)
	if err != nil {
		return fmt.Errorf("failed to marshal TOTP config: %w", err)
	}

	key := totpKeyPrefix + config.UserID
	return r.client.Set(ctx, key, data, 0)
}

// GetByUserID retrieves a TOTP configuration by user ID.
func (r *RedisTOTPRepository) GetByUserID(ctx context.Context, userID string) (*entity.TOTPConfig, error) {
	key := totpKeyPrefix + userID
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrTOTPNotFound
	}

	var config entity.TOTPConfig
	if err := json.Unmarshal([]byte(data), &config); err != nil {
		return nil, fmt.Errorf("failed to unmarshal TOTP config: %w", err)
	}

	return &config, nil
}

// Delete removes a TOTP configuration.
func (r *RedisTOTPRepository) Delete(ctx context.Context, userID string) error {
	key := totpKeyPrefix + userID
	return r.client.Del(ctx, key)
}

// Exists checks if a TOTP configuration exists for a user.
func (r *RedisTOTPRepository) Exists(ctx context.Context, userID string) (bool, error) {
	key := totpKeyPrefix + userID
	exists, err := r.client.Exists(ctx, key)
	return exists > 0, err
}

// Ensure interface compliance
var _ repository.TOTPRepository = (*RedisTOTPRepository)(nil)
