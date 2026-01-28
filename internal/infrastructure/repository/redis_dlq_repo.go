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
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	dlqKeyPrefix      = "dlq:"
	dlqSetKey         = "dlq:entries"
	dlqReasonSetKey   = "dlq:reason:"
	dlqTaskTypeSetKey = "dlq:tasktype:"
	dlqTaskIDKey      = "dlq:taskid:"
)

// RedisDLQRepository implements DLQRepository using Redis.
type RedisDLQRepository struct {
	client goredis.UniversalClient
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisDLQRepository creates a new Redis DLQ repository.
func NewRedisDLQRepository(client goredis.UniversalClient) *RedisDLQRepository {
	return &RedisDLQRepository{
		client: client,
		ttl:    30 * 24 * time.Hour, // 30 days default TTL for DLQ entries
		log:    logger.LogFields{"component": "redis-dlq-repo"},
	}
}

// Save stores a DLQ entry.
func (r *RedisDLQRepository) Save(ctx context.Context, entry *entity.DLQEntry) error {
	data, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("failed to marshal DLQ entry: %w", err)
	}

	key := dlqKeyPrefix + entry.ID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)
	pipe.SAdd(ctx, dlqSetKey, entry.ID)
	pipe.SAdd(ctx, dlqReasonSetKey+string(entry.Reason), entry.ID)
	pipe.SAdd(ctx, dlqTaskTypeSetKey+string(entry.TaskType), entry.ID)
	pipe.Set(ctx, dlqTaskIDKey+entry.TaskID, entry.ID, r.ttl)

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a DLQ entry by ID.
func (r *RedisDLQRepository) Get(ctx context.Context, id string) (*entity.DLQEntry, error) {
	key := dlqKeyPrefix + id
	data, err := r.client.Get(ctx, key).Result()
	if err != nil {
		return nil, repository.ErrDLQEntryNotFound
	}

	var entry entity.DLQEntry
	if err := json.Unmarshal([]byte(data), &entry); err != nil {
		return nil, fmt.Errorf("failed to unmarshal DLQ entry: %w", err)
	}

	return &entry, nil
}

// GetByTaskID retrieves a DLQ entry by original task ID.
func (r *RedisDLQRepository) GetByTaskID(ctx context.Context, taskID string) (*entity.DLQEntry, error) {
	entryID, err := r.client.Get(ctx, dlqTaskIDKey+taskID).Result()
	if err != nil {
		return nil, repository.ErrDLQEntryNotFound
	}

	return r.Get(ctx, entryID)
}

// GetAll retrieves all DLQ entries with optional pagination.
func (r *RedisDLQRepository) GetAll(ctx context.Context, limit, offset int) ([]*entity.DLQEntry, error) {
	entryIDs, err := r.client.SMembers(ctx, dlqSetKey).Result()
	if err != nil {
		return nil, err
	}

	// Apply pagination
	start := offset
	end := offset + limit
	if start > len(entryIDs) {
		return []*entity.DLQEntry{}, nil
	}
	if end > len(entryIDs) || limit == 0 {
		end = len(entryIDs)
	}

	entries := make([]*entity.DLQEntry, 0, end-start)
	for i := start; i < end; i++ {
		entry, err := r.Get(ctx, entryIDs[i])
		if err != nil {
			continue
		}
		entries = append(entries, entry)
	}

	return entries, nil
}

// GetByReason retrieves DLQ entries by reason.
func (r *RedisDLQRepository) GetByReason(ctx context.Context, reason entity.DLQReason, limit int) ([]*entity.DLQEntry, error) {
	entryIDs, err := r.client.SMembers(ctx, dlqReasonSetKey+string(reason)).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(entryIDs) {
		entryIDs = entryIDs[:limit]
	}

	entries := make([]*entity.DLQEntry, 0, len(entryIDs))
	for _, id := range entryIDs {
		entry, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		entries = append(entries, entry)
	}

	return entries, nil
}

// GetByTaskType retrieves DLQ entries by task type.
func (r *RedisDLQRepository) GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.DLQEntry, error) {
	entryIDs, err := r.client.SMembers(ctx, dlqTaskTypeSetKey+string(taskType)).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(entryIDs) {
		entryIDs = entryIDs[:limit]
	}

	entries := make([]*entity.DLQEntry, 0, len(entryIDs))
	for _, id := range entryIDs {
		entry, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		entries = append(entries, entry)
	}

	return entries, nil
}

// GetExpired retrieves expired DLQ entries.
func (r *RedisDLQRepository) GetExpired(ctx context.Context, limit int) ([]*entity.DLQEntry, error) {
	entryIDs, err := r.client.SMembers(ctx, dlqSetKey).Result()
	if err != nil {
		return nil, err
	}

	expired := make([]*entity.DLQEntry, 0)
	for _, id := range entryIDs {
		entry, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		if entry.IsExpired() {
			expired = append(expired, entry)
			if limit > 0 && len(expired) >= limit {
				break
			}
		}
	}

	return expired, nil
}

