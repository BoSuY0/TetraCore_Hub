// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// Schedule repository errors.
var (
	ErrScheduleNotFound      = errors.New("schedule not found")
	ErrScheduleAlreadyExists = errors.New("schedule already exists")
)

// ScheduleRepository defines the interface for schedule data access.
type ScheduleRepository interface {
	// Save stores a schedule.
	Save(ctx context.Context, schedule *entity.Schedule) error

	// Get retrieves a schedule by ID.
	Get(ctx context.Context, id string) (*entity.Schedule, error)

	// GetByName retrieves a schedule by name.
	GetByName(ctx context.Context, name string) (*entity.Schedule, error)

	// GetAll retrieves all schedules with optional pagination.
	GetAll(ctx context.Context, limit, offset int) ([]*entity.Schedule, error)

	// GetByStatus retrieves schedules by status.
	GetByStatus(ctx context.Context, status entity.ScheduleStatus, limit int) ([]*entity.Schedule, error)

	// GetActive retrieves all active schedules.
	GetActive(ctx context.Context) ([]*entity.Schedule, error)

	// GetByCreator retrieves schedules created by a specific user.
	GetByCreator(ctx context.Context, createdBy string, limit int) ([]*entity.Schedule, error)

	// GetDue retrieves schedules that are due to run.
	GetDue(ctx context.Context) ([]*entity.Schedule, error)

	// GetByTaskType retrieves schedules by task type.
	GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Schedule, error)

	// GetByTag retrieves schedules by tag.
	GetByTag(ctx context.Context, tag string, limit int) ([]*entity.Schedule, error)

	// Update updates a schedule.
	Update(ctx context.Context, schedule *entity.Schedule) error

	// UpdateStatus updates the status of a schedule.
	UpdateStatus(ctx context.Context, id string, status entity.ScheduleStatus) error

	// UpdateNextRun updates the next run time of a schedule.
	UpdateNextRun(ctx context.Context, id string, schedule *entity.Schedule) error

	// RecordRun records a schedule run.
	RecordRun(ctx context.Context, id, taskID string, status entity.TaskStatus) error

	// Delete removes a schedule.
	Delete(ctx context.Context, id string) error

	// Count returns the total number of schedules.
	Count(ctx context.Context) (int64, error)

	// CountByStatus returns the count of schedules by status.
	CountByStatus(ctx context.Context, status entity.ScheduleStatus) (int64, error)

	// Exists checks if a schedule exists.
	Exists(ctx context.Context, id string) (bool, error)

	// ExistsByName checks if a schedule with the given name exists.
	ExistsByName(ctx context.Context, name string) (bool, error)
}
