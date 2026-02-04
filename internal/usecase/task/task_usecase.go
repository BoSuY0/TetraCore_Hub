// Package task provides the task management use case for TetraCore Hub.
package task

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds task use case configuration.
type Config struct {
	DefaultTimeout    time.Duration
	MaxRetries        int
	RetryDelay        time.Duration
	CleanupAge        time.Duration
	EnableIdempotency bool
	BatchSize         int
}

// DefaultConfig returns the default configuration.
func DefaultConfig() Config {
	return Config{
		DefaultTimeout:    5 * time.Minute,
		MaxRetries:        3,
		RetryDelay:        5 * time.Second,
		CleanupAge:        24 * time.Hour,
		EnableIdempotency: true,
		BatchSize:         100,
	}
}

// WorkerSelector provides worker selection for task assignment.
type WorkerSelector interface {
	GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error)
}

// SubmitInput contains the input for submitting a task.
type SubmitInput struct {
	TaskID         string
	TaskType       entity.TaskType
	ExecutorType   entity.ExecutorType
	Priority       entity.TaskPriority
	Payload        map[string]any
	ClientID       string
	Timeout        time.Duration
	IdempotencyKey string
}

// TaskSender is an interface for sending tasks to workers.
type TaskSender interface {
	SendToClient(clientID string, message any) error
	GetAvailableExecutors(ctx context.Context, executorType entity.ExecutorType, taskType string) ([]*entity.Client, error)
	SetActiveTask(ctx context.Context, clientID, taskID string) error
	RemoveActiveTask(ctx context.Context, clientID, taskID string) error
}

// ProducerAuth handles producer authentication.
type ProducerAuth interface {
	Verify(ctx context.Context, signature, body string) (verified bool, producerID, algorithm string, err error)
}

// Stats represents task statistics.
type Stats struct {
	TotalTasks        int64            `json:"total_tasks"`
	PendingTasks      int64            `json:"pending_tasks"`
	ProcessingTasks   int64            `json:"processing_tasks"`
	CompletedTasks    int64            `json:"completed_tasks"`
	FailedTasks       int64            `json:"failed_tasks"`
	TasksByType       map[string]int64 `json:"tasks_by_type"`
	AvgProcessingTime float64          `json:"avg_processing_time_ms"`
}

// UseCase manages tasks.
type UseCase struct {
	taskRepo       repository.TaskRepository
	workerSelector WorkerSelector
	config         Config
	redisClient    *redis.Client
	sender         TaskSender
	auth           ProducerAuth
	log            logger.LogFields
	mu             sync.RWMutex
	processMu      sync.Mutex
}

// NewUseCase creates a new task use case.
func NewUseCase(
	taskRepo repository.TaskRepository,
	workerSelector WorkerSelector,
	config Config,
	redisClient *redis.Client,
) *UseCase {
	return &UseCase{
		taskRepo:       taskRepo,
		workerSelector: workerSelector,
		config:         config,
		redisClient:    redisClient,
		log:            logger.LogFields{"component": "task-usecase"},
	}
}

// SetSender sets the task sender.
func (uc *UseCase) SetSender(sender TaskSender) {
	uc.mu.Lock()
	defer uc.mu.Unlock()
	uc.sender = sender
}

// SetProducerAuth sets the producer authentication handler.
func (uc *UseCase) SetProducerAuth(auth ProducerAuth) {
	uc.mu.Lock()
	defer uc.mu.Unlock()
	uc.auth = auth
}

// GetProducerAuth returns the producer authentication handler.
func (uc *UseCase) GetProducerAuth() ProducerAuth {
	uc.mu.RLock()
	defer uc.mu.RUnlock()
	return uc.auth
}

