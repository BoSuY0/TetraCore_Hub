// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	scheduleKeyPrefix      = "schedule:"
	scheduleSetKey         = "schedules"
	scheduleNameKey        = "schedules:name:"
	scheduleStatusSetKey   = "schedules:status:"
	scheduleCreatorSetKey  = "schedules:creator:"
	scheduleTaskTypeSetKey = "schedules:tasktype:"
	scheduleTagSetKey      = "schedules:tag:"
	scheduleDueZSetKey     = "schedules:due"
)

// RedisScheduleRepository implements ScheduleRepository using Redis.
type RedisScheduleRepository struct {
	client *redis.Client
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisScheduleRepository creates a new Redis schedule repository.
func NewRedisScheduleRepository(client *redis.Client) *RedisScheduleRepository {
	return &RedisScheduleRepository{
		client: client,
		ttl:    0, // No expiration for schedules by default
		log:    logger.LogFields{"component": "redis-schedule-repo"},
	}
}

// Save stores a schedule.
func (r *RedisScheduleRepository) Save(ctx context.Context, schedule *entity.Schedule) error {
	data, err := json.Marshal(schedule)
	if err != nil {
		return fmt.Errorf("failed to marshal schedule: %w", err)
	}

	key := scheduleKeyPrefix + schedule.ID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)
	pipe.SAdd(ctx, scheduleSetKey, schedule.ID)
	pipe.Set(ctx, scheduleNameKey+schedule.Name, schedule.ID, r.ttl)
	pipe.SAdd(ctx, scheduleStatusSetKey+string(schedule.Status), schedule.ID)
	pipe.SAdd(ctx, scheduleCreatorSetKey+schedule.CreatedBy, schedule.ID)
	pipe.SAdd(ctx, scheduleTaskTypeSetKey+string(schedule.TaskType), schedule.ID)

	// Add to due sorted set if active and has next run time
	if schedule.Status == entity.ScheduleStatusActive && schedule.NextRunAt != nil {
		pipe.ZAdd(ctx, scheduleDueZSetKey, goredis.Z{Score: float64(schedule.NextRunAt.Unix()), Member: schedule.ID})
	} else {
		pipe.ZRem(ctx, scheduleDueZSetKey, schedule.ID)
	}

	for _, tag := range schedule.Tags {
		pipe.SAdd(ctx, scheduleTagSetKey+tag, schedule.ID)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a schedule by ID.
func (r *RedisScheduleRepository) Get(ctx context.Context, id string) (*entity.Schedule, error) {
	key := scheduleKeyPrefix + id
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrScheduleNotFound
	}

	var schedule entity.Schedule
	if err := json.Unmarshal([]byte(data), &schedule); err != nil {
		return nil, fmt.Errorf("failed to unmarshal schedule: %w", err)
	}

	return &schedule, nil
}

// GetByName retrieves a schedule by name.
func (r *RedisScheduleRepository) GetByName(ctx context.Context, name string) (*entity.Schedule, error) {
	scheduleID, err := r.client.Get(ctx, scheduleNameKey+name)
	if err != nil {
		return nil, repository.ErrScheduleNotFound
	}

	return r.Get(ctx, scheduleID)
}

// GetAll retrieves all schedules with optional pagination.
func (r *RedisScheduleRepository) GetAll(ctx context.Context, limit, offset int) ([]*entity.Schedule, error) {
	scheduleIDs, err := r.client.SMembers(ctx, scheduleSetKey)
	if err != nil {
		return nil, err
	}

	// Apply pagination
	start := offset
	end := offset + limit
	if start > len(scheduleIDs) {
		return []*entity.Schedule{}, nil
	}
	if end > len(scheduleIDs) || limit == 0 {
		end = len(scheduleIDs)
	}

	schedules := make([]*entity.Schedule, 0, end-start)
	for i := start; i < end; i++ {
		schedule, err := r.Get(ctx, scheduleIDs[i])
		if err != nil {
			continue
		}
		schedules = append(schedules, schedule)
	}

	return schedules, nil
}

// GetByStatus retrieves schedules by status.
func (r *RedisScheduleRepository) GetByStatus(ctx context.Context, status entity.ScheduleStatus, limit int) ([]*entity.Schedule, error) {
	scheduleIDs, err := r.client.SMembers(ctx, scheduleStatusSetKey+string(status))
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(scheduleIDs) {
		scheduleIDs = scheduleIDs[:limit]
	}

	schedules := make([]*entity.Schedule, 0, len(scheduleIDs))
	for _, id := range scheduleIDs {
		schedule, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		schedules = append(schedules, schedule)
	}

	return schedules, nil
}

// GetActive retrieves all active schedules.
func (r *RedisScheduleRepository) GetActive(ctx context.Context) ([]*entity.Schedule, error) {
	return r.GetByStatus(ctx, entity.ScheduleStatusActive, 0)
}

// GetByCreator retrieves schedules created by a specific user.
func (r *RedisScheduleRepository) GetByCreator(ctx context.Context, createdBy string, limit int) ([]*entity.Schedule, error) {
	scheduleIDs, err := r.client.SMembers(ctx, scheduleCreatorSetKey+createdBy)
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(scheduleIDs) {
		scheduleIDs = scheduleIDs[:limit]
	}

	schedules := make([]*entity.Schedule, 0, len(scheduleIDs))
	for _, id := range scheduleIDs {
		schedule, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		schedules = append(schedules, schedule)
	}

	return schedules, nil
}

// GetDue retrieves schedules that are due to run.
func (r *RedisScheduleRepository) GetDue(ctx context.Context) ([]*entity.Schedule, error) {
	now := time.Now().UTC().Unix()

	// Get all schedules with next_run_at <= now
	scheduleIDs, err := r.client.ZRangeByScore(ctx, scheduleDueZSetKey, &goredis.ZRangeBy{
		Min: "-inf",
		Max: fmt.Sprintf("%d", now),
	})
	if err != nil {
		return nil, err
	}

	schedules := make([]*entity.Schedule, 0, len(scheduleIDs))
	for _, id := range scheduleIDs {
		schedule, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		// Double-check that the schedule is active and due
		if schedule.ShouldRun() {
			schedules = append(schedules, schedule)
		}
	}

	return schedules, nil
}

// GetByTaskType retrieves schedules by task type.
func (r *RedisScheduleRepository) GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Schedule, error) {
	scheduleIDs, err := r.client.SMembers(ctx, scheduleTaskTypeSetKey+string(taskType))
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(scheduleIDs) {
		scheduleIDs = scheduleIDs[:limit]
	}

	schedules := make([]*entity.Schedule, 0, len(scheduleIDs))
	for _, id := range scheduleIDs {
		schedule, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		schedules = append(schedules, schedule)
	}

	return schedules, nil
}

