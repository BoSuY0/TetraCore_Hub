// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"encoding/json"
	"testing"
	"time"
)

func TestBaseMessage(t *testing.T) {
	msg := BaseMessage{
		Type:      MessageTypeTask,
		Timestamp: time.Now().UTC(),
		MessageID: "msg-123",
	}

	if msg.Type != MessageTypeTask {
		t.Errorf("Expected Type 'task', got '%s'", msg.Type)
	}

	if msg.MessageID != "msg-123" {
		t.Errorf("Expected MessageID 'msg-123', got '%s'", msg.MessageID)
	}
}

func TestClientRegistrationMessage_Serialization(t *testing.T) {
	msg := ClientRegistrationMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeClientRegistration,
			Timestamp: time.Now().UTC(),
		},
		ClientID:   "client-1",
		ClientType: ClientTypeBot,
		ClientName: "Test Bot",
		Version:    "1.0.0",
		Metadata:   map[string]any{"env": "test"},
	}

	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var decoded ClientRegistrationMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if decoded.ClientID != "client-1" {
		t.Errorf("Expected ClientID 'client-1', got '%s'", decoded.ClientID)
	}

	if decoded.ClientType != ClientTypeBot {
		t.Errorf("Expected ClientType 'bot', got '%s'", decoded.ClientType)
	}
}

func TestClientRegistrationResponse(t *testing.T) {
	resp := ClientRegistrationResponse{
		BaseMessage: BaseMessage{
			Type:      MessageTypeClientRegistration,
			Timestamp: time.Now().UTC(),
		},
		Success:   true,
		ClientID:  "client-1",
		Message:   "Registration successful",
		SessionID: "session-123",
	}

	if !resp.Success {
		t.Error("Expected Success to be true")
	}

	if resp.SessionID != "session-123" {
		t.Errorf("Expected SessionID 'session-123', got '%s'", resp.SessionID)
	}
}

func TestTaskMessage_Serialization(t *testing.T) {
	msg := TaskMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTask,
			Timestamp: time.Now().UTC(),
		},
		TaskID:       "task-123",
		TaskType:     TaskTypeAPIRequest,
		ExecutorType: ExecutorTypeWorker,
		Priority:     TaskPriorityHigh,
		Payload:      map[string]any{"url": "https://api.example.com"},
		Timeout:      30 * time.Second,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	var decoded TaskMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if decoded.TaskID != "task-123" {
		t.Errorf("Expected TaskID 'task-123', got '%s'", decoded.TaskID)
	}

	if decoded.Priority != TaskPriorityHigh {
		t.Errorf("Expected Priority 'high', got '%s'", decoded.Priority)
	}
}

func TestTaskAckMessage(t *testing.T) {
	msg := TaskAckMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTaskAck,
			Timestamp: time.Now().UTC(),
		},
		TaskID:  "task-123",
		Success: true,
		Message: "Task accepted",
	}

	if !msg.Success {
		t.Error("Expected Success to be true")
	}

	if msg.TaskID != "task-123" {
		t.Errorf("Expected TaskID 'task-123', got '%s'", msg.TaskID)
	}
}

func TestTaskError(t *testing.T) {
	err := TaskError{
		Type:       "RuntimeError",
		Message:    "Something went wrong",
		Stacktrace: "line 1\nline 2",
	}

	if err.Type != "RuntimeError" {
		t.Errorf("Expected Type 'RuntimeError', got '%s'", err.Type)
	}

	if err.Stacktrace == "" {
		t.Error("Stacktrace should be set")
	}
}

func TestTaskResultMessage_Success(t *testing.T) {
	msg := TaskResultMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTaskResult,
			Timestamp: time.Now().UTC(),
		},
		TaskID:        "task-123",
		Status:        TaskStatusCompleted,
		Result:        map[string]any{"output": "success"},
		ExecutionTime: 100 * time.Millisecond,
	}

	if msg.Status != TaskStatusCompleted {
		t.Errorf("Expected Status 'completed', got '%s'", msg.Status)
	}

	if msg.Result["output"] != "success" {
		t.Error("Result should contain output")
	}

	if msg.Error != nil {
		t.Error("Error should be nil for successful task")
	}
}

func TestTaskResultMessage_Failure(t *testing.T) {
	msg := TaskResultMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTaskResult,
			Timestamp: time.Now().UTC(),
		},
		TaskID: "task-123",
		Status: TaskStatusFailed,
		Error: &TaskError{
			Type:    "ProcessingError",
			Message: "Failed to process",
		},
	}

	if msg.Status != TaskStatusFailed {
		t.Errorf("Expected Status 'failed', got '%s'", msg.Status)
	}

	if msg.Error == nil {
		t.Fatal("Error should not be nil for failed task")
	}

	if msg.Error.Type != "ProcessingError" {
		t.Errorf("Expected error type 'ProcessingError', got '%s'", msg.Error.Type)
	}
}

func TestTaskProgressMessage(t *testing.T) {
	msg := TaskProgressMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTaskProgress,
			Timestamp: time.Now().UTC(),
		},
		TaskID:   "task-123",
		Progress: 0.5,
		Message:  "50% complete",
		Details:  map[string]any{"step": 5, "total_steps": 10},
	}

	if msg.Progress != 0.5 {
		t.Errorf("Expected Progress 0.5, got %f", msg.Progress)
	}

	if msg.Details["step"] != 5 {
		t.Error("Details should contain step")
	}
}