// SubmitTask submits a new task.
func (uc *UseCase) SubmitTask(ctx context.Context, input SubmitInput) (*entity.Task, error) {
	log := logger.WithFields(uc.log)

	// Check idempotency
	if input.IdempotencyKey != "" {
		existing, err := uc.taskRepo.GetByIdempotencyKey(ctx, input.IdempotencyKey)
		if err == nil && existing != nil {
			log.Debug().
				Str("task_id", existing.TaskID).
				Str("idempotency_key", input.IdempotencyKey).
				Msg("Returning existing task for idempotency key")
			return existing, nil
		}
	}

	// Create task options
	opts := []entity.TaskOption{}

	if input.TaskID != "" {
		opts = append(opts, entity.WithTaskID(input.TaskID))
	}

	if input.Priority != "" {
		opts = append(opts, entity.WithPriority(input.Priority))
	}

	if input.ExecutorType != "" {
		opts = append(opts, entity.WithExecutorType(input.ExecutorType))
	}

	if input.Timeout > 0 {
		opts = append(opts, entity.WithTimeout(int(input.Timeout.Seconds())))
	} else {
		opts = append(opts, entity.WithTimeout(int(uc.config.DefaultTimeout.Seconds())))
	}

	if input.ClientID != "" {
		opts = append(opts, entity.WithClientID(input.ClientID))
	}

	if input.IdempotencyKey != "" {
		opts = append(opts, entity.WithIdempotencyKey(input.IdempotencyKey))
	}

	// Create task
	task := entity.CreateTask(input.TaskType, input.Payload, opts...)

	// Save task
	if err := uc.taskRepo.Save(ctx, task); err != nil {
		log.Error().Err(err).Str("task_id", task.TaskID).Msg("Failed to save task")
		return nil, fmt.Errorf("failed to save task: %w", err)
	}

	log.Info().
		Str("task_id", task.TaskID).
		Str("task_type", string(task.TaskType)).
		Str("executor_type", string(task.ExecutorType)).
		Msg("Task submitted successfully")

	return task, nil
}

// GetTask retrieves a task by ID.
func (uc *UseCase) GetTask(ctx context.Context, taskID string) (*entity.Task, error) {
	return uc.taskRepo.Get(ctx, taskID)
}

// CompleteTask marks a task as completed.
func (uc *UseCase) CompleteTask(ctx context.Context, taskID string, result map[string]any) error {
	log := logger.WithFields(uc.log)

	task, err := uc.taskRepo.Get(ctx, taskID)
	if err != nil {
		return fmt.Errorf("task not found: %w", err)
	}

	uc.mu.RLock()
	sender := uc.sender
	uc.mu.RUnlock()

	workerID := task.Context.WorkerID
	if sender != nil && workerID != "" {
		_ = sender.RemoveActiveTask(ctx, workerID, taskID)
	}

	task.Complete(result)

	if err := uc.taskRepo.Update(ctx, task); err != nil {
		return fmt.Errorf("failed to update task: %w", err)
	}

	log.Info().
		Str("task_id", taskID).
		Msg("Task completed successfully")

	return nil
}

// FailTask marks a task as failed.
func (uc *UseCase) FailTask(ctx context.Context, taskID, errorType, errorMessage, errorTrace string) error {
	log := logger.WithFields(uc.log)

	task, err := uc.taskRepo.Get(ctx, taskID)
	if err != nil {
		return fmt.Errorf("task not found: %w", err)
	}

	uc.mu.RLock()
	sender := uc.sender
	uc.mu.RUnlock()

	workerID := task.Context.WorkerID
	if sender != nil && workerID != "" {
		_ = sender.RemoveActiveTask(ctx, workerID, taskID)
	}

	// Mark failed for this attempt
	task.Fail(errorMessage, errorTrace)
	if task.Context != nil {
		task.Context.AddAttempt(workerID, errorMessage)
	}

	// If we can retry, schedule retry and reset assignment/execution timestamps
	if task.ScheduleRetry() {
		task.Context.WorkerID = ""
		task.Context.AssignedAt = nil
		task.Context.StartedAt = nil
		task.Context.CompletedAt = nil
		task.Context.ExpiresAt = nil

		if err := uc.taskRepo.Update(ctx, task); err != nil {
			return fmt.Errorf("failed to schedule retry: %w", err)
		}

		log.Info().
			Str("task_id", taskID).
			Int("attempt", task.Context.CurrentAttempt).
			Msg("Task scheduled for retry")

		return nil
	}

	if err := uc.taskRepo.Update(ctx, task); err != nil {
		return fmt.Errorf("failed to update failed task: %w", err)
	}

	log.Warn().
		Str("task_id", taskID).
		Str("error_type", errorType).
		Str("error_message", errorMessage).
		Msg("Task failed")

	return nil
}