// Delete removes a DLQ entry.
func (r *RedisDLQRepository) Delete(ctx context.Context, id string) error {
	entry, err := r.Get(ctx, id)
	if err != nil {
		return nil // Entry doesn't exist, nothing to delete
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, dlqKeyPrefix+id)
	pipe.SRem(ctx, dlqSetKey, id)
	pipe.SRem(ctx, dlqReasonSetKey+string(entry.Reason), id)
	pipe.SRem(ctx, dlqTaskTypeSetKey+string(entry.TaskType), id)
	pipe.Del(ctx, dlqTaskIDKey+entry.TaskID)

	_, err = pipe.Exec(ctx)
	return err
}

// DeleteByTaskID removes a DLQ entry by task ID.
func (r *RedisDLQRepository) DeleteByTaskID(ctx context.Context, taskID string) error {
	entry, err := r.GetByTaskID(ctx, taskID)
	if err != nil {
		return nil // Entry doesn't exist
	}

	return r.Delete(ctx, entry.ID)
}

// DeleteOlderThan deletes entries older than the specified hours.
func (r *RedisDLQRepository) DeleteOlderThan(ctx context.Context, hours int) (int64, error) {
	cutoff := time.Now().UTC().Add(-time.Duration(hours) * time.Hour)

	entryIDs, err := r.client.SMembers(ctx, dlqSetKey).Result()
	if err != nil {
		return 0, err
	}

	var deleted int64
	for _, id := range entryIDs {
		entry, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		if entry.FailedAt.Before(cutoff) {
			if err := r.Delete(ctx, id); err == nil {
				deleted++
			}
		}
	}

	return deleted, nil
}

// Purge removes all DLQ entries.
func (r *RedisDLQRepository) Purge(ctx context.Context) (int64, error) {
	entryIDs, err := r.client.SMembers(ctx, dlqSetKey).Result()
	if err != nil {
		return 0, err
	}

	var deleted int64
	for _, id := range entryIDs {
		if err := r.Delete(ctx, id); err == nil {
			deleted++
		}
	}

	return deleted, nil
}

// Count returns the total number of DLQ entries.
func (r *RedisDLQRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, dlqSetKey).Result()
}

// CountByReason returns the count of DLQ entries by reason.
func (r *RedisDLQRepository) CountByReason(ctx context.Context, reason entity.DLQReason) (int64, error) {
	return r.client.SCard(ctx, dlqReasonSetKey+string(reason)).Result()
}

// GetStats retrieves DLQ statistics.
func (r *RedisDLQRepository) GetStats(ctx context.Context) (*entity.DLQStats, error) {
	stats := entity.NewDLQStats()

	var err error
	total, err := r.Count(ctx)
	if err != nil {
		return nil, err
	}
	stats.TotalEntries = int(total)

	// Count by reason
	reasons := []entity.DLQReason{
		entity.DLQReasonMaxRetries,
		entity.DLQReasonTimeout,
		entity.DLQReasonFatalError,
		entity.DLQReasonManual,
		entity.DLQReasonInvalidData,
		entity.DLQReasonNoWorker,
	}

	for _, reason := range reasons {
		count, _ := r.CountByReason(ctx, reason)
		if count > 0 {
			stats.EntriesByReason[string(reason)] = int(count)
		}
	}

	// Get additional stats by iterating through entries
	entryIDs, _ := r.client.SMembers(ctx, dlqSetKey).Result()
	var totalRetries int
	var retryableCount int
	var expiredCount int

	for _, id := range entryIDs {
		entry, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		// Count by task type
		stats.EntriesByType[string(entry.TaskType)]++

		// Track oldest and newest
		if stats.OldestEntry == nil || entry.FailedAt.Before(*stats.OldestEntry) {
			stats.OldestEntry = &entry.FailedAt
		}
		if stats.NewestEntry == nil || entry.FailedAt.After(*stats.NewestEntry) {
			stats.NewestEntry = &entry.FailedAt
		}

		totalRetries += entry.RetryCount

		if entry.IsExpired() {
			expiredCount++
		}

		// Check if retryable (not expired and not a fatal error)
		if !entry.IsExpired() && entry.Reason != entity.DLQReasonFatalError && entry.Reason != entity.DLQReasonInvalidData {
			retryableCount++
		}
	}

	stats.ExpiredCount = expiredCount
	stats.RetryableCount = retryableCount

	if stats.TotalEntries > 0 {
		stats.AverageRetries = float64(totalRetries) / float64(stats.TotalEntries)
	}

	return stats, nil
}

// Exists checks if a DLQ entry exists.
func (r *RedisDLQRepository) Exists(ctx context.Context, id string) (bool, error) {
	exists, err := r.client.Exists(ctx, dlqKeyPrefix+id).Result()
	return exists > 0, err
}

// ExistsByTaskID checks if a DLQ entry exists for a task.
func (r *RedisDLQRepository) ExistsByTaskID(ctx context.Context, taskID string) (bool, error) {
	exists, err := r.client.Exists(ctx, dlqTaskIDKey+taskID).Result()
	return exists > 0, err
}

// Ensure interface compliance
var _ repository.DLQRepository = (*RedisDLQRepository)(nil)