func TestTaskCancelMessage(t *testing.T) {
	msg := TaskCancelMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTaskCancel,
			Timestamp: time.Now().UTC(),
		},
		TaskID: "task-123",
		Reason: "user requested",
	}

	if msg.TaskID != "task-123" {
		t.Errorf("Expected TaskID 'task-123', got '%s'", msg.TaskID)
	}

	if msg.Reason != "user requested" {
		t.Errorf("Expected Reason 'user requested', got '%s'", msg.Reason)
	}
}

func TestWorkerStatusMessage(t *testing.T) {
	msg := WorkerStatusMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeWorkerStatus,
			Timestamp: time.Now().UTC(),
		},
		ClientID:    "worker-1",
		Status:      WorkerStatusBusy,
		ActiveTasks: 3,
		Load:        0.75,
		Metrics:     map[string]any{"cpu": 0.5, "memory": 0.7},
	}

	if msg.Status != WorkerStatusBusy {
		t.Errorf("Expected Status 'busy', got '%s'", msg.Status)
	}

	if msg.ActiveTasks != 3 {
		t.Errorf("Expected ActiveTasks 3, got %d", msg.ActiveTasks)
	}

	if msg.Load != 0.75 {
		t.Errorf("Expected Load 0.75, got %f", msg.Load)
	}
}

func TestClientStatusMessage(t *testing.T) {
	msg := ClientStatusMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeClientStatus,
			Timestamp: time.Now().UTC(),
		},
		ClientID:   "client-1",
		ClientType: ClientTypeBot,
		Status:     ConnectionStatusConnected,
	}

	if msg.Status != ConnectionStatusConnected {
		t.Errorf("Expected Status 'connected', got '%s'", msg.Status)
	}
}

func TestHeartbeatMessage(t *testing.T) {
	msg := HeartbeatMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeHeartbeat,
			Timestamp: time.Now().UTC(),
		},
		ClientID: "client-1",
		Metrics:  map[string]any{"uptime": 3600},
	}

	if msg.ClientID != "client-1" {
		t.Errorf("Expected ClientID 'client-1', got '%s'", msg.ClientID)
	}

	if msg.Metrics["uptime"] != 3600 {
		t.Error("Metrics should contain uptime")
	}
}

func TestBroadcastMessage(t *testing.T) {
	msg := BroadcastMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeBroadcast,
			Timestamp: time.Now().UTC(),
		},
		DataType: "notification",
		Data:     map[string]any{"message": "System update"},
	}

	if msg.DataType != "notification" {
		t.Errorf("Expected DataType 'notification', got '%s'", msg.DataType)
	}

	if msg.Data["message"] != "System update" {
		t.Error("Data should contain message")
	}
}

func TestErrorMessage(t *testing.T) {
	msg := ErrorMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeError,
			Timestamp: time.Now().UTC(),
		},
		Code:    "AUTH_FAILED",
		Message: "Authentication failed",
		Details: map[string]any{"reason": "invalid_token"},
	}

	if msg.Code != "AUTH_FAILED" {
		t.Errorf("Expected Code 'AUTH_FAILED', got '%s'", msg.Code)
	}

	if msg.Message != "Authentication failed" {
		t.Errorf("Expected Message 'Authentication failed', got '%s'", msg.Message)
	}
}

func TestMessageTypes(t *testing.T) {
	types := []MessageType{
		MessageTypeClientRegistration,
		MessageTypeTask,
		MessageTypeTaskAck,
		MessageTypeTaskResult,
		MessageTypeTaskProgress,
		MessageTypeTaskCancel,
		MessageTypeWorkerStatus,
		MessageTypeClientStatus,
		MessageTypeHeartbeat,
		MessageTypePing,
		MessageTypePong,
		MessageTypeBroadcast,
		MessageTypeError,
	}

	for _, mt := range types {
		if mt == "" {
			t.Error("Message type should not be empty")
		}
	}
}

func TestMessageJSON_RoundTrip(t *testing.T) {
	original := TaskMessage{
		BaseMessage: BaseMessage{
			Type:      MessageTypeTask,
			Timestamp: time.Now().UTC().Truncate(time.Second), // Truncate for JSON precision
			MessageID: "test-123",
		},
		TaskID:         "task-456",
		TaskType:       TaskTypeAPIRequest,
		ExecutorType:   ExecutorTypeWorker,
		Priority:       TaskPriorityNormal,
		Payload:        map[string]any{"key": "value", "number": float64(42)},
		Timeout:        30 * time.Second,
		RetryCount:     2,
		IdempotencyKey: "idemp-key",
	}

	// Marshal
	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal: %v", err)
	}

	// Unmarshal
	var decoded TaskMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	// Compare fields
	if decoded.TaskID != original.TaskID {
		t.Errorf("TaskID mismatch: expected '%s', got '%s'", original.TaskID, decoded.TaskID)
	}

	if decoded.Priority != original.Priority {
		t.Errorf("Priority mismatch: expected '%s', got '%s'", original.Priority, decoded.Priority)
	}

	if decoded.IdempotencyKey != original.IdempotencyKey {
		t.Errorf("IdempotencyKey mismatch: expected '%s', got '%s'", original.IdempotencyKey, decoded.IdempotencyKey)
	}

	if decoded.Payload["key"] != original.Payload["key"] {
		t.Error("Payload key mismatch")
	}
}
