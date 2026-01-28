// Package repository provides Redis-based repository implementations.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	userKeyPrefix      = "users:"
	userUsernameIndex  = "users:index:username:"
	userEmailIndex     = "users:index:email:"
	userRoleIndex      = "users:index:role:"
	userListKey        = "users:list"
)

// RedisUserRepository implements UserRepository using Redis.
type RedisUserRepository struct {
	client redis.UniversalClient
	log    logger.LogFields
}

// NewRedisUserRepository creates a new RedisUserRepository.
func NewRedisUserRepository(client redis.UniversalClient) *RedisUserRepository {
	return &RedisUserRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-user-repo"},
	}
}

// Create creates a new user.
func (r *RedisUserRepository) Create(ctx context.Context, user *entity.User) error {
	// Check if username already exists
	exists, err := r.ExistsByUsername(ctx, user.Username)
	if err != nil {
		return err
	}
	if exists {
		return entity.ErrUserAlreadyExists
	}

	// Check if email already exists (if provided)
	if user.Email != "" {
		exists, err = r.ExistsByEmail(ctx, user.Email)
		if err != nil {
			return err
		}
		if exists {
			return entity.ErrUserAlreadyExists
		}
	}

	data, err := json.Marshal(user)
	if err != nil {
		return fmt.Errorf("failed to marshal user: %w", err)
	}

	pipe := r.client.Pipeline()

	// Store user data
	pipe.Set(ctx, userKeyPrefix+user.ID, data, 0)

	// Create indexes
	pipe.Set(ctx, userUsernameIndex+strings.ToLower(user.Username), user.ID, 0)
	if user.Email != "" {
		pipe.Set(ctx, userEmailIndex+strings.ToLower(user.Email), user.ID, 0)
	}
	pipe.SAdd(ctx, userRoleIndex+string(user.RoleID), user.ID)
	pipe.SAdd(ctx, userListKey, user.ID)

	_, err = pipe.Exec(ctx)
	return err
}

// GetByID retrieves a user by ID.
func (r *RedisUserRepository) GetByID(ctx context.Context, id string) (*entity.User, error) {
	data, err := r.client.Get(ctx, userKeyPrefix+id).Bytes()
	if err == redis.Nil {
		return nil, entity.ErrUserNotFound
	}
	if err != nil {
		return nil, err
	}

	var user entity.User
	if err := json.Unmarshal(data, &user); err != nil {
		return nil, fmt.Errorf("failed to unmarshal user: %w", err)
	}
	return &user, nil
}

// GetByUsername retrieves a user by username.
func (r *RedisUserRepository) GetByUsername(ctx context.Context, username string) (*entity.User, error) {
	id, err := r.client.Get(ctx, userUsernameIndex+strings.ToLower(username)).Result()
	if err == redis.Nil {
		return nil, entity.ErrUserNotFound
	}
	if err != nil {
		return nil, err
	}
	return r.GetByID(ctx, id)
}

// GetByEmail retrieves a user by email.
func (r *RedisUserRepository) GetByEmail(ctx context.Context, email string) (*entity.User, error) {
	id, err := r.client.Get(ctx, userEmailIndex+strings.ToLower(email)).Result()
	if err == redis.Nil {
		return nil, entity.ErrUserNotFound
	}
	if err != nil {
		return nil, err
	}
	return r.GetByID(ctx, id)
}

// Update updates an existing user.
func (r *RedisUserRepository) Update(ctx context.Context, user *entity.User) error {
	// Get existing user to check for index changes
	existing, err := r.GetByID(ctx, user.ID)
	if err != nil {
		return err
	}

	data, err := json.Marshal(user)
	if err != nil {
		return fmt.Errorf("failed to marshal user: %w", err)
	}

	pipe := r.client.Pipeline()

	// Update user data
	pipe.Set(ctx, userKeyPrefix+user.ID, data, 0)

	// Update username index if changed
	if existing.Username != user.Username {
		pipe.Del(ctx, userUsernameIndex+strings.ToLower(existing.Username))
		pipe.Set(ctx, userUsernameIndex+strings.ToLower(user.Username), user.ID, 0)
	}

	// Update email index if changed
	if existing.Email != user.Email {
		if existing.Email != "" {
			pipe.Del(ctx, userEmailIndex+strings.ToLower(existing.Email))
		}
		if user.Email != "" {
			pipe.Set(ctx, userEmailIndex+strings.ToLower(user.Email), user.ID, 0)
		}
	}

	// Update role index if changed
	if existing.RoleID != user.RoleID {
		pipe.SRem(ctx, userRoleIndex+string(existing.RoleID), user.ID)
		pipe.SAdd(ctx, userRoleIndex+string(user.RoleID), user.ID)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Delete deletes a user by ID.
func (r *RedisUserRepository) Delete(ctx context.Context, id string) error {
	user, err := r.GetByID(ctx, id)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()

	// Delete user data
	pipe.Del(ctx, userKeyPrefix+id)

	// Delete indexes
	pipe.Del(ctx, userUsernameIndex+strings.ToLower(user.Username))
	if user.Email != "" {
		pipe.Del(ctx, userEmailIndex+strings.ToLower(user.Email))
	}
	pipe.SRem(ctx, userRoleIndex+string(user.RoleID), id)
	pipe.SRem(ctx, userListKey, id)

	_, err = pipe.Exec(ctx)
	return err
}

// List returns all users with optional filtering.
func (r *RedisUserRepository) List(ctx context.Context, filter repository.UserFilter) ([]*entity.User, error) {
	var userIDs []string

	if filter.RoleID != "" {
		// Filter by role
		ids, err := r.client.SMembers(ctx, userRoleIndex+string(filter.RoleID)).Result()
		if err != nil {
			return nil, err
		}
		userIDs = ids
	} else {
		// Get all users
		ids, err := r.client.SMembers(ctx, userListKey).Result()
		if err != nil {
			return nil, err
		}
		userIDs = ids
	}

	users := make([]*entity.User, 0, len(userIDs))
	for _, id := range userIDs {
		user, err := r.GetByID(ctx, id)
		if err != nil {
			continue // Skip missing users
		}

		// Apply status filter
		if filter.Status != "" && user.Status != filter.Status {
			continue
		}

		// Apply search filter
		if filter.Search != "" {
			searchLower := strings.ToLower(filter.Search)
			if !strings.Contains(strings.ToLower(user.Username), searchLower) &&
				!strings.Contains(strings.ToLower(user.Email), searchLower) {
				continue
			}
		}

		users = append(users, user)
	}

	// Apply pagination
	start := filter.Offset
	if start > len(users) {
		return []*entity.User{}, nil
	}

	end := len(users)
	if filter.Limit > 0 && start+filter.Limit < end {
		end = start + filter.Limit
	}

	return users[start:end], nil
}

// Count returns the total number of users.
func (r *RedisUserRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, userListKey).Result()
}

// ExistsByUsername checks if a user with the given username exists.
func (r *RedisUserRepository) ExistsByUsername(ctx context.Context, username string) (bool, error) {
	exists, err := r.client.Exists(ctx, userUsernameIndex+strings.ToLower(username)).Result()
	return exists > 0, err
}

// ExistsByEmail checks if a user with the given email exists.
func (r *RedisUserRepository) ExistsByEmail(ctx context.Context, email string) (bool, error) {
	if email == "" {
		return false, nil
	}
	exists, err := r.client.Exists(ctx, userEmailIndex+strings.ToLower(email)).Result()
	return exists > 0, err
}

// Ensure interface compliance
var _ repository.UserRepository = (*RedisUserRepository)(nil)
