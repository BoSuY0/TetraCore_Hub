// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// Repository errors
var (
	ErrClientNotFound = errors.New("client not found")
	ErrTaskNotFound   = errors.New("task not found")
	ErrSessionNotFound = errors.New("session not found")
)

// ClientRepository defines the interface for client data access.
type ClientRepository interface {
	// Save stores a client.
	Save(ctx context.Context, client *entity.Client) error

	// Get retrieves a client by ID.
	Get(ctx context.Context, clientID string) (*entity.Client, error)

	// GetAll retrieves all clients.
	GetAll(ctx context.Context) ([]*entity.Client, error)

	// GetByType retrieves clients by type.
	GetByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error)

	// GetConnected retrieves all connected clients.
	GetConnected(ctx context.Context) ([]*entity.Client, error)

	// GetAvailableWorkers retrieves available workers for task assignment.
	GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error)

	// Delete removes a client.
	Delete(ctx context.Context, clientID string) error

	// UpdateStatus updates a client's connection status.
	UpdateStatus(ctx context.Context, clientID string, status entity.ConnectionStatus) error

	// UpdateWorkerStatus updates a worker's operational status.
	UpdateWorkerStatus(ctx context.Context, clientID string, status entity.WorkerStatus) error

	// IncrementTaskCount increments the task count for a client.
	IncrementTaskCount(ctx context.Context, clientID string, status entity.TaskStatus) error

	// SetActiveTask marks a task as active for a client.
	SetActiveTask(ctx context.Context, clientID, taskID string) error

	// RemoveActiveTask removes a task from client's active tasks.
	RemoveActiveTask(ctx context.Context, clientID, taskID string) error

	// Count returns the total number of clients.
	Count(ctx context.Context) (int64, error)

	// CountByType returns the count of clients by type.
	CountByType(ctx context.Context, clientType entity.ClientType) (int64, error)

	// Exists checks if a client exists.
	Exists(ctx context.Context, clientID string) (bool, error)
}
