// Package client provides client management use cases for TetraCore Hub.
package client

import (
	"context"
	"sort"
	"sync"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds client management configuration.
type Config struct {
	HeartbeatTimeout    time.Duration
	CleanupInterval     time.Duration
	MaxClientsPerType   int
	AllowReconnect      bool
	ReconnectGracePeriod time.Duration
}

// UseCase handles client management operations.
type UseCase struct {
	clientRepo repository.ClientRepository
	config     Config
	log        logger.LogFields

	// In-memory connection tracking
	connections   map[string]*ConnectionInfo
	connectionsMu sync.RWMutex
}

// ConnectionInfo tracks WebSocket connection state.
type ConnectionInfo struct {
	ClientID      string
	ConnectedAt   time.Time
	LastHeartbeat time.Time
	MessageCount  int64
	BytesSent     int64
	BytesReceived int64
}

// NewUseCase creates a new client use case.
func NewUseCase(clientRepo repository.ClientRepository, config Config) *UseCase {
	return &UseCase{
		clientRepo:  clientRepo,
		config:      config,
		log:         logger.LogFields{"component": "client-usecase"},
		connections: make(map[string]*ConnectionInfo),
	}
}

// RegisterInput represents client registration data.
type RegisterInput struct {
	ClientID     string
	ClientType   entity.ClientType
	Name         string
	Version      string
	Capabilities *entity.WorkerCapabilities
	Metadata     map[string]any
}

// RegisterClient registers a new client or updates an existing one.
func (uc *UseCase) RegisterClient(ctx context.Context, input RegisterInput) (*entity.Client, error) {
	log := logger.WithFields(uc.log).With("client_id", input.ClientID, "type", input.ClientType)

	// Check if client already exists
	existing, err := uc.clientRepo.Get(ctx, input.ClientID)
	if err == nil && existing != nil {
		// Client exists - handle reconnection
		if !uc.config.AllowReconnect {
			return nil, errors.ErrConflict.With("client already registered")
		}

		// Update existing client
		existing.Info.ConnectionStatus = entity.ConnectionStatusConnected
		existing.Info.LastSeen = time.Now().UTC()
		existing.Info.ReconnectCount++

		if input.Capabilities != nil {
			existing.Info.Capabilities = input.Capabilities
		}

		if err := uc.clientRepo.Save(ctx, existing); err != nil {
			log.Error().Err(err).Msg("Failed to update existing client")
			return nil, errors.ErrInternalServer.Wrap(err, "failed to update client")
		}

		uc.trackConnection(input.ClientID)
		log.Info().Msg("Client reconnected")
		return existing, nil
	}

	// Create new client
	client := entity.NewClient(input.ClientID, input.ClientType, input.Name, input.Version)
	if input.Capabilities != nil {
		client.Info.Capabilities = input.Capabilities
	}
	if input.Metadata != nil {
		client.Info.Metadata = input.Metadata
	}

	// Set initial status based on type
	if input.ClientType == entity.ClientTypeWorker || input.ClientType == entity.ClientTypeWorkerAPI {
		status := entity.WorkerStatusIdle
		client.Info.WorkerStatus = &status
	}

	if err := uc.clientRepo.Save(ctx, client); err != nil {
		log.Error().Err(err).Msg("Failed to save client")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to save client")
	}

	uc.trackConnection(input.ClientID)
	log.Info().Msg("Client registered")

	return client, nil
}

// trackConnection adds connection to in-memory tracking.
func (uc *UseCase) trackConnection(clientID string) {
	uc.connectionsMu.Lock()
	defer uc.connectionsMu.Unlock()

	uc.connections[clientID] = &ConnectionInfo{
		ClientID:      clientID,
		ConnectedAt:   time.Now().UTC(),
		LastHeartbeat: time.Now().UTC(),
	}
}

// DisconnectClient handles client disconnection.
func (uc *UseCase) DisconnectClient(ctx context.Context, clientID string, reason string) error {
	log := logger.WithFields(uc.log).With("client_id", clientID, "reason", reason)

	client, err := uc.clientRepo.Get(ctx, clientID)
	if err != nil {
		return errors.ErrNotFound.With("client not found")
	}

	client.Info.ConnectionStatus = entity.ConnectionStatusDisconnected
	client.Info.LastSeen = time.Now().UTC()
	client.Info.DisconnectReason = reason

	if err := uc.clientRepo.Save(ctx, client); err != nil {
		log.Error().Err(err).Msg("Failed to update client status")
		return errors.ErrInternalServer.Wrap(err, "failed to update client")
	}

	// Remove from connection tracking
	uc.connectionsMu.Lock()
	delete(uc.connections, clientID)
	uc.connectionsMu.Unlock()

	log.Info().Msg("Client disconnected")
	return nil
}

// GetClient retrieves a client by ID.
func (uc *UseCase) GetClient(ctx context.Context, clientID string) (*entity.Client, error) {
	client, err := uc.clientRepo.Get(ctx, clientID)
	if err != nil {
		return nil, errors.ErrNotFound.With("client not found")
	}
	return client, nil
}

// GetAllClients retrieves all clients.
func (uc *UseCase) GetAllClients(ctx context.Context) ([]*entity.Client, error) {
	return uc.clientRepo.GetAll(ctx)
}

// GetClientsByType retrieves clients by type.
func (uc *UseCase) GetClientsByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error) {
	return uc.clientRepo.GetByType(ctx, clientType)
}