// ProcessPendingTasks processes pending tasks and assigns them to available workers.
func (uc *UseCase) ProcessPendingTasks(ctx context.Context) (int, error) {
	log := logger.WithFields(uc.log)

	uc.processMu.Lock()
	defer uc.processMu.Unlock()

	uc.mu.RLock()
	sender := uc.sender
	uc.mu.RUnlock()

	if sender == nil {
		return 0, nil
	}

	// Спочатку обробляємо прострочені (timeout) задачі.
	_, _ = uc.processExpiredTasks(ctx, sender)

	// Get pending tasks
	tasks, err := uc.taskRepo.GetPending(ctx, uc.config.BatchSize)
	if err != nil {
		return 0, fmt.Errorf("failed to get pending tasks: %w", err)
	}

	var assigned int
	for _, task := range tasks {
		// Find available executor based on executor_type
		executors, err := sender.GetAvailableExecutors(ctx, task.ExecutorType, string(task.TaskType))
		if err != nil || len(executors) == 0 {
			continue
		}

		// Pick the least loaded executor
		var selectedWorker *entity.Client
		minLoad := 100.0
		for _, w := range executors {
			load := w.Info.GetLoadPercentage()
			if load < minLoad {
				minLoad = load
				selectedWorker = w
			}
		}

		if selectedWorker == nil {
			continue
		}

		// Mark task as active for the executor (fail-safe for concurrency)
		if err := sender.SetActiveTask(ctx, selectedWorker.Info.ClientID, task.TaskID); err != nil {
			log.Warn().Err(err).
				Str("task_id", task.TaskID).
				Str("worker_id", selectedWorker.Info.ClientID).
				Msg("Failed to mark task as active for executor")
			continue
		}

		// Assign task to worker
		task.AssignToWorker(selectedWorker.Info.ClientID)
		task.StartExecution()

		// Update task in repository
		if err := uc.taskRepo.Update(ctx, task); err != nil {
			log.Warn().Err(err).Str("task_id", task.TaskID).Msg("Failed to update task")
			_ = sender.RemoveActiveTask(ctx, selectedWorker.Info.ClientID, task.TaskID)
			continue
		}

		// Send task to worker
		taskMsg := entity.TaskMessage{
			BaseMessage:  entity.NewBaseMessage(entity.MessageTypeTask),
			TaskID:       task.TaskID,
			TaskType:     task.TaskType,
			ExecutorType: task.ExecutorType,
			Priority:     task.Priority,
			Payload:      task.Data,
			Timeout:      time.Duration(task.Timeout) * time.Second,
		}

		if err := sender.SendToClient(selectedWorker.Info.ClientID, taskMsg); err != nil {
			log.Warn().Err(err).
				Str("task_id", task.TaskID).
				Str("worker_id", selectedWorker.Info.ClientID).
				Msg("Failed to send task to worker, resetting assignment")

			// Reset task assignment
			task.Context.ResetAssignment()
			uc.taskRepo.Update(ctx, task)
			_ = sender.RemoveActiveTask(ctx, selectedWorker.Info.ClientID, task.TaskID)
			continue
		}

		assigned++
		log.Debug().
			Str("task_id", task.TaskID).
			Str("worker_id", selectedWorker.Info.ClientID).
			Msg("Task assigned to worker")
	}

	if assigned > 0 {
		log.Info().Int("count", assigned).Msg("Pending tasks processed")
	}

	return assigned, nil
}

func (uc *UseCase) processExpiredTasks(ctx context.Context, sender TaskSender) (int, error) {
	expired, err := uc.taskRepo.GetExpired(ctx, uc.config.BatchSize)
	if err != nil {
		return 0, err
	}
	if len(expired) == 0 {
		return 0, nil
	}

	log := logger.WithFields(uc.log)

	processed := 0
	for _, task := range expired {
		if task == nil || task.Context == nil || task.Context.IsCompleted() {
			continue
		}

		workerID := task.Context.WorkerID
		if workerID != "" {
			_ = sender.RemoveActiveTask(ctx, workerID, task.TaskID)
		}

		// Позначаємо як timeout (це важливо для CanRetry()).
		task.Context.AddError("timeout", "Task timed out", "")
		task.MarkTimeout()
		task.Context.AddAttempt(workerID, "timeout")

		// Якщо можна повторити — плануємо retry.
		if task.ScheduleRetry() {
			task.Context.WorkerID = ""
			task.Context.AssignedAt = nil
			task.Context.StartedAt = nil
			task.Context.CompletedAt = nil
			task.Context.ExpiresAt = nil
		}

		if err := uc.taskRepo.Update(ctx, task); err != nil {
			log.Warn().Err(err).Str("task_id", task.TaskID).Msg("Failed to update expired task")
			continue
		}

		expiredAt := ""
		if task.Context.ExpiresAt != nil {
			expiredAt = task.Context.ExpiresAt.UTC().Format(time.RFC3339)
		}

		processed++
		log.Info().
			Str("task_id", task.TaskID).
			Str("status", string(task.Context.CurrentStatus)).
			Str("expired_at", expiredAt).
			Msg("Expired task processed")
	}

	return processed, nil
}

