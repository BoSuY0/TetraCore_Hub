// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"fmt"
	"time"

	"github.com/google/uuid"
)

// TaskType represents the type of task in the system.
type TaskType string

const (
	TaskTypeAPIRequest      TaskType = "api_request"
	TaskTypeDataProcessing  TaskType = "data_processing"
	TaskTypeFileUpload      TaskType = "file_upload"
	TaskTypeEmailSend       TaskType = "email_send"
	TaskTypeNotification    TaskType = "notification"
	TaskTypeWebhook         TaskType = "webhook"
	TaskTypeCalculation     TaskType = "calculation"
	TaskTypeSendMessage     TaskType = "send_message"
	TaskTypeCustom          TaskType = "custom"
	TaskTypeWorkerTask      TaskType = "worker_task"
)

// ExecutorType represents the type of task executor.
type ExecutorType string

const (
	ExecutorTypeBot       ExecutorType = "bot"
	ExecutorTypeWorker    ExecutorType = "worker"
	ExecutorTypeWorkerAPI ExecutorType = "worker_api"
)

// TaskStatus represents the status of a task.
type TaskStatus string

const (
	TaskStatusPending    TaskStatus = "pending"
	TaskStatusAssigned   TaskStatus = "assigned"
	TaskStatusProcessing TaskStatus = "processing"
	TaskStatusCompleted  TaskStatus = "completed"
	TaskStatusFailed     TaskStatus = "failed"
	TaskStatusTimeout    TaskStatus = "timeout"
	TaskStatusRetry      TaskStatus = "retry"
	TaskStatusCancelled  TaskStatus = "cancelled"
)

// IsTerminal returns true if the status is a terminal state.
func (s TaskStatus) IsTerminal() bool {
	return s == TaskStatusCompleted || s == TaskStatusFailed ||
		s == TaskStatusTimeout || s == TaskStatusCancelled
}

// TaskPriority represents the priority of a task.
type TaskPriority string

const (
	TaskPriorityLow      TaskPriority = "low"
	TaskPriorityNormal   TaskPriority = "normal"
	TaskPriorityHigh     TaskPriority = "high"
	TaskPriorityCritical TaskPriority = "critical"
)

// Score returns a numeric score for priority sorting.
func (p TaskPriority) Score() int {
	switch p {
	case TaskPriorityLow:
		return 1
	case TaskPriorityNormal:
		return 2
	case TaskPriorityHigh:
		return 3
	case TaskPriorityCritical:
		return 4
	default:
		return 2
	}
}

// StatusHistoryEntry represents a single status change entry.
type StatusHistoryEntry struct {
	FromStatus TaskStatus `json:"from_status"`
	ToStatus   TaskStatus `json:"to_status"`
	Timestamp  time.Time  `json:"timestamp"`
	Message    string     `json:"message,omitempty"`
}

// AttemptHistoryEntry represents a single task attempt.
type AttemptHistoryEntry struct {
	Attempt   int       `json:"attempt"`
	WorkerID  string    `json:"worker_id"`
	StartedAt time.Time `json:"started_at"`
	Error     string    `json:"error,omitempty"`
}

// TaskError represents an error that occurred during task execution.
type TaskErrorEntry struct {
	ErrorType    string    `json:"error_type"`
	ErrorMessage string    `json:"error_message"`
	ErrorTrace   string    `json:"error_trace,omitempty"`
	Timestamp    time.Time `json:"timestamp"`
	Attempt      int       `json:"attempt"`
}

// TaskMetadata contains task metadata and categorization info.
type TaskMetadata struct {
	Source            string         `json:"source"`
	Version           string         `json:"version"`
	Tags              []string       `json:"tags"`
	Group             string         `json:"group,omitempty"`
	ParentTaskID      string         `json:"parent_task_id,omitempty"`
	ChildTaskIDs      []string       `json:"child_task_ids"`
	Dependencies      []string       `json:"dependencies"`
	CreatedBy         string         `json:"created_by,omitempty"`
	CustomMetadata    map[string]any `json:"custom_metadata"`
	IsCritical        bool           `json:"is_critical"`
	IsRetryable       bool           `json:"is_retryable"`
	IsCancellable     bool           `json:"is_cancellable"`
	IdempotencyKey    string         `json:"idempotency_key,omitempty"`
	ExecutionSettings map[string]any `json:"execution_settings"`
}

// NewTaskMetadata creates a new TaskMetadata with defaults.
func NewTaskMetadata() *TaskMetadata {
	return &TaskMetadata{
		Source:            "unknown",
		Version:           "1.0.0",
		Tags:              []string{},
		ChildTaskIDs:      []string{},
		Dependencies:      []string{},
		CustomMetadata:    make(map[string]any),
		IsRetryable:       true,
		IsCancellable:     true,
		ExecutionSettings: make(map[string]any),
	}
}