// GetConnectedClients retrieves all connected clients.
func (uc *UseCase) GetConnectedClients(ctx context.Context) ([]*entity.Client, error) {
	return uc.clientRepo.GetConnected(ctx)
}

// GetAvailableWorkers retrieves workers that can handle a task type.
func (uc *UseCase) GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error) {
	workers, err := uc.clientRepo.GetAvailableWorkers(ctx, taskType)
	if err != nil {
		return nil, err
	}

	// Sort by load (lowest first) for load balancing
	sort.Slice(workers, func(i, j int) bool {
		loadI := workers[i].Info.GetCurrentLoad()
		loadJ := workers[j].Info.GetCurrentLoad()
		return loadI < loadJ
	})

	return workers, nil
}

// SelectWorker selects the best worker for a task.
func (uc *UseCase) SelectWorker(ctx context.Context, taskType string, priority entity.TaskPriority) (*entity.Client, error) {
	workers, err := uc.GetAvailableWorkers(ctx, taskType)
	if err != nil {
		return nil, err
	}

	if len(workers) == 0 {
		return nil, errors.ErrNotFound.With("no available workers")
	}

	// For critical/high priority, prefer workers with lower load
	// For normal/low priority, simple round-robin is fine
	if priority == entity.TaskPriorityCritical || priority == entity.TaskPriorityHigh {
		// Already sorted by load, return lowest
		return workers[0], nil
	}

	// Return first available worker
	return workers[0], nil
}

// UpdateWorkerStatus updates a worker's operational status.
func (uc *UseCase) UpdateWorkerStatus(ctx context.Context, clientID string, status entity.WorkerStatus) error {
	log := logger.WithFields(uc.log).With("client_id", clientID, "status", status)

	if err := uc.clientRepo.UpdateWorkerStatus(ctx, clientID, status); err != nil {
		log.Error().Err(err).Msg("Failed to update worker status")
		return errors.ErrInternalServer.Wrap(err, "failed to update status")
	}

	log.Debug().Msg("Worker status updated")
	return nil
}

// ProcessHeartbeat updates client's last seen timestamp.
func (uc *UseCase) ProcessHeartbeat(ctx context.Context, clientID string, metrics map[string]any) error {
	client, err := uc.clientRepo.Get(ctx, clientID)
	if err != nil {
		return errors.ErrNotFound.With("client not found")
	}

	client.Info.LastSeen = time.Now().UTC()
	if metrics != nil {
		client.Info.Metrics = metrics
	}

	if err := uc.clientRepo.Save(ctx, client); err != nil {
		return errors.ErrInternalServer.Wrap(err, "failed to update client")
	}

	// Update connection tracking
	uc.connectionsMu.Lock()
	if conn, ok := uc.connections[clientID]; ok {
		conn.LastHeartbeat = time.Now().UTC()
	}
	uc.connectionsMu.Unlock()

	return nil
}

// IncrementTaskCount updates task statistics for a client.
func (uc *UseCase) IncrementTaskCount(ctx context.Context, clientID string, status entity.TaskStatus) error {
	return uc.clientRepo.IncrementTaskCount(ctx, clientID, status)
}

// SetActiveTask marks a task as active for a client.
func (uc *UseCase) SetActiveTask(ctx context.Context, clientID, taskID string) error {
	return uc.clientRepo.SetActiveTask(ctx, clientID, taskID)
}

// RemoveActiveTask removes a task from client's active tasks.
func (uc *UseCase) RemoveActiveTask(ctx context.Context, clientID, taskID string) error {
	return uc.clientRepo.RemoveActiveTask(ctx, clientID, taskID)
}