// GetByTag retrieves schedules by tag.
func (r *RedisScheduleRepository) GetByTag(ctx context.Context, tag string, limit int) ([]*entity.Schedule, error) {
	scheduleIDs, err := r.client.SMembers(ctx, scheduleTagSetKey+tag)
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(scheduleIDs) {
		scheduleIDs = scheduleIDs[:limit]
	}

	schedules := make([]*entity.Schedule, 0, len(scheduleIDs))
	for _, id := range scheduleIDs {
		schedule, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		schedules = append(schedules, schedule)
	}

	return schedules, nil
}

// Update updates a schedule.
func (r *RedisScheduleRepository) Update(ctx context.Context, schedule *entity.Schedule) error {
	// Get existing schedule to clean up old indices
	existing, err := r.Get(ctx, schedule.ID)
	if err == nil && existing != nil {
		// Remove old name mapping if changed
		if existing.Name != schedule.Name {
			r.client.Del(ctx, scheduleNameKey+existing.Name)
		}
		// Remove old status set membership if changed
		if existing.Status != schedule.Status {
			r.client.SRem(ctx, scheduleStatusSetKey+string(existing.Status), schedule.ID)
		}
		// Remove old tags
		for _, tag := range existing.Tags {
			r.client.SRem(ctx, scheduleTagSetKey+tag, schedule.ID)
		}
	}

	schedule.UpdatedAt = time.Now().UTC()
	return r.Save(ctx, schedule)
}