// TaskContext holds the execution context of a task.
type TaskContext struct {
	TaskID           string                `json:"task_id"`
	WorkerID         string                `json:"worker_id,omitempty"`
	ClientID         string                `json:"client_id,omitempty"`
	CorrelationID    string                `json:"correlation_id,omitempty"`
	CreatedAt        time.Time             `json:"created_at"`
	AssignedAt       *time.Time            `json:"assigned_at,omitempty"`
	StartedAt        *time.Time            `json:"started_at,omitempty"`
	CompletedAt      *time.Time            `json:"completed_at,omitempty"`
	ExpiresAt        *time.Time            `json:"expires_at,omitempty"`
	RetryAt          *time.Time            `json:"retry_at,omitempty"`
	CurrentStatus    TaskStatus            `json:"current_status"`
	StatusHistory    []StatusHistoryEntry  `json:"status_history"`
	CurrentAttempt   int                   `json:"current_attempt"`
	AttemptHistory   []AttemptHistoryEntry `json:"attempt_history"`
	Result           map[string]any        `json:"result,omitempty"`
	Errors           []TaskErrorEntry      `json:"errors"`
	ResourceUsage    map[string]float64    `json:"resource_usage"`
	ExecutionMetrics map[string]any        `json:"execution_metrics"`
}

// NewTaskContext creates a new TaskContext with defaults.
func NewTaskContext(taskID string) *TaskContext {
	return &TaskContext{
		TaskID:           taskID,
		CreatedAt:        time.Now().UTC(),
		CurrentStatus:    TaskStatusPending,
		StatusHistory:    []StatusHistoryEntry{},
		CurrentAttempt:   1,
		AttemptHistory:   []AttemptHistoryEntry{},
		Errors:           []TaskErrorEntry{},
		ResourceUsage:    make(map[string]float64),
		ExecutionMetrics: make(map[string]any),
	}
}

// AddStatusChange records a status change.
func (c *TaskContext) AddStatusChange(newStatus TaskStatus, message string) {
	c.StatusHistory = append(c.StatusHistory, StatusHistoryEntry{
		FromStatus: c.CurrentStatus,
		ToStatus:   newStatus,
		Timestamp:  time.Now().UTC(),
		Message:    message,
	})
	c.CurrentStatus = newStatus
}

// AddAttempt records a new execution attempt.
func (c *TaskContext) AddAttempt(workerID string, errorMsg string) {
	c.AttemptHistory = append(c.AttemptHistory, AttemptHistoryEntry{
		Attempt:   c.CurrentAttempt,
		WorkerID:  workerID,
		StartedAt: time.Now().UTC(),
		Error:     errorMsg,
	})
	c.CurrentAttempt++
}

// AddError records an error.
func (c *TaskContext) AddError(errorType, errorMessage, errorTrace string) {
	c.Errors = append(c.Errors, TaskErrorEntry{
		ErrorType:    errorType,
		ErrorMessage: errorMessage,
		ErrorTrace:   errorTrace,
		Timestamp:    time.Now().UTC(),
		Attempt:      c.CurrentAttempt,
	})
}

// GetExecutionTime returns the execution time in seconds.
func (c *TaskContext) GetExecutionTime() *float64 {
	if c.StartedAt != nil && c.CompletedAt != nil {
		duration := c.CompletedAt.Sub(*c.StartedAt).Seconds()
		return &duration
	}
	return nil
}

// GetTotalTime returns the total time since creation in seconds.
func (c *TaskContext) GetTotalTime() float64 {
	endTime := time.Now().UTC()
	if c.CompletedAt != nil {
		endTime = *c.CompletedAt
	}
	return endTime.Sub(c.CreatedAt).Seconds()
}

// IsExpired checks if the task has expired.
func (c *TaskContext) IsExpired() bool {
	if c.ExpiresAt != nil {
		return time.Now().UTC().After(*c.ExpiresAt)
	}
	return false
}

// IsCompleted checks if the task is in a terminal state.
func (c *TaskContext) IsCompleted() bool {
	return c.CurrentStatus.IsTerminal()
}

// ResetAssignment resets the worker assignment.
func (c *TaskContext) ResetAssignment() {
	c.WorkerID = ""
	c.AssignedAt = nil
	c.StartedAt = nil
	c.AddStatusChange(TaskStatusPending, "Assignment reset due to communication failure")
}

