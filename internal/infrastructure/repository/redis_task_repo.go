// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	taskKeyPrefix         = "task:"
	taskSetKey            = "tasks"
	taskStatusSetKey      = "tasks:status:"
	taskTypeSetKey        = "tasks:type:"
	taskClientSetKey      = "tasks:client:"
	taskWorkerSetKey      = "tasks:worker:"
	taskPendingZSetKey    = "tasks:pending"
	taskRetryZSetKey      = "tasks:retry"
	taskIdempotencyKey    = "tasks:idempotency:"
	taskExecutorSetKey    = "tasks:executor:"
)

// RedisTaskRepository implements TaskRepository using Redis.
type RedisTaskRepository struct {
	client *redis.Client
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisTaskRepository creates a new Redis task repository.
func NewRedisTaskRepository(client *redis.Client, ttl time.Duration) *RedisTaskRepository {
	return &RedisTaskRepository{
		client: client,
		ttl:    ttl,
		log:    logger.LogFields{"component": "redis-task-repo"},
	}
}

// Save stores a task.
func (r *RedisTaskRepository) Save(ctx context.Context, task *entity.Task) error {
	// Ensure RetryAt is set when scheduling retries (so Redis score is deterministic).
	if task.Context != nil && task.Context.CurrentStatus == entity.TaskStatusRetry && task.Context.RetryAt == nil {
		retryAt := time.Now().UTC().Add(time.Duration(task.RetryDelay) * time.Second)
		task.Context.RetryAt = &retryAt
	}

	data, err := json.Marshal(task)
	if err != nil {
		return fmt.Errorf("failed to marshal task: %w", err)
	}

	key := taskKeyPrefix + task.TaskID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)
	pipe.SAdd(ctx, taskSetKey, task.TaskID)
	pipe.SAdd(ctx, taskStatusSetKey+string(task.Context.CurrentStatus), task.TaskID)
	pipe.SAdd(ctx, taskTypeSetKey+string(task.TaskType), task.TaskID)
	pipe.SAdd(ctx, taskExecutorSetKey+string(task.ExecutorType), task.TaskID)

	if task.Context.ClientID != "" {
		pipe.SAdd(ctx, taskClientSetKey+task.Context.ClientID, task.TaskID)
	}

	if task.Context.WorkerID != "" {
		pipe.SAdd(ctx, taskWorkerSetKey+task.Context.WorkerID, task.TaskID)
	}

	// Add to pending sorted set if pending
	if task.Context.CurrentStatus == entity.TaskStatusPending {
		score := float64(task.GetPriorityScore())*1000000 - float64(task.Context.CreatedAt.Unix())
		pipe.ZAdd(ctx, taskPendingZSetKey, goredis.Z{Score: score, Member: task.TaskID})
	} else {
		pipe.ZRem(ctx, taskPendingZSetKey, task.TaskID)
	}

	// Retry scheduling: keep retry tasks in a time-based ZSET, remove otherwise.
	if task.Context.CurrentStatus == entity.TaskStatusRetry && task.Context.RetryAt != nil {
		pipe.ZAdd(ctx, taskRetryZSetKey, goredis.Z{Score: float64(task.Context.RetryAt.Unix()), Member: task.TaskID})
	} else {
		pipe.ZRem(ctx, taskRetryZSetKey, task.TaskID)
	}

	// Store idempotency key mapping if present
	if task.Metadata.IdempotencyKey != "" {
		pipe.Set(ctx, taskIdempotencyKey+task.Metadata.IdempotencyKey, task.TaskID, r.ttl)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a task by ID.
func (r *RedisTaskRepository) Get(ctx context.Context, taskID string) (*entity.Task, error) {
	key := taskKeyPrefix + taskID
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrTaskNotFound
	}

	var task entity.Task
	if err := json.Unmarshal([]byte(data), &task); err != nil {
		return nil, fmt.Errorf("failed to unmarshal task: %w", err)
	}

	return &task, nil
}

// GetAll retrieves all tasks with optional pagination.
func (r *RedisTaskRepository) GetAll(ctx context.Context, limit, offset int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskSetKey)
	if err != nil {
		return nil, err
	}

	// Apply pagination
	start := offset
	end := offset + limit
	if start > len(taskIDs) {
		return []*entity.Task{}, nil
	}
	if end > len(taskIDs) {
		end = len(taskIDs)
	}

	tasks := make([]*entity.Task, 0, end-start)
	for i := start; i < end; i++ {
		task, err := r.Get(ctx, taskIDs[i])
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

// GetByStatus retrieves tasks by status.
func (r *RedisTaskRepository) GetByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskStatusSetKey+string(status))
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(taskIDs) {
		taskIDs = taskIDs[:limit]
	}

	tasks := make([]*entity.Task, 0, len(taskIDs))
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

// GetByType retrieves tasks by type.
func (r *RedisTaskRepository) GetByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskTypeSetKey+string(taskType))
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(taskIDs) {
		taskIDs = taskIDs[:limit]
	}

	tasks := make([]*entity.Task, 0, len(taskIDs))
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