// UpdateStatus updates the status of a schedule.
func (r *RedisScheduleRepository) UpdateStatus(ctx context.Context, id string, status entity.ScheduleStatus) error {
	schedule, err := r.Get(ctx, id)
	if err != nil {
		return err
	}

	oldStatus := schedule.Status
	schedule.Status = status
	schedule.UpdatedAt = time.Now().UTC()

	// Update status sets
	pipe := r.client.Pipeline()
	pipe.SRem(ctx, scheduleStatusSetKey+string(oldStatus), id)
	pipe.SAdd(ctx, scheduleStatusSetKey+string(status), id)

	// Update due sorted set
	if status == entity.ScheduleStatusActive && schedule.NextRunAt != nil {
		pipe.ZAdd(ctx, scheduleDueZSetKey, goredis.Z{Score: float64(schedule.NextRunAt.Unix()), Member: id})
	} else {
		pipe.ZRem(ctx, scheduleDueZSetKey, id)
	}

	_, err = pipe.Exec(ctx)
	if err != nil {
		return err
	}

	return r.Save(ctx, schedule)
}

// UpdateNextRun updates the next run time of a schedule.
func (r *RedisScheduleRepository) UpdateNextRun(ctx context.Context, id string, schedule *entity.Schedule) error {
	schedule.UpdatedAt = time.Now().UTC()

	// Update due sorted set
	if schedule.Status == entity.ScheduleStatusActive && schedule.NextRunAt != nil {
		r.client.ZAdd(ctx, scheduleDueZSetKey, goredis.Z{Score: float64(schedule.NextRunAt.Unix()), Member: id})
	} else {
		r.client.ZRem(ctx, scheduleDueZSetKey, id)
	}

	return r.Save(ctx, schedule)
}

// RecordRun records a schedule run.
func (r *RedisScheduleRepository) RecordRun(ctx context.Context, id, taskID string, status entity.TaskStatus) error {
	schedule, err := r.Get(ctx, id)
	if err != nil {
		return err
	}

	schedule.RecordRun(taskID, status)

	// Calculate next run time for recurring schedules
	if schedule.Frequency != entity.ScheduleFrequencyOnce {
		schedule.CalculateNextRun()
	}

	return r.Update(ctx, schedule)
}

// Delete removes a schedule.
func (r *RedisScheduleRepository) Delete(ctx context.Context, id string) error {
	schedule, err := r.Get(ctx, id)
	if err != nil {
		return nil // Schedule doesn't exist, nothing to delete
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, scheduleKeyPrefix+id)
	pipe.SRem(ctx, scheduleSetKey, id)
	pipe.Del(ctx, scheduleNameKey+schedule.Name)
	pipe.SRem(ctx, scheduleStatusSetKey+string(schedule.Status), id)
	pipe.SRem(ctx, scheduleCreatorSetKey+schedule.CreatedBy, id)
	pipe.SRem(ctx, scheduleTaskTypeSetKey+string(schedule.TaskType), id)
	pipe.ZRem(ctx, scheduleDueZSetKey, id)

	for _, tag := range schedule.Tags {
		pipe.SRem(ctx, scheduleTagSetKey+tag, id)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Count returns the total number of schedules.
func (r *RedisScheduleRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, scheduleSetKey)
}

// CountByStatus returns the count of schedules by status.
func (r *RedisScheduleRepository) CountByStatus(ctx context.Context, status entity.ScheduleStatus) (int64, error) {
	return r.client.SCard(ctx, scheduleStatusSetKey+string(status))
}

// Exists checks if a schedule exists.
func (r *RedisScheduleRepository) Exists(ctx context.Context, id string) (bool, error) {
	exists, err := r.client.Exists(ctx, scheduleKeyPrefix+id)
	return exists > 0, err
}

// ExistsByName checks if a schedule with the given name exists.
func (r *RedisScheduleRepository) ExistsByName(ctx context.Context, name string) (bool, error) {
	exists, err := r.client.Exists(ctx, scheduleNameKey+name)
	return exists > 0, err
}

// Ensure interface compliance
var _ repository.ScheduleRepository = (*RedisScheduleRepository)(nil)