// Task represents a task in the system.
type Task struct {
	TaskID             string        `json:"task_id"`
	TaskType           TaskType      `json:"task_type"`
	Data               map[string]any `json:"data"`
	Priority           TaskPriority  `json:"priority"`
	Timeout            int           `json:"timeout"`
	MaxRetries         int           `json:"max_retries"`
	RetryDelay         int           `json:"retry_delay"`
	ExecutorType       ExecutorType  `json:"executor_type"`
	WorkerRequirements []string      `json:"worker_requirements"`
	Metadata           *TaskMetadata `json:"metadata"`
	Context            *TaskContext  `json:"context"`
}

// NewTask creates a new Task with defaults.
func NewTask(taskType TaskType, data map[string]any) *Task {
	taskID := uuid.New().String()
	return &Task{
		TaskID:             taskID,
		TaskType:           taskType,
		Data:               data,
		Priority:           TaskPriorityNormal,
		Timeout:            300,
		MaxRetries:         3,
		RetryDelay:         5,
		ExecutorType:       ExecutorTypeWorker,
		WorkerRequirements: []string{},
		Metadata:           NewTaskMetadata(),
		Context:            NewTaskContext(taskID),
	}
}

// CreateTask creates a new task with custom options.
func CreateTask(taskType TaskType, data map[string]any, opts ...TaskOption) *Task {
	task := NewTask(taskType, data)
	for _, opt := range opts {
		opt(task)
	}
	return task
}

// TaskOption is a functional option for creating tasks.
type TaskOption func(*Task)

// WithTaskID sets a custom task ID.
func WithTaskID(id string) TaskOption {
	return func(t *Task) {
		t.TaskID = id
		t.Context.TaskID = id
	}
}

// WithPriority sets the task priority.
func WithPriority(priority TaskPriority) TaskOption {
	return func(t *Task) {
		t.Priority = priority
	}
}

// WithTimeout sets the task timeout in seconds.
func WithTimeout(timeout int) TaskOption {
	return func(t *Task) {
		t.Timeout = timeout
	}
}

// WithMaxRetries sets the maximum number of retries.
func WithMaxRetries(retries int) TaskOption {
	return func(t *Task) {
		t.MaxRetries = retries
	}
}

// WithRetryDelay sets the delay between retries in seconds.
func WithRetryDelay(delay int) TaskOption {
	return func(t *Task) {
		t.RetryDelay = delay
	}
}

// WithExecutorType sets the executor type.
func WithExecutorType(execType ExecutorType) TaskOption {
	return func(t *Task) {
		t.ExecutorType = execType
	}
}

// WithWorkerRequirements sets the worker requirements.
func WithWorkerRequirements(requirements []string) TaskOption {
	return func(t *Task) {
		t.WorkerRequirements = requirements
	}
}

// WithIdempotencyKey sets the idempotency key.
func WithIdempotencyKey(key string) TaskOption {
	return func(t *Task) {
		t.Metadata.IdempotencyKey = key
	}
}

// WithClientID sets the client ID in context.
func WithClientID(clientID string) TaskOption {
	return func(t *Task) {
		t.Context.ClientID = clientID
	}
}

// WithCorrelationID sets the correlation ID.
func WithCorrelationID(correlationID string) TaskOption {
	return func(t *Task) {
		t.Context.CorrelationID = correlationID
	}
}

// AssignToWorker assigns the task to a worker.
func (t *Task) AssignToWorker(workerID string) {
	t.Context.WorkerID = workerID
	now := time.Now().UTC()
	t.Context.AssignedAt = &now
	t.Context.AddStatusChange(TaskStatusAssigned, "Assigned to worker "+workerID)
}

// StartExecution marks the task as started.
func (t *Task) StartExecution() {
	now := time.Now().UTC()
	t.Context.StartedAt = &now
	if t.Timeout > 0 {
		t.SetExpiration(t.Timeout)
	}
	t.Context.AddStatusChange(TaskStatusProcessing, "Task execution started")
}

// Complete marks the task as completed successfully.
func (t *Task) Complete(result map[string]any) {
	t.Context.Result = result
	now := time.Now().UTC()
	t.Context.CompletedAt = &now
	t.Context.AddStatusChange(TaskStatusCompleted, "Task completed successfully")
}

// Fail marks the task as failed.
func (t *Task) Fail(errorMessage, errorTrace string) {
	t.Context.AddError("execution_error", errorMessage, errorTrace)
	now := time.Now().UTC()
	t.Context.CompletedAt = &now
	t.Context.AddStatusChange(TaskStatusFailed, "Task failed: "+errorMessage)
}

// MarkTimeout marks the task as timed out.
func (t *Task) MarkTimeout() {
	now := time.Now().UTC()
	t.Context.CompletedAt = &now
	t.Context.AddStatusChange(TaskStatusTimeout, "Task timed out")
}