// GetClientCount returns the total number of clients.
func (uc *UseCase) GetClientCount(ctx context.Context) (int64, error) {
	return uc.clientRepo.Count(ctx)
}

// GetClientCountByType returns client count by type.
func (uc *UseCase) GetClientCountByType(ctx context.Context, clientType entity.ClientType) (int64, error) {
	return uc.clientRepo.CountByType(ctx, clientType)
}

// GetConnectionInfo returns in-memory connection info.
func (uc *UseCase) GetConnectionInfo(clientID string) *ConnectionInfo {
	uc.connectionsMu.RLock()
	defer uc.connectionsMu.RUnlock()
	return uc.connections[clientID]
}

// GetAllConnectionInfo returns all connection info.
func (uc *UseCase) GetAllConnectionInfo() map[string]*ConnectionInfo {
	uc.connectionsMu.RLock()
	defer uc.connectionsMu.RUnlock()

	result := make(map[string]*ConnectionInfo)
	for k, v := range uc.connections {
		result[k] = v
	}
	return result
}

// UpdateMessageStats updates message statistics for a connection.
func (uc *UseCase) UpdateMessageStats(clientID string, bytesSent, bytesReceived int64) {
	uc.connectionsMu.Lock()
	defer uc.connectionsMu.Unlock()

	if conn, ok := uc.connections[clientID]; ok {
		conn.MessageCount++
		conn.BytesSent += bytesSent
		conn.BytesReceived += bytesReceived
	}
}

// CleanupStaleConnections removes clients that haven't sent heartbeats.
func (uc *UseCase) CleanupStaleConnections(ctx context.Context) (int, error) {
	log := logger.WithFields(uc.log)

	uc.connectionsMu.Lock()
	staleClients := make([]string, 0)
	cutoff := time.Now().Add(-uc.config.HeartbeatTimeout)

	for clientID, conn := range uc.connections {
		if conn.LastHeartbeat.Before(cutoff) {
			staleClients = append(staleClients, clientID)
		}
	}
	uc.connectionsMu.Unlock()

	for _, clientID := range staleClients {
		if err := uc.DisconnectClient(ctx, clientID, "heartbeat_timeout"); err != nil {
			log.Warn().Str("client_id", clientID).Err(err).Msg("Failed to disconnect stale client")
		}
	}

	if len(staleClients) > 0 {
		log.Info().Int("count", len(staleClients)).Msg("Cleaned up stale connections")
	}

	return len(staleClients), nil
}

// DeleteClient permanently removes a client.
func (uc *UseCase) DeleteClient(ctx context.Context, clientID string) error {
	log := logger.WithFields(uc.log).With("client_id", clientID)

	if err := uc.clientRepo.Delete(ctx, clientID); err != nil {
		log.Error().Err(err).Msg("Failed to delete client")
		return errors.ErrInternalServer.Wrap(err, "failed to delete client")
	}

	// Remove from connection tracking
	uc.connectionsMu.Lock()
	delete(uc.connections, clientID)
	uc.connectionsMu.Unlock()

	log.Info().Msg("Client deleted")
	return nil
}

// GetStats returns client statistics.
func (uc *UseCase) GetStats(ctx context.Context) (*ClientStats, error) {
	total, _ := uc.clientRepo.Count(ctx)
	bots, _ := uc.clientRepo.CountByType(ctx, entity.ClientTypeBot)
	workers, _ := uc.clientRepo.CountByType(ctx, entity.ClientTypeWorker)
	workerAPIs, _ := uc.clientRepo.CountByType(ctx, entity.ClientTypeWorkerAPI)
	monitors, _ := uc.clientRepo.CountByType(ctx, entity.ClientTypeMonitor)
	admins, _ := uc.clientRepo.CountByType(ctx, entity.ClientTypeAdmin)

	connected, _ := uc.clientRepo.GetConnected(ctx)

	return &ClientStats{
		Total:        total,
		Bots:         bots,
		Workers:      workers,
		WorkerAPIs:   workerAPIs,
		Monitors:     monitors,
		Admins:       admins,
		Connected:    int64(len(connected)),
		Disconnected: total - int64(len(connected)),
	}, nil
}

// ClientStats holds aggregated client statistics.
type ClientStats struct {
	Total        int64 `json:"total"`
	Bots         int64 `json:"bots"`
	Workers      int64 `json:"workers"`
	WorkerAPIs   int64 `json:"worker_apis"`
	Monitors     int64 `json:"monitors"`
	Admins       int64 `json:"admins"`
	Connected    int64 `json:"connected"`
	Disconnected int64 `json:"disconnected"`
}
