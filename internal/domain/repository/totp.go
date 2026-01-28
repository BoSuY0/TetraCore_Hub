// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// ErrTOTPNotFound is returned when a TOTP configuration is not found.
var ErrTOTPNotFound = errors.New("TOTP configuration not found")

// TOTPRepository defines operations for TOTP persistence.
type TOTPRepository interface {
	// Save saves a TOTP configuration (create or update).
	Save(ctx context.Context, config *entity.TOTPConfig) error

	// GetByUserID retrieves TOTP config by user ID.
	GetByUserID(ctx context.Context, userID string) (*entity.TOTPConfig, error)

	// Delete deletes a TOTP configuration.
	Delete(ctx context.Context, userID string) error

	// Exists checks if TOTP is configured for a user.
	Exists(ctx context.Context, userID string) (bool, error)
}
