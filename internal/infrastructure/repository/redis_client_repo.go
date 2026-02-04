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
	clientKeyPrefix    = "client:"
	clientSetKey       = "clients"
	clientTypeSetKey   = "clients:type:"
	connectedSetKey    = "clients:connected"
	activeTasksKey     = "client:tasks:"
)

// RedisClientRepository implements ClientRepository using Redis.
type RedisClientRepository struct {
	client *redis.Client
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisClientRepository creates a new Redis client repository.
func NewRedisClientRepository(client *redis.Client, ttl time.Duration) *RedisClientRepository {
	return &RedisClientRepository{
		client: client,
		ttl:    ttl,
		log:    logger.LogFields{"component": "redis-client-repo"},
	}
}

// Save stores a client.
func (r *RedisClientRepository) Save(ctx context.Context, client *entity.Client) error {
	data, err := json.Marshal(client)
	if err != nil {
		return fmt.Errorf("failed to marshal client: %w", err)
	}

	key := clientKeyPrefix + client.Info.ClientID

	// Use pipeline for atomic operations
	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)
	pipe.SAdd(ctx, clientSetKey, client.Info.ClientID)
	pipe.SAdd(ctx, clientTypeSetKey+string(client.Info.ClientType), client.Info.ClientID)

	if client.Info.IsConnected() {
		pipe.SAdd(ctx, connectedSetKey, client.Info.ClientID)
	} else {
		pipe.SRem(ctx, connectedSetKey, client.Info.ClientID)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a client by ID.
func (r *RedisClientRepository) Get(ctx context.Context, clientID string) (*entity.Client, error) {
	key := clientKeyPrefix + clientID
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, repository.ErrClientNotFound
	}

	var client entity.Client
	if err := json.Unmarshal([]byte(data), &client); err != nil {
		return nil, fmt.Errorf("failed to unmarshal client: %w", err)
	}

	return &client, nil
}

// GetAll retrieves all clients.
func (r *RedisClientRepository) GetAll(ctx context.Context) ([]*entity.Client, error) {
	clientIDs, err := r.client.SMembers(ctx, clientSetKey)
	if err != nil {
		return nil, err
	}

	clients := make([]*entity.Client, 0, len(clientIDs))
	for _, id := range clientIDs {
		client, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		clients = append(clients, client)
	}

	return clients, nil
}

// GetByType retrieves clients by type.
func (r *RedisClientRepository) GetByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error) {
	clientIDs, err := r.client.SMembers(ctx, clientTypeSetKey+string(clientType))
	if err != nil {
		return nil, err
	}

	clients := make([]*entity.Client, 0, len(clientIDs))
	for _, id := range clientIDs {
		client, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		clients = append(clients, client)
	}

	return clients, nil
}

// GetConnected retrieves all connected clients.
func (r *RedisClientRepository) GetConnected(ctx context.Context) ([]*entity.Client, error) {
	clientIDs, err := r.client.SMembers(ctx, connectedSetKey)
	if err != nil {
		return nil, err
	}

	clients := make([]*entity.Client, 0, len(clientIDs))
	for _, id := range clientIDs {
		client, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		clients = append(clients, client)
	}

	return clients, nil
}

// GetAvailableWorkers retrieves available workers for task assignment.
func (r *RedisClientRepository) GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error) {
	// Зберігаємо попередню поведінку: "worker" включає і worker_api.
	return r.GetAvailableExecutors(ctx, entity.ExecutorTypeWorker, taskType)
}

// GetAvailableExecutors retrieves available executors for task assignment.
func (r *RedisClientRepository) GetAvailableExecutors(ctx context.Context, executorType entity.ExecutorType, taskType string) ([]*entity.Client, error) {
	var clientTypes []entity.ClientType
	switch executorType {
	case entity.ExecutorTypeBot:
		clientTypes = []entity.ClientType{entity.ClientTypeBot}
	case entity.ExecutorTypeWorkerAPI:
		clientTypes = []entity.ClientType{entity.ClientTypeWorkerAPI}
	case entity.ExecutorTypeWorker:
		// Backward-compatible: "worker" може бути і worker_api.
		clientTypes = []entity.ClientType{entity.ClientTypeWorker, entity.ClientTypeWorkerAPI}
	default:
		// Безпечний дефолт: трактуємо як "worker".
		clientTypes = []entity.ClientType{entity.ClientTypeWorker, entity.ClientTypeWorkerAPI}
	}

	// Отримуємо ids кандидатів за типами клієнтів.
	candidateSet := make(map[string]struct{})
	for _, ct := range clientTypes {
		ids, err := r.client.SMembers(ctx, clientTypeSetKey+string(ct))
		if err != nil {
			return nil, err
		}
		for _, id := range ids {
			candidateSet[id] = struct{}{}
		}
	}

	// Підмножина підключених клієнтів.
	connectedIDs, err := r.client.SMembers(ctx, connectedSetKey)
	if err != nil {
		return nil, err
	}
	connectedSet := make(map[string]struct{}, len(connectedIDs))
	for _, id := range connectedIDs {
		connectedSet[id] = struct{}{}
	}

	candidates := make([]string, 0, len(candidateSet))
	for id := range candidateSet {
		if _, ok := connectedSet[id]; ok {
			candidates = append(candidates, id)
		}
	}

	// Отримуємо кількість активних задач по кожному кандидату через pipeline.
	pipe := r.client.Pipeline()
	activeCmds := make(map[string]*goredis.IntCmd, len(candidates))
	for _, id := range candidates {
		activeCmds[id] = pipe.SCard(ctx, activeTasksKey+id)
	}
	if _, err := pipe.Exec(ctx); err != nil {
		return nil, err
	}

	available := make([]*entity.Client, 0)
	for _, id := range candidates {
		client, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		if client.Info == nil {
			continue
		}
		if client.Info.Stats == nil {
			client.Info.Stats = entity.NewClientStats()
		}

		if cmd, ok := activeCmds[id]; ok {
			client.Info.Stats.ActiveTasks = int(cmd.Val())
			client.Info.CurrentLoad = client.Info.Stats.ActiveTasks
		}

		// Перевірка: чи може виконувати цей тип задачі і чи є доступним.
		if client.Info.CanHandleTask(taskType) && client.Info.IsAvailable() {
			available = append(available, client)
		}
	}

	return available, nil
}