// GetByClientID retrieves tasks for a specific client.
func (r *RedisTaskRepository) GetByClientID(ctx context.Context, clientID string, limit int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskClientSetKey+clientID)
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(taskIDs) {
		taskIDs = taskIDs[:limit]
	}

	tasks := make([]*entity.Task, 0, len(taskIDs))
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

// GetByWorkerID retrieves tasks assigned to a specific worker.
func (r *RedisTaskRepository) GetByWorkerID(ctx context.Context, workerID string, limit int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskWorkerSetKey+workerID)
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(taskIDs) {
		taskIDs = taskIDs[:limit]
	}

	tasks := make([]*entity.Task, 0, len(taskIDs))
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

// GetPending retrieves pending tasks ordered by priority.
func (r *RedisTaskRepository) GetPending(ctx context.Context, limit int) ([]*entity.Task, error) {
	// Best-effort: promote due retries back into pending before selecting tasks.
	_ = r.promoteDueRetries(ctx, limit)

	// Get from sorted set with scores
	results, err := r.client.ZRangeWithScores(ctx, taskPendingZSetKey, 0, -1)
	if err != nil {
		return nil, err
	}

	// Sort by score descending (highest priority first)
	sort.Slice(results, func(i, j int) bool {
		return results[i].Score > results[j].Score
	})

	// Apply limit
	if limit > 0 && limit < len(results) {
		results = results[:limit]
	}

	tasks := make([]*entity.Task, 0, len(results))
	for _, z := range results {
		taskID, ok := z.Member.(string)
		if !ok {
			continue
		}
		task, err := r.Get(ctx, taskID)
		if err != nil {
			continue
		}
		tasks = append(tasks, task)
	}

	return tasks, nil
}

func (r *RedisTaskRepository) promoteDueRetries(ctx context.Context, limit int) error {
	promoteLimit := limit
	if promoteLimit <= 0 {
		promoteLimit = 100
	}

	nowUnix := time.Now().UTC().Unix()
	ids, err := r.client.ZRangeByScore(ctx, taskRetryZSetKey, &goredis.ZRangeBy{
		Min:    "-inf",
		Max:    fmt.Sprintf("%d", nowUnix),
		Offset: 0,
		Count:  int64(promoteLimit),
	})
	if err != nil {
		return err
	}
	if len(ids) == 0 {
		return nil
	}

	now := time.Now().UTC()
	for _, id := range ids {
		task, err := r.Get(ctx, id)
		if err != nil || task == nil || task.Context == nil {
			_ = r.client.ZRem(ctx, taskRetryZSetKey, id)
			continue
		}

		if task.Context.CurrentStatus != entity.TaskStatusRetry {
			_ = r.client.ZRem(ctx, taskRetryZSetKey, id)
			continue
		}
		if task.Context.RetryAt != nil && task.Context.RetryAt.After(now) {
			continue
		}

		task.Context.RetryAt = nil
		task.Context.WorkerID = ""
		task.Context.AssignedAt = nil
		task.Context.StartedAt = nil
		task.Context.CompletedAt = nil
		task.Context.ExpiresAt = nil
		task.Context.AddStatusChange(entity.TaskStatusPending, "Повтор дозрів: переведено в pending")

		if err := r.Update(ctx, task); err != nil {
			continue
		}
	}

	return nil
}

// GetPendingByExecutorType retrieves pending tasks for a specific executor type.
func (r *RedisTaskRepository) GetPendingByExecutorType(ctx context.Context, executorType entity.ExecutorType, limit int) ([]*entity.Task, error) {
	// Get pending tasks
	pending, err := r.GetPending(ctx, 0) // Get all pending
	if err != nil {
		return nil, err
	}

	// Filter by executor type
	tasks := make([]*entity.Task, 0)
	for _, task := range pending {
		if task.ExecutorType == executorType {
			tasks = append(tasks, task)
			if limit > 0 && len(tasks) >= limit {
				break
			}
		}
	}

	return tasks, nil
}