// Cancel cancels the task.
func (t *Task) Cancel(reason string) {
	now := time.Now().UTC()
	t.Context.CompletedAt = &now
	t.Context.AddStatusChange(TaskStatusCancelled, "Task cancelled: "+reason)
}

// CanRetry checks if the task can be retried.
func (t *Task) CanRetry() bool {
	return t.Metadata.IsRetryable &&
		t.Context.CurrentAttempt <= t.MaxRetries &&
		(t.Context.CurrentStatus == TaskStatusFailed || t.Context.CurrentStatus == TaskStatusTimeout)
}

// ScheduleRetry schedules a retry attempt.
func (t *Task) ScheduleRetry() bool {
	if t.CanRetry() {
		retryAt := time.Now().UTC().Add(time.Duration(t.RetryDelay) * time.Second)
		t.Context.RetryAt = &retryAt
		t.Context.AddStatusChange(TaskStatusRetry, fmt.Sprintf("Scheduling retry attempt %d", t.Context.CurrentAttempt))
		return true
	}
	return false
}

// SetExpiration sets the expiration time.
func (t *Task) SetExpiration(expiresInSeconds int) {
	expireTime := time.Now().UTC().Add(time.Duration(expiresInSeconds) * time.Second)
	t.Context.ExpiresAt = &expireTime
}

// GetPriorityScore returns a numeric priority score for sorting.
func (t *Task) GetPriorityScore() int {
	score := t.Priority.Score()

	if t.Metadata.IsCritical {
		score += 10
	}

	ageMinutes := time.Since(t.Context.CreatedAt).Minutes()
	if ageMinutes > 60 {
		score--
	}

	if score < 1 {
		score = 1
	}
	return score
}

// ToMap converts the task to a map for JSON serialization.
func (t *Task) ToMap() map[string]any {
	var startedAt, completedAt *string
	if t.Context.StartedAt != nil {
		s := t.Context.StartedAt.Format(time.RFC3339)
		startedAt = &s
	}
	if t.Context.CompletedAt != nil {
		s := t.Context.CompletedAt.Format(time.RFC3339)
		completedAt = &s
	}

	return map[string]any{
		"task_id":        t.TaskID,
		"task_type":      string(t.TaskType),
		"priority":       string(t.Priority),
		"status":         string(t.Context.CurrentStatus),
		"worker_id":      t.Context.WorkerID,
		"client_id":      t.Context.ClientID,
		"created_at":     t.Context.CreatedAt.Format(time.RFC3339),
		"started_at":     startedAt,
		"completed_at":   completedAt,
		"execution_time": t.Context.GetExecutionTime(),
		"attempt":        t.Context.CurrentAttempt,
		"max_retries":    t.MaxRetries,
		"timeout":        t.Timeout,
		"is_expired":     t.Context.IsExpired(),
		"can_retry":      t.CanRetry(),
		"task_data":      t.Data,
		"metadata":       t.Metadata,
	}
}

// ToStorage returns a minimal representation for storage.
func (t *Task) ToStorage() map[string]any {
	return map[string]any{
		"task_id":             t.TaskID,
		"task_type":           string(t.TaskType),
		"data":                t.Data,
		"priority":            string(t.Priority),
		"timeout":             t.Timeout,
		"max_retries":         t.MaxRetries,
		"retry_delay":         t.RetryDelay,
		"executor_type":       string(t.ExecutorType),
		"worker_requirements": t.WorkerRequirements,
	}
}

// TaskFromStorage restores a Task from storage.
func TaskFromStorage(stored map[string]any) *Task {
	taskID, _ := stored["task_id"].(string)
	taskType := TaskType(stored["task_type"].(string))
	data, _ := stored["data"].(map[string]any)
	priority := TaskPriority(stored["priority"].(string))
	timeout, _ := stored["timeout"].(float64)
	maxRetries, _ := stored["max_retries"].(float64)
	retryDelay, _ := stored["retry_delay"].(float64)
	executorType := ExecutorType(stored["executor_type"].(string))
	workerReqs, _ := stored["worker_requirements"].([]any)

	requirements := make([]string, 0, len(workerReqs))
	for _, r := range workerReqs {
		if s, ok := r.(string); ok {
			requirements = append(requirements, s)
		}
	}

	task := &Task{
		TaskID:             taskID,
		TaskType:           taskType,
		Data:               data,
		Priority:           priority,
		Timeout:            int(timeout),
		MaxRetries:         int(maxRetries),
		RetryDelay:         int(retryDelay),
		ExecutorType:       executorType,
		WorkerRequirements: requirements,
		Metadata:           NewTaskMetadata(),
		Context:            NewTaskContext(taskID),
	}

	return task
}