// Delete removes a client.
func (r *RedisClientRepository) Delete(ctx context.Context, clientID string) error {
	client, err := r.Get(ctx, clientID)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, clientKeyPrefix+clientID)
	pipe.SRem(ctx, clientSetKey, clientID)
	pipe.SRem(ctx, clientTypeSetKey+string(client.Info.ClientType), clientID)
	pipe.SRem(ctx, connectedSetKey, clientID)
	pipe.Del(ctx, activeTasksKey+clientID)

	_, err = pipe.Exec(ctx)
	return err
}

// UpdateStatus updates a client's connection status.
func (r *RedisClientRepository) UpdateStatus(ctx context.Context, clientID string, status entity.ConnectionStatus) error {
	client, err := r.Get(ctx, clientID)
	if err != nil {
		return err
	}

	client.Info.ConnectionStatus = status

	if status == entity.ConnectionStatusConnected {
		r.client.SAdd(ctx, connectedSetKey, clientID)
	} else {
		r.client.SRem(ctx, connectedSetKey, clientID)
	}

	return r.Save(ctx, client)
}

// UpdateWorkerStatus updates a worker's operational status.
func (r *RedisClientRepository) UpdateWorkerStatus(ctx context.Context, clientID string, status entity.WorkerStatus) error {
	client, err := r.Get(ctx, clientID)
	if err != nil {
		return err
	}

	client.Info.WorkerStatus = &status
	return r.Save(ctx, client)
}

// IncrementTaskCount increments the task count for a client.
func (r *RedisClientRepository) IncrementTaskCount(ctx context.Context, clientID string, status entity.TaskStatus) error {
	client, err := r.Get(ctx, clientID)
	if err != nil {
		return err
	}

	client.Info.Stats.TotalTasks++
	switch status {
	case entity.TaskStatusCompleted:
		client.Info.Stats.SuccessfulTasks++
	case entity.TaskStatusFailed:
		client.Info.Stats.FailedTasks++
	case entity.TaskStatusTimeout:
		client.Info.Stats.TimeoutTasks++
	}

	return r.Save(ctx, client)
}

// SetActiveTask marks a task as active for a client.
func (r *RedisClientRepository) SetActiveTask(ctx context.Context, clientID, taskID string) error {
	return r.client.SAdd(ctx, activeTasksKey+clientID, taskID)
}

// RemoveActiveTask removes a task from client's active tasks.
func (r *RedisClientRepository) RemoveActiveTask(ctx context.Context, clientID, taskID string) error {
	return r.client.SRem(ctx, activeTasksKey+clientID, taskID)
}

// ClearActiveTasks clears the active task tracking set for a client.
func (r *RedisClientRepository) ClearActiveTasks(ctx context.Context, clientID string) error {
	return r.client.Del(ctx, activeTasksKey+clientID)
}

// Count returns the total number of clients.
func (r *RedisClientRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, clientSetKey)
}

// CountByType returns the count of clients by type.
func (r *RedisClientRepository) CountByType(ctx context.Context, clientType entity.ClientType) (int64, error) {
	return r.client.SCard(ctx, clientTypeSetKey+string(clientType))
}

// Exists checks if a client exists.
func (r *RedisClientRepository) Exists(ctx context.Context, clientID string) (bool, error) {
	exists, err := r.client.Exists(ctx, clientKeyPrefix+clientID)
	return exists > 0, err
}

// Repository errors
var (
	ErrClientNotFound = fmt.Errorf("client not found")
)

// Ensure interface compliance
var _ repository.ClientRepository = (*RedisClientRepository)(nil)