// Update updates a task.
func (r *RedisTaskRepository) Update(ctx context.Context, task *entity.Task) error {
	// Get existing task to clean up old indices
	existing, err := r.Get(ctx, task.TaskID)
	if err == nil && existing != nil {
		// Remove from old status set
		if existing.Context.CurrentStatus != task.Context.CurrentStatus {
			r.client.SRem(ctx, taskStatusSetKey+string(existing.Context.CurrentStatus), task.TaskID)
		}
		// Remove from old worker set
		if existing.Context.WorkerID != task.Context.WorkerID && existing.Context.WorkerID != "" {
			r.client.SRem(ctx, taskWorkerSetKey+existing.Context.WorkerID, task.TaskID)
		}
	}

	return r.Save(ctx, task)
}

// UpdateStatus updates the status of a task.
func (r *RedisTaskRepository) UpdateStatus(ctx context.Context, taskID string, status entity.TaskStatus) error {
	task, err := r.Get(ctx, taskID)
	if err != nil {
		return err
	}

	oldStatus := task.Context.CurrentStatus
	task.Context.AddStatusChange(status, "Status updated")

	// Update status sets
	pipe := r.client.Pipeline()
	pipe.SRem(ctx, taskStatusSetKey+string(oldStatus), taskID)
	pipe.SAdd(ctx, taskStatusSetKey+string(status), taskID)

	// Update pending sorted set
	if status == entity.TaskStatusPending {
		score := float64(task.GetPriorityScore())*1000000 - float64(task.Context.CreatedAt.Unix())
		pipe.ZAdd(ctx, taskPendingZSetKey, goredis.Z{Score: score, Member: taskID})
	} else {
		pipe.ZRem(ctx, taskPendingZSetKey, taskID)
	}

	_, err = pipe.Exec(ctx)
	if err != nil {
		return err
	}

	return r.Save(ctx, task)
}

// AssignToWorker assigns a task to a worker.
func (r *RedisTaskRepository) AssignToWorker(ctx context.Context, taskID, workerID string) error {
	task, err := r.Get(ctx, taskID)
	if err != nil {
		return err
	}

	task.AssignToWorker(workerID)
	return r.Update(ctx, task)
}

// Delete removes a task.
func (r *RedisTaskRepository) Delete(ctx context.Context, taskID string) error {
	task, err := r.Get(ctx, taskID)
	if err != nil {
		return nil // Task doesn't exist, nothing to delete
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, taskKeyPrefix+taskID)
	pipe.SRem(ctx, taskSetKey, taskID)
	pipe.SRem(ctx, taskStatusSetKey+string(task.Context.CurrentStatus), taskID)
	pipe.SRem(ctx, taskTypeSetKey+string(task.TaskType), taskID)
	pipe.SRem(ctx, taskExecutorSetKey+string(task.ExecutorType), taskID)
	pipe.ZRem(ctx, taskPendingZSetKey, taskID)
	pipe.ZRem(ctx, taskRetryZSetKey, taskID)

	if task.Context.ClientID != "" {
		pipe.SRem(ctx, taskClientSetKey+task.Context.ClientID, taskID)
	}

	if task.Context.WorkerID != "" {
		pipe.SRem(ctx, taskWorkerSetKey+task.Context.WorkerID, taskID)
	}

	if task.Metadata.IdempotencyKey != "" {
		pipe.Del(ctx, taskIdempotencyKey+task.Metadata.IdempotencyKey)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// DeleteOlderThan deletes tasks older than the specified duration.
func (r *RedisTaskRepository) DeleteOlderThan(ctx context.Context, hours int) (int64, error) {
	cutoff := time.Now().UTC().Add(-time.Duration(hours) * time.Hour)

	taskIDs, err := r.client.SMembers(ctx, taskSetKey)
	if err != nil {
		return 0, err
	}

	var deleted int64
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		if task.Context.CreatedAt.Before(cutoff) && task.Context.IsCompleted() {
			if err := r.Delete(ctx, id); err == nil {
				deleted++
			}
		}
	}

	return deleted, nil
}

// Count returns the total number of tasks.
func (r *RedisTaskRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, taskSetKey)
}

