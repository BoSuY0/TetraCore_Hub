// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// TaskRepository defines the interface for task data access.
type TaskRepository interface {
	// Save stores a task.
	Save(ctx context.Context, task *entity.Task) error

	// Get retrieves a task by ID.
	Get(ctx context.Context, taskID string) (*entity.Task, error)

	// GetAll retrieves all tasks with optional pagination.
	GetAll(ctx context.Context, limit, offset int) ([]*entity.Task, error)

	// GetByStatus retrieves tasks by status.
	GetByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error)

	// GetByType retrieves tasks by type.
	GetByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error)

	// GetByClientID retrieves tasks for a specific client.
	GetByClientID(ctx context.Context, clientID string, limit int) ([]*entity.Task, error)

	// GetByWorkerID retrieves tasks assigned to a specific worker.
	GetByWorkerID(ctx context.Context, workerID string, limit int) ([]*entity.Task, error)

	// GetPending retrieves pending tasks ordered by priority.
	GetPending(ctx context.Context, limit int) ([]*entity.Task, error)

	// GetPendingByExecutorType retrieves pending tasks for a specific executor type.
	GetPendingByExecutorType(ctx context.Context, executorType entity.ExecutorType, limit int) ([]*entity.Task, error)

	// Update updates a task.
	Update(ctx context.Context, task *entity.Task) error

	// UpdateStatus updates the status of a task.
	UpdateStatus(ctx context.Context, taskID string, status entity.TaskStatus) error

	// AssignToWorker assigns a task to a worker.
	AssignToWorker(ctx context.Context, taskID, workerID string) error

	// Delete removes a task.
	Delete(ctx context.Context, taskID string) error

	// DeleteOlderThan deletes tasks older than the specified duration.
	DeleteOlderThan(ctx context.Context, hours int) (int64, error)

	// Count returns the total number of tasks.
	Count(ctx context.Context) (int64, error)

	// CountByStatus returns the count of tasks by status.
	CountByStatus(ctx context.Context, status entity.TaskStatus) (int64, error)

	// Exists checks if a task exists.
	Exists(ctx context.Context, taskID string) (bool, error)

	// GetByIdempotencyKey retrieves a task by idempotency key.
	GetByIdempotencyKey(ctx context.Context, key string) (*entity.Task, error)

	// GetExpired retrieves expired tasks.
	GetExpired(ctx context.Context, limit int) ([]*entity.Task, error)

	// GetStats retrieves task statistics.
	GetStats(ctx context.Context) (*TaskStats, error)
}

// TaskStats represents task statistics.
type TaskStats struct {
	TotalTasks          int64            `json:"total_tasks"`
	PendingTasks        int64            `json:"pending_tasks"`
	ProcessingTasks     int64            `json:"processing_tasks"`
	CompletedTasks      int64            `json:"completed_tasks"`
	FailedTasks         int64            `json:"failed_tasks"`
	TimeoutTasks        int64            `json:"timeout_tasks"`
	TasksByType         map[string]int64 `json:"tasks_by_type"`
	TasksByPriority     map[string]int64 `json:"tasks_by_priority"`
	AverageProcessingMs float64          `json:"average_processing_ms"`
	OldestPendingAge    float64          `json:"oldest_pending_age_seconds"`
}