// CleanupOldTasks removes completed tasks older than the configured duration.
func (uc *UseCase) CleanupOldTasks(ctx context.Context) (int64, error) {
	log := logger.WithFields(uc.log)

	// Convert cleanup age to hours for the repository
	cleanupHours := int(uc.config.CleanupAge.Hours())
	if cleanupHours < 1 {
		cleanupHours = 24
	}

	deleted, err := uc.taskRepo.DeleteOlderThan(ctx, cleanupHours)
	if err != nil {
		return 0, fmt.Errorf("failed to cleanup old tasks: %w", err)
	}

	if deleted > 0 {
		log.Info().Int64("deleted", deleted).Msg("Old tasks cleaned up")
	}

	return deleted, nil
}

// GetStats retrieves task statistics.
func (uc *UseCase) GetStats(ctx context.Context) (*Stats, error) {
	repoStats, err := uc.taskRepo.GetStats(ctx)
	if err != nil {
		return nil, err
	}

	return &Stats{
		TotalTasks:        repoStats.TotalTasks,
		PendingTasks:      repoStats.PendingTasks,
		ProcessingTasks:   repoStats.ProcessingTasks,
		CompletedTasks:    repoStats.CompletedTasks,
		FailedTasks:       repoStats.FailedTasks,
		TasksByType:       repoStats.TasksByType,
		AvgProcessingTime: repoStats.AverageProcessingMs,
	}, nil
}

// CancelTask cancels a pending or processing task.
func (uc *UseCase) CancelTask(ctx context.Context, taskID, reason string) error {
	log := logger.WithFields(uc.log)

	task, err := uc.taskRepo.Get(ctx, taskID)
	if err != nil {
		return fmt.Errorf("task not found: %w", err)
	}

	if task.Context.IsCompleted() {
		return fmt.Errorf("cannot cancel completed task")
	}

	task.Cancel(reason)

	if err := uc.taskRepo.Update(ctx, task); err != nil {
		return fmt.Errorf("failed to cancel task: %w", err)
	}

	log.Info().
		Str("task_id", taskID).
		Str("reason", reason).
		Msg("Task cancelled")

	return nil
}

// GetAllTasks retrieves all tasks with pagination.
func (uc *UseCase) GetAllTasks(ctx context.Context, limit, offset int) ([]*entity.Task, error) {
	return uc.taskRepo.GetAll(ctx, limit, offset)
}

// GetTasksByStatus retrieves tasks by status.
func (uc *UseCase) GetTasksByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error) {
	return uc.taskRepo.GetByStatus(ctx, status, limit)
}

// GetTasksByType retrieves tasks by type.
func (uc *UseCase) GetTasksByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error) {
	return uc.taskRepo.GetByType(ctx, taskType, limit)
}

// DeleteTask deletes a task.
func (uc *UseCase) DeleteTask(ctx context.Context, taskID string) error {
	return uc.taskRepo.Delete(ctx, taskID)
}

// RetryTask retries a failed task.
func (uc *UseCase) RetryTask(ctx context.Context, taskID string) error {
	log := logger.WithFields(uc.log)

	task, err := uc.taskRepo.Get(ctx, taskID)
	if err != nil {
		return fmt.Errorf("task not found: %w", err)
	}

	if !task.Context.IsCompleted() {
		return fmt.Errorf("can only retry completed tasks")
	}

	// Reset task for retry
	task.Context.CurrentStatus = entity.TaskStatusPending
	task.Context.WorkerID = ""
	task.Context.AssignedAt = nil
	task.Context.StartedAt = nil
	task.Context.CompletedAt = nil
	task.Context.CurrentAttempt = 1

	if err := uc.taskRepo.Update(ctx, task); err != nil {
		return fmt.Errorf("failed to retry task: %w", err)
	}

	log.Info().Str("task_id", taskID).Msg("Task queued for retry")

	return nil
}

// marshalTaskMessage marshals a task message to JSON.
func marshalTaskMessage(task *entity.Task) ([]byte, error) {
	msg := entity.TaskMessage{
		BaseMessage:  entity.NewBaseMessage(entity.MessageTypeTask),
		TaskID:       task.TaskID,
		TaskType:     task.TaskType,
		ExecutorType: task.ExecutorType,
		Priority:     task.Priority,
		Payload:      task.Data,
		Timeout:      time.Duration(task.Timeout) * time.Second,
	}
	return json.Marshal(msg)
}