// CountByStatus returns the count of tasks by status.
func (r *RedisTaskRepository) CountByStatus(ctx context.Context, status entity.TaskStatus) (int64, error) {
	return r.client.SCard(ctx, taskStatusSetKey+string(status))
}

// Exists checks if a task exists.
func (r *RedisTaskRepository) Exists(ctx context.Context, taskID string) (bool, error) {
	exists, err := r.client.Exists(ctx, taskKeyPrefix+taskID)
	return exists > 0, err
}

// GetByIdempotencyKey retrieves a task by idempotency key.
func (r *RedisTaskRepository) GetByIdempotencyKey(ctx context.Context, key string) (*entity.Task, error) {
	taskID, err := r.client.Get(ctx, taskIdempotencyKey+key)
	if err != nil {
		return nil, repository.ErrTaskNotFound
	}

	return r.Get(ctx, taskID)
}

// GetExpired retrieves expired tasks.
func (r *RedisTaskRepository) GetExpired(ctx context.Context, limit int) ([]*entity.Task, error) {
	taskIDs, err := r.client.SMembers(ctx, taskSetKey)
	if err != nil {
		return nil, err
	}

	expired := make([]*entity.Task, 0)
	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		if task.Context.IsExpired() && !task.Context.IsCompleted() {
			expired = append(expired, task)
			if limit > 0 && len(expired) >= limit {
				break
			}
		}
	}

	return expired, nil
}

// GetStats retrieves task statistics.
func (r *RedisTaskRepository) GetStats(ctx context.Context) (*repository.TaskStats, error) {
	stats := &repository.TaskStats{
		TasksByType:     make(map[string]int64),
		TasksByPriority: make(map[string]int64),
	}

	var err error
	stats.TotalTasks, err = r.Count(ctx)
	if err != nil {
		return nil, err
	}

	stats.PendingTasks, _ = r.CountByStatus(ctx, entity.TaskStatusPending)
	stats.ProcessingTasks, _ = r.CountByStatus(ctx, entity.TaskStatusProcessing)
	stats.CompletedTasks, _ = r.CountByStatus(ctx, entity.TaskStatusCompleted)
	stats.FailedTasks, _ = r.CountByStatus(ctx, entity.TaskStatusFailed)
	stats.TimeoutTasks, _ = r.CountByStatus(ctx, entity.TaskStatusTimeout)

	// Calculate tasks by type
	taskTypes := []entity.TaskType{
		entity.TaskTypeAPIRequest,
		entity.TaskTypeDataProcessing,
		entity.TaskTypeFileUpload,
		entity.TaskTypeNotification,
		entity.TaskTypeWebhook,
		entity.TaskTypeCalculation,
		entity.TaskTypeSendMessage,
		entity.TaskTypeCustom,
		entity.TaskTypeWorkerTask,
	}

	for _, t := range taskTypes {
		count, _ := r.client.SCard(ctx, taskTypeSetKey+string(t))
		if count > 0 {
			stats.TasksByType[string(t)] = count
		}
	}

	// Calculate tasks by priority - need to iterate through tasks
	priorities := map[entity.TaskPriority]int64{
		entity.TaskPriorityLow:      0,
		entity.TaskPriorityNormal:   0,
		entity.TaskPriorityHigh:     0,
		entity.TaskPriorityCritical: 0,
	}

	taskIDs, _ := r.client.SMembers(ctx, taskSetKey)
	var totalProcessingTime float64
	var completedCount int64
	var oldestPendingAge float64

	for _, id := range taskIDs {
		task, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		priorities[task.Priority]++

		if task.Context.CurrentStatus == entity.TaskStatusCompleted {
			if execTime := task.Context.GetExecutionTime(); execTime != nil {
				totalProcessingTime += *execTime * 1000 // Convert to ms
				completedCount++
			}
		}

		if task.Context.CurrentStatus == entity.TaskStatusPending {
			age := time.Since(task.Context.CreatedAt).Seconds()
			if age > oldestPendingAge {
				oldestPendingAge = age
			}
		}
	}

	for p, count := range priorities {
		if count > 0 {
			stats.TasksByPriority[string(p)] = count
		}
	}

	if completedCount > 0 {
		stats.AverageProcessingMs = totalProcessingTime / float64(completedCount)
	}
	stats.OldestPendingAge = oldestPendingAge

	return stats, nil
}

// Ensure interface compliance
var _ repository.TaskRepository = (*RedisTaskRepository)(nil)
