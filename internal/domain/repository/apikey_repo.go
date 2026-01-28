// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// APIKeyRepository defines the interface for API key data access.
type APIKeyRepository interface {
	// Create creates a new API key.
	Create(ctx context.Context, key *entity.APIKey) error

	// GetByID retrieves an API key by ID.
	GetByID(ctx context.Context, id string) (*entity.APIKey, error)

	// GetByPrefix retrieves an API key by prefix.
	GetByPrefix(ctx context.Context, prefix string) (*entity.APIKey, error)

	// Update updates an existing API key.
	Update(ctx context.Context, key *entity.APIKey) error

	// Delete deletes an API key by ID.
	Delete(ctx context.Context, id string) error

	// ListByUser returns all API keys for a user.
	ListByUser(ctx context.Context, userID string) ([]*entity.APIKey, error)

	// List returns all API keys with optional filtering.
	List(ctx context.Context, filter APIKeyFilter) ([]*entity.APIKey, error)

	// Count returns the total number of API keys.
	Count(ctx context.Context) (int64, error)

	// CountByUser returns the number of API keys for a user.
	CountByUser(ctx context.Context, userID string) (int64, error)
}

// APIKeyFilter defines filtering options for API key queries.
type APIKeyFilter struct {
	UserID   string `json:"user_id,omitempty"`
	IsActive *bool  `json:"is_active,omitempty"`
	Limit    int    `json:"limit,omitempty"`
	Offset   int    `json:"offset,omitempty"`
}
