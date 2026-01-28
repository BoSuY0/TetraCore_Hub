// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	auditKeyPrefix       = "audit:"
	auditListKey         = "audit:list"
	auditUserListKey     = "audit:user:"
	auditActionListKey   = "audit:action:"
	auditResourceListKey = "audit:resource:"
	auditRetentionDays   = 90
)

// RedisAuditRepository implements AuditRepository using Redis.
type RedisAuditRepository struct {
	client *redis.Client
	log    logger.LogFields
	ttl    time.Duration
}

// NewRedisAuditRepository creates a new Redis audit repository.
func NewRedisAuditRepository(client *redis.Client) *RedisAuditRepository {
	return &RedisAuditRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-audit-repo"},
		ttl:    time.Duration(auditRetentionDays) * 24 * time.Hour,
	}
}

// Save stores an audit entry.
func (r *RedisAuditRepository) Save(ctx context.Context, entry *entity.AuditEntry) error {
	data, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("failed to marshal audit entry: %w", err)
	}

	key := auditKeyPrefix + entry.ID
	timestamp := float64(entry.Timestamp.UnixNano())

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)

	// Add to sorted sets for efficient querying
	member := goredis.Z{Score: timestamp, Member: entry.ID}
	pipe.ZAdd(ctx, auditListKey, member)

	if entry.UserID != "" {
		pipe.ZAdd(ctx, auditUserListKey+entry.UserID, member)
	}

	pipe.ZAdd(ctx, auditActionListKey+string(entry.Action), member)

	if entry.Resource != "" {
		pipe.ZAdd(ctx, auditResourceListKey+entry.Resource+":"+entry.ResourceID, member)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// GetByID retrieves an audit entry by ID.
func (r *RedisAuditRepository) GetByID(ctx context.Context, id string) (*entity.AuditEntry, error) {
	key := auditKeyPrefix + id
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrAuditEntryNotFound
	}

	var entry entity.AuditEntry
	if err := json.Unmarshal([]byte(data), &entry); err != nil {
		return nil, fmt.Errorf("failed to unmarshal audit entry: %w", err)
	}

	return &entry, nil
}

// Query retrieves audit entries based on filter.
func (r *RedisAuditRepository) Query(ctx context.Context, filter entity.AuditFilter) ([]*entity.AuditEntry, error) {
	var entryIDs []string
	var err error

	// Choose the most specific index
	if filter.UserID != "" {
		entryIDs, err = r.getFromSortedSet(ctx, auditUserListKey+filter.UserID, filter)
	} else if filter.Action != "" {
		entryIDs, err = r.getFromSortedSet(ctx, auditActionListKey+string(filter.Action), filter)
	} else if filter.Resource != "" && filter.ResourceID != "" {
		entryIDs, err = r.getFromSortedSet(ctx, auditResourceListKey+filter.Resource+":"+filter.ResourceID, filter)
	} else {
		entryIDs, err = r.getFromSortedSet(ctx, auditListKey, filter)
	}

	if err != nil {
		return nil, err
	}

	// Fetch entries and apply additional filters
	entries := make([]*entity.AuditEntry, 0, len(entryIDs))
	for _, id := range entryIDs {
		entry, err := r.GetByID(ctx, id)
		if err != nil {
			continue
		}

		// Apply filters
		if filter.UserID != "" && entry.UserID != filter.UserID {
			continue
		}
		if filter.Action != "" && entry.Action != filter.Action {
			continue
		}
		if filter.Resource != "" && entry.Resource != filter.Resource {
			continue
		}
		if filter.ResourceID != "" && entry.ResourceID != filter.ResourceID {
			continue
		}
		if filter.Success != nil && entry.Success != *filter.Success {
			continue
		}
		if filter.StartTime != nil && entry.Timestamp.Before(*filter.StartTime) {
			continue
		}
		if filter.EndTime != nil && entry.Timestamp.After(*filter.EndTime) {
			continue
		}

		entries = append(entries, entry)
	}

	// Sort by timestamp descending
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Timestamp.After(entries[j].Timestamp)
	})

	// Apply offset and limit
	if filter.Offset > 0 {
		if filter.Offset >= len(entries) {
			return []*entity.AuditEntry{}, nil
		}
		entries = entries[filter.Offset:]
	}

	if filter.Limit > 0 && len(entries) > filter.Limit {
		entries = entries[:filter.Limit]
	}

	return entries, nil
}

// getFromSortedSet retrieves entry IDs from a sorted set.
func (r *RedisAuditRepository) getFromSortedSet(ctx context.Context, key string, filter entity.AuditFilter) ([]string, error) {
	var start, end float64 = 0, float64(time.Now().UnixNano())

	if filter.StartTime != nil {
		start = float64(filter.StartTime.UnixNano())
	}
	if filter.EndTime != nil {
		end = float64(filter.EndTime.UnixNano())
	}

	// Get from sorted set by score (timestamp) range
	return r.client.ZRangeByScore(ctx, key, &goredis.ZRangeBy{
		Min: strconv.FormatFloat(start, 'f', -1, 64),
		Max: strconv.FormatFloat(end, 'f', -1, 64),
	})
}

// Count returns the count of audit entries matching the filter.
func (r *RedisAuditRepository) Count(ctx context.Context, filter entity.AuditFilter) (int64, error) {
	// For simplicity, we query and count
	// In production, you might want to use ZCount for better performance
	entries, err := r.Query(ctx, entity.AuditFilter{
		UserID:     filter.UserID,
		Action:     filter.Action,
		Resource:   filter.Resource,
		ResourceID: filter.ResourceID,
		Success:    filter.Success,
		StartTime:  filter.StartTime,
		EndTime:    filter.EndTime,
		Limit:      0, // No limit for counting
	})
	if err != nil {
		return 0, err
	}
	return int64(len(entries)), nil
}

// DeleteBefore removes audit entries older than a given time.
func (r *RedisAuditRepository) DeleteBefore(ctx context.Context, before time.Time) (int64, error) {
	timestamp := float64(before.UnixNano())

	// Get entries to delete
	entryIDs, err := r.client.ZRangeByScore(ctx, auditListKey, &goredis.ZRangeBy{
		Min: "0",
		Max: strconv.FormatFloat(timestamp, 'f', -1, 64),
	})
	if err != nil {
		return 0, err
	}

	if len(entryIDs) == 0 {
		return 0, nil
	}

	// Delete entries
	pipe := r.client.Pipeline()
	for _, id := range entryIDs {
		entry, _ := r.GetByID(ctx, id)
		if entry != nil {
			// Remove from indexes
			pipe.ZRem(ctx, auditListKey, id)
			if entry.UserID != "" {
				pipe.ZRem(ctx, auditUserListKey+entry.UserID, id)
			}
			pipe.ZRem(ctx, auditActionListKey+string(entry.Action), id)
			if entry.Resource != "" {
				pipe.ZRem(ctx, auditResourceListKey+entry.Resource+":"+entry.ResourceID, id)
			}
		}
		pipe.Del(ctx, auditKeyPrefix+id)
	}

	_, err = pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}

	return int64(len(entryIDs)), nil
}

// Ensure interface compliance
var _ repository.AuditRepository = (*RedisAuditRepository)(nil)
