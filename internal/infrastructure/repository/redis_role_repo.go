// Package repository provides Redis-based repository implementations.
package repository

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	roleKeyPrefix = "roles:"
	roleListKey   = "roles:list"
)

// ErrRoleNotFound is returned when a role is not found.
var ErrRoleNotFound = errors.New("role not found")

// ErrRoleIsSystem is returned when trying to delete a system role.
var ErrRoleIsSystem = errors.New("cannot delete system role")

// RedisRoleRepository implements RoleRepository using Redis.
type RedisRoleRepository struct {
	client redis.UniversalClient
	log    logger.LogFields
}

// NewRedisRoleRepository creates a new RedisRoleRepository.
func NewRedisRoleRepository(client redis.UniversalClient) *RedisRoleRepository {
	return &RedisRoleRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-role-repo"},
	}
}

// Create creates a new role.
func (r *RedisRoleRepository) Create(ctx context.Context, role *entity.Role) error {
	data, err := json.Marshal(role)
	if err != nil {
		return fmt.Errorf("failed to marshal role: %w", err)
	}

	pipe := r.client.Pipeline()
	pipe.Set(ctx, roleKeyPrefix+string(role.ID), data, 0)
	pipe.SAdd(ctx, roleListKey, string(role.ID))
	_, err = pipe.Exec(ctx)
	return err
}

// GetByID retrieves a role by ID.
func (r *RedisRoleRepository) GetByID(ctx context.Context, id entity.RoleID) (*entity.Role, error) {
	data, err := r.client.Get(ctx, roleKeyPrefix+string(id)).Bytes()
	if err == redis.Nil {
		// Check default roles
		if role := entity.GetDefaultRole(id); role != nil {
			return role, nil
		}
		return nil, ErrRoleNotFound
	}
	if err != nil {
		return nil, err
	}

	var role entity.Role
	if err := json.Unmarshal(data, &role); err != nil {
		return nil, fmt.Errorf("failed to unmarshal role: %w", err)
	}
	return &role, nil
}

// Update updates an existing role.
func (r *RedisRoleRepository) Update(ctx context.Context, role *entity.Role) error {
	// Check if role exists
	existing, err := r.GetByID(ctx, role.ID)
	if err != nil {
		return err
	}

	// Don't allow modifying system roles
	if existing.IsSystem {
		return ErrRoleIsSystem
	}

	data, err := json.Marshal(role)
	if err != nil {
		return fmt.Errorf("failed to marshal role: %w", err)
	}

	return r.client.Set(ctx, roleKeyPrefix+string(role.ID), data, 0).Err()
}

// Delete deletes a role by ID.
func (r *RedisRoleRepository) Delete(ctx context.Context, id entity.RoleID) error {
	// Check if role exists and is not a system role
	existing, err := r.GetByID(ctx, id)
	if err != nil {
		return err
	}

	if existing.IsSystem {
		return ErrRoleIsSystem
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, roleKeyPrefix+string(id))
	pipe.SRem(ctx, roleListKey, string(id))
	_, err = pipe.Exec(ctx)
	return err
}

// List returns all roles.
func (r *RedisRoleRepository) List(ctx context.Context) ([]*entity.Role, error) {
	// Start with default roles
	roles := entity.DefaultRoles()
	roleMap := make(map[entity.RoleID]bool)
	for _, role := range roles {
		roleMap[role.ID] = true
	}

	// Get custom roles from Redis
	ids, err := r.client.SMembers(ctx, roleListKey).Result()
	if err != nil && err != redis.Nil {
		return nil, err
	}

	for _, id := range ids {
		if roleMap[entity.RoleID(id)] {
			continue // Skip default roles
		}

		role, err := r.GetByID(ctx, entity.RoleID(id))
		if err != nil {
			continue
		}
		roles = append(roles, role)
	}

	return roles, nil
}

// Exists checks if a role with the given ID exists.
func (r *RedisRoleRepository) Exists(ctx context.Context, id entity.RoleID) (bool, error) {
	// Check default roles first
	if entity.GetDefaultRole(id) != nil {
		return true, nil
	}

	exists, err := r.client.Exists(ctx, roleKeyPrefix+string(id)).Result()
	return exists > 0, err
}

// InitDefaults initializes default system roles.
func (r *RedisRoleRepository) InitDefaults(ctx context.Context) error {
	log := logger.WithFields(r.log)

	for _, role := range entity.DefaultRoles() {
		// Check if already exists
		_, err := r.client.Get(ctx, roleKeyPrefix+string(role.ID)).Result()
		if err == nil {
			continue // Already exists
		}
		if err != redis.Nil {
			return err
		}

		// Create default role
		if err := r.Create(ctx, role); err != nil {
			return err
		}
		log.Info().Str("role_id", string(role.ID)).Msg("Created default role")
	}

	return nil
}

// Ensure interface compliance
var _ repository.RoleRepository = (*RedisRoleRepository)(nil)
