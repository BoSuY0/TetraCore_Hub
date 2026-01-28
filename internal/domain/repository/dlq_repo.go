// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// DLQ repository errors.
var (
	ErrDLQEntryNotFound = errors.New("DLQ entry not found")
	ErrDLQEmpty         = errors.New("DLQ is empty")
)

// DLQRepository defines the interface for dead letter queue data access.
type DLQRepository interface {
	// Save stores a DLQ entry.
	Save(ctx context.Context, entry *entity.DLQEntry) error

	// Get retrieves a DLQ entry by ID.
	Get(ctx context.Context, id string) (*entity.DLQEntry, error)

	// GetByTaskID retrieves a DLQ entry by original task ID.
	GetByTaskID(ctx context.Context, taskID string) (*entity.DLQEntry, error)

	// GetAll retrieves all DLQ entries with optional pagination.
	GetAll(ctx context.Context, limit, offset int) ([]*entity.DLQEntry, error)

	// GetByReason retrieves DLQ entries by reason.
	GetByReason(ctx context.Context, reason entity.DLQReason, limit int) ([]*entity.DLQEntry, error)

	// GetByTaskType retrieves DLQ entries by task type.
	GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.DLQEntry, error)

	// GetExpired retrieves expired DLQ entries.
	GetExpired(ctx context.Context, limit int) ([]*entity.DLQEntry, error)

	// Delete removes a DLQ entry.
	Delete(ctx context.Context, id string) error

	// DeleteByTaskID removes a DLQ entry by task ID.
	DeleteByTaskID(ctx context.Context, taskID string) error

	// DeleteOlderThan deletes entries older than the specified hours.
	DeleteOlderThan(ctx context.Context, hours int) (int64, error)

	// Purge removes all DLQ entries.
	Purge(ctx context.Context) (int64, error)

	// Count returns the total number of DLQ entries.
	Count(ctx context.Context) (int64, error)

	// CountByReason returns the count of DLQ entries by reason.
	CountByReason(ctx context.Context, reason entity.DLQReason) (int64, error)

	// GetStats retrieves DLQ statistics.
	GetStats(ctx context.Context) (*entity.DLQStats, error)

	// Exists checks if a DLQ entry exists.
	Exists(ctx context.Context, id string) (bool, error)

	// ExistsByTaskID checks if a DLQ entry exists for a task.
	ExistsByTaskID(ctx context.Context, taskID string) (bool, error)
}
