// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"time"

	"github.com/google/uuid"
)

// DLQReason represents the reason a task was moved to DLQ.
type DLQReason string

const (
	DLQReasonMaxRetries  DLQReason = "max_retries_exceeded"
	DLQReasonTimeout     DLQReason = "timeout"
	DLQReasonFatalError  DLQReason = "fatal_error"
	DLQReasonManual      DLQReason = "manual"
	DLQReasonInvalidData DLQReason = "invalid_data"
	DLQReasonNoWorker    DLQReason = "no_worker_available"
)

// DLQEntry represents an entry in the dead letter queue.
type DLQEntry struct {
	ID            string         `json:"id"`
	TaskID        string         `json:"task_id"`
	TaskType      TaskType       `json:"task_type"`
	TaskData      map[string]any `json:"task_data"`
	Priority      TaskPriority   `json:"priority"`
	ExecutorType  ExecutorType   `json:"executor_type"`
	OriginalTask  map[string]any `json:"original_task,omitempty"`
	Reason        DLQReason      `json:"reason"`
	ErrorMessage  string         `json:"error_message"`
	ErrorTrace    string         `json:"error_trace,omitempty"`
	RetryCount    int            `json:"retry_count"`
	MaxRetries    int            `json:"max_retries"`
	LastWorkerID  string         `json:"last_worker_id,omitempty"`
	ClientID      string         `json:"client_id,omitempty"`
	CorrelationID string         `json:"correlation_id,omitempty"`
	CreatedAt     time.Time      `json:"created_at"`
	FailedAt      time.Time      `json:"failed_at"`
	ExpiresAt     *time.Time     `json:"expires_at,omitempty"`
	Metadata      map[string]any `json:"metadata"`
}

// NewDLQEntry creates a new DLQ entry from a failed task.
func NewDLQEntry(task *Task, reason DLQReason, errorMessage, errorTrace string) *DLQEntry {
	return &DLQEntry{
		ID:            uuid.New().String(),
		TaskID:        task.TaskID,
		TaskType:      task.TaskType,
		TaskData:      task.Data,
		Priority:      task.Priority,
		ExecutorType:  task.ExecutorType,
		OriginalTask:  task.ToStorage(),
		Reason:        reason,
		ErrorMessage:  errorMessage,
		ErrorTrace:    errorTrace,
		RetryCount:    task.Context.CurrentAttempt,
		MaxRetries:    task.MaxRetries,
		LastWorkerID:  task.Context.WorkerID,
		ClientID:      task.Context.ClientID,
		CorrelationID: task.Context.CorrelationID,
		CreatedAt:     task.Context.CreatedAt,
		FailedAt:      time.Now().UTC(),
		Metadata:      make(map[string]any),
	}
}

// ToTask converts the DLQ entry back to a task for retry.
func (e *DLQEntry) ToTask() *Task {
	task := NewTask(e.TaskType, e.TaskData)
	task.TaskID = e.TaskID
	task.Priority = e.Priority
	task.ExecutorType = e.ExecutorType
	task.Context.ClientID = e.ClientID
	task.Context.CorrelationID = e.CorrelationID
	task.Context.CurrentAttempt = 1 // Reset attempt count for retry
	return task
}

// IsExpired checks if the DLQ entry has expired.
func (e *DLQEntry) IsExpired() bool {
	if e.ExpiresAt != nil {
		return time.Now().UTC().After(*e.ExpiresAt)
	}
	return false
}

// SetExpiration sets the expiration time.
func (e *DLQEntry) SetExpiration(expiresInSeconds int) {
	expireTime := time.Now().UTC().Add(time.Duration(expiresInSeconds) * time.Second)
	e.ExpiresAt = &expireTime
}

// ToMap converts the DLQ entry to a map.
func (e *DLQEntry) ToMap() map[string]any {
	var expiresAt *string
	if e.ExpiresAt != nil {
		s := e.ExpiresAt.Format(time.RFC3339)
		expiresAt = &s
	}

	return map[string]any{
		"id":             e.ID,
		"task_id":        e.TaskID,
		"task_type":      string(e.TaskType),
		"priority":       string(e.Priority),
		"executor_type":  string(e.ExecutorType),
		"reason":         string(e.Reason),
		"error_message":  e.ErrorMessage,
		"error_trace":    e.ErrorTrace,
		"retry_count":    e.RetryCount,
		"max_retries":    e.MaxRetries,
		"last_worker_id": e.LastWorkerID,
		"client_id":      e.ClientID,
		"created_at":     e.CreatedAt.Format(time.RFC3339),
		"failed_at":      e.FailedAt.Format(time.RFC3339),
		"expires_at":     expiresAt,
		"is_expired":     e.IsExpired(),
		"metadata":       e.Metadata,
	}
}

// DLQStats represents DLQ statistics.
type DLQStats struct {
	TotalEntries     int            `json:"total_entries"`
	EntriesByReason  map[string]int `json:"entries_by_reason"`
	EntriesByType    map[string]int `json:"entries_by_type"`
	OldestEntry      *time.Time     `json:"oldest_entry,omitempty"`
	NewestEntry      *time.Time     `json:"newest_entry,omitempty"`
	ExpiredCount     int            `json:"expired_count"`
	RetryableCount   int            `json:"retryable_count"`
	AverageRetries   float64        `json:"average_retries"`
	TotalStorageSize int64          `json:"total_storage_size"`
}

// NewDLQStats creates new empty DLQ stats.
func NewDLQStats() *DLQStats {
	return &DLQStats{
		EntriesByReason: make(map[string]int),
		EntriesByType:   make(map[string]int),
	}
}
