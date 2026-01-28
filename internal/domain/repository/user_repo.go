// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// UserRepository defines the interface for user data access.
type UserRepository interface {
	// Create creates a new user.
	Create(ctx context.Context, user *entity.User) error

	// GetByID retrieves a user by ID.
	GetByID(ctx context.Context, id string) (*entity.User, error)

	// GetByUsername retrieves a user by username.
	GetByUsername(ctx context.Context, username string) (*entity.User, error)

	// GetByEmail retrieves a user by email.
	GetByEmail(ctx context.Context, email string) (*entity.User, error)

	// Update updates an existing user.
	Update(ctx context.Context, user *entity.User) error

	// Delete deletes a user by ID.
	Delete(ctx context.Context, id string) error

	// List returns all users with optional filtering.
	List(ctx context.Context, filter UserFilter) ([]*entity.User, error)

	// Count returns the total number of users.
	Count(ctx context.Context) (int64, error)

	// ExistsByUsername checks if a user with the given username exists.
	ExistsByUsername(ctx context.Context, username string) (bool, error)

	// ExistsByEmail checks if a user with the given email exists.
	ExistsByEmail(ctx context.Context, email string) (bool, error)
}

// UserFilter defines filtering options for user queries.
type UserFilter struct {
	RoleID   entity.RoleID    `json:"role_id,omitempty"`
	Status   entity.UserStatus `json:"status,omitempty"`
	Search   string           `json:"search,omitempty"` // Search in username/email
	Limit    int              `json:"limit,omitempty"`
	Offset   int              `json:"offset,omitempty"`
}
