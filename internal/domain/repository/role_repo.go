// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// RoleRepository defines the interface for role data access.
type RoleRepository interface {
	// Create creates a new role.
	Create(ctx context.Context, role *entity.Role) error

	// GetByID retrieves a role by ID.
	GetByID(ctx context.Context, id entity.RoleID) (*entity.Role, error)

	// Update updates an existing role.
	Update(ctx context.Context, role *entity.Role) error

	// Delete deletes a role by ID.
	Delete(ctx context.Context, id entity.RoleID) error

	// List returns all roles.
	List(ctx context.Context) ([]*entity.Role, error)

	// Exists checks if a role with the given ID exists.
	Exists(ctx context.Context, id entity.RoleID) (bool, error)

	// InitDefaults initializes default system roles.
	InitDefaults(ctx context.Context) error
}
