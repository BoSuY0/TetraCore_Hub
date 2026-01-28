// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// ErrAuditEntryNotFound is returned when an audit entry is not found.
var ErrAuditEntryNotFound = errors.New("audit entry not found")

// AuditRepository defines operations for audit log persistence.
type AuditRepository interface {
	// Save saves an audit entry.
	Save(ctx context.Context, entry *entity.AuditEntry) error

	// GetByID retrieves an audit entry by ID.
	GetByID(ctx context.Context, id string) (*entity.AuditEntry, error)

	// Query retrieves audit entries matching the filter.
	Query(ctx context.Context, filter entity.AuditFilter) ([]*entity.AuditEntry, error)

	// Count returns the count of entries matching the filter.
	Count(ctx context.Context, filter entity.AuditFilter) (int64, error)

	// DeleteBefore deletes entries before the given time.
	DeleteBefore(ctx context.Context, before time.Time) (int64, error)
}
