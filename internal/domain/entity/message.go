// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"time"
)

// MessageType represents the type of WebSocket message.
type MessageType string

const (
	// Registration messages
	MessageTypeClientRegistration MessageType = "client_registration"

	// Task messages
	MessageTypeTask         MessageType = "task"
	MessageTypeTaskAck      MessageType = "task_ack"
	MessageTypeTaskResult   MessageType = "task_result"
	MessageTypeTaskProgress MessageType = "task_progress"
	MessageTypeTaskCancel   MessageType = "task_cancel"

	// Status messages
	MessageTypeWorkerStatus MessageType = "worker_status"
	MessageTypeClientStatus MessageType = "client_status"

	// Health check messages
	MessageTypeHeartbeat MessageType = "heartbeat"
	MessageTypePing      MessageType = "ping"
	MessageTypePong      MessageType = "pong"

	// Broadcast messages
	MessageTypeBroadcast MessageType = "broadcast"

	// Service messages
	MessageTypeError MessageType = "error"
)

// BaseMessage is the base structure for all messages.
type BaseMessage struct {
	Type      MessageType `json:"type"`
	Timestamp time.Time   `json:"timestamp"`
	MessageID string      `json:"message_id,omitempty"`
}

// ClientRegistrationMessage is a client registration message.
type ClientRegistrationMessage struct {
	BaseMessage
	ClientID     string              `json:"client_id"`
	ClientType   ClientType          `json:"client_type"`
	ClientName   string              `json:"client_name"`
	Version      string              `json:"version"`
	Capabilities *WorkerCapabilities `json:"capabilities,omitempty"`
	AuthToken    string              `json:"auth_token,omitempty"`
	Metadata     map[string]any      `json:"metadata,omitempty"`
}

// ClientRegistrationResponse is a registration response message.
type ClientRegistrationResponse struct {
	BaseMessage
	Success   bool           `json:"success"`
	ClientID  string         `json:"client_id"`
	Message   string         `json:"message"`
	SessionID string         `json:"session_id,omitempty"`
	Config    map[string]any `json:"config,omitempty"`
}

// TaskMessage is a task submission/assignment message.
type TaskMessage struct {
	BaseMessage
	TaskID         string         `json:"task_id"`
	TaskType       TaskType       `json:"task_type"`
	ExecutorType   ExecutorType   `json:"executor_type"`
	Priority       TaskPriority   `json:"priority"`
	Payload        map[string]any `json:"payload"`
	Timeout        time.Duration  `json:"timeout"`
	RetryCount     int            `json:"retry_count,omitempty"`
	IdempotencyKey string         `json:"idempotency_key,omitempty"`
}

// TaskAckMessage is a task acknowledgment message.
type TaskAckMessage struct {
	BaseMessage
	TaskID  string `json:"task_id"`
	Success bool   `json:"success"`
	Message string `json:"message,omitempty"`
}

// TaskError represents a task error.
type TaskError struct {
	Type       string `json:"type"`
	Message    string `json:"message"`
	Stacktrace string `json:"stacktrace,omitempty"`
}

// TaskResultMessage is a task result message.
type TaskResultMessage struct {
	BaseMessage
	TaskID        string         `json:"task_id"`
	Status        TaskStatus     `json:"status"`
	Result        map[string]any `json:"result,omitempty"`
	Error         *TaskError     `json:"error,omitempty"`
	ExecutionTime time.Duration  `json:"execution_time,omitempty"`
}

// TaskProgressMessage is a task progress update message.
type TaskProgressMessage struct {
	BaseMessage
	TaskID     string         `json:"task_id"`
	Progress   float64        `json:"progress"` // 0.0 to 1.0
	Message    string         `json:"message,omitempty"`
	Details    map[string]any `json:"details,omitempty"`
}

// TaskCancelMessage is a task cancellation message.
type TaskCancelMessage struct {
	BaseMessage
	TaskID string `json:"task_id"`
	Reason string `json:"reason,omitempty"`
}

// WorkerStatusMessage is a worker status update message.
type WorkerStatusMessage struct {
	BaseMessage
	ClientID    string         `json:"client_id,omitempty"`
	Status      WorkerStatus   `json:"status"`
	ActiveTasks int            `json:"active_tasks,omitempty"`
	Load        float64        `json:"load,omitempty"`
	Metrics     map[string]any `json:"metrics,omitempty"`
}

// ClientStatusMessage is a client status broadcast message.
type ClientStatusMessage struct {
	BaseMessage
	ClientID   string           `json:"client_id"`
	ClientType ClientType       `json:"client_type"`
	Status     ConnectionStatus `json:"status"`
}

// HeartbeatMessage is a heartbeat message.
type HeartbeatMessage struct {
	BaseMessage
	ClientID string         `json:"client_id,omitempty"`
	Metrics  map[string]any `json:"metrics,omitempty"`
}

// BroadcastMessage is a broadcast message.
type BroadcastMessage struct {
	BaseMessage
	DataType string         `json:"data_type"`
	Data     map[string]any `json:"data"`
	Channel  string         `json:"channel,omitempty"`
}

// ErrorMessage is an error message.
type ErrorMessage struct {
	BaseMessage
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
}

// NewBaseMessage creates a new base message.
func NewBaseMessage(msgType MessageType) BaseMessage {
	return BaseMessage{
		Type:      msgType,
		Timestamp: time.Now().UTC(),
	}
}

// NewErrorMessage creates a new error message.
func NewErrorMessage(code, message string) ErrorMessage {
	return ErrorMessage{
		BaseMessage: NewBaseMessage(MessageTypeError),
		Code:        code,
		Message:     message,
	}
}

// NewTaskResultMessage creates a new task result message.
func NewTaskResultMessage(taskID string, status TaskStatus, result map[string]any) TaskResultMessage {
	return TaskResultMessage{
		BaseMessage: NewBaseMessage(MessageTypeTaskResult),
		TaskID:      taskID,
		Status:      status,
		Result:      result,
	}
}

// NewTaskProgressMessage creates a new task progress message.
func NewTaskProgressMessage(taskID string, progress float64, message string) TaskProgressMessage {
	return TaskProgressMessage{
		BaseMessage: NewBaseMessage(MessageTypeTaskProgress),
		TaskID:      taskID,
		Progress:    progress,
		Message:     message,
	}
}
