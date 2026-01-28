// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"testing"
	"time"
)

func TestNewClient(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test Bot", "1.0.0")

	if client.Info.ClientID != "client-1" {
		t.Errorf("Expected ClientID 'client-1', got '%s'", client.Info.ClientID)
	}

	if client.Info.ClientType != ClientTypeBot {
		t.Errorf("Expected ClientType 'bot', got '%s'", client.Info.ClientType)
	}

	if client.Info.ClientName != "Test Bot" {
		t.Errorf("Expected ClientName 'Test Bot', got '%s'", client.Info.ClientName)
	}

	if client.Info.ClientVersion != "1.0.0" {
		t.Errorf("Expected ClientVersion '1.0.0', got '%s'", client.Info.ClientVersion)
	}

	if client.Info.ConnectionStatus != ConnectionStatusConnected {
		t.Errorf("Expected ConnectionStatus 'connected', got '%s'", client.Info.ConnectionStatus)
	}
}

func TestNewWorkerCapabilities(t *testing.T) {
	caps := NewWorkerCapabilities()

	if caps.MaxConcurrentTasks != 1 {
		t.Errorf("Expected MaxConcurrentTasks 1, got %d", caps.MaxConcurrentTasks)
	}

	if caps.APIVersion != "1.0.0" {
		t.Errorf("Expected APIVersion '1.0.0', got '%s'", caps.APIVersion)
	}

	if len(caps.SupportedFormats) != 1 || caps.SupportedFormats[0] != "json" {
		t.Error("Expected SupportedFormats to contain 'json'")
	}
}

func TestClientInfo_IsConnected(t *testing.T) {
	info := NewClientInfo("test", ClientTypeBot, "Test")

	if info.IsConnected() {
		t.Error("New client should not be connected by default")
	}

	info.ConnectionStatus = ConnectionStatusConnected
	if !info.IsConnected() {
		t.Error("Client should be connected after setting status")
	}
}

func TestClientInfo_IsWorker(t *testing.T) {
	tests := []struct {
		clientType ClientType
		expected   bool
	}{
		{ClientTypeWorker, true},
		{ClientTypeWorkerAPI, true},
		{ClientTypeBot, false},
		{ClientTypeMonitor, false},
		{ClientTypeAdmin, false},
	}

	for _, tt := range tests {
		info := NewClientInfo("test", tt.clientType, "Test")
		if info.IsWorker() != tt.expected {
			t.Errorf("IsWorker() for %s: expected %v, got %v", tt.clientType, tt.expected, info.IsWorker())
		}
	}
}

func TestClientInfo_IsBot(t *testing.T) {
	info := NewClientInfo("test", ClientTypeBot, "Test")
	if !info.IsBot() {
		t.Error("ClientTypeBot should return true for IsBot()")
	}

	info2 := NewClientInfo("test", ClientTypeWorker, "Test")
	if info2.IsBot() {
		t.Error("ClientTypeWorker should return false for IsBot()")
	}
}

func TestClientInfo_CanExecuteTasks(t *testing.T) {
	// Without capabilities
	info := NewClientInfo("test", ClientTypeWorker, "Test")
	if info.CanExecuteTasks() {
		t.Error("Should not be able to execute tasks without capabilities")
	}

	// With capabilities
	caps := NewWorkerCapabilities()
	caps.SupportedTaskTypes = []string{"task_type_1"}
	info.Capabilities = caps

	if !info.CanExecuteTasks() {
		t.Error("Should be able to execute tasks with capabilities")
	}

	// Monitor type
	monitorInfo := NewClientInfo("monitor", ClientTypeMonitor, "Monitor")
	monitorInfo.Capabilities = caps
	if monitorInfo.CanExecuteTasks() {
		t.Error("Monitor should not be able to execute tasks")
	}
}

func TestClientInfo_CanHandleTask(t *testing.T) {
	info := NewClientInfo("test", ClientTypeWorker, "Test")
	info.Capabilities = &WorkerCapabilities{
		SupportedTaskTypes: []string{"type_a", "type_b"},
	}

	if !info.CanHandleTask("type_a") {
		t.Error("Should be able to handle type_a")
	}

	if info.CanHandleTask("type_c") {
		t.Error("Should not be able to handle type_c")
	}
}

func TestClientInfo_IsAvailable(t *testing.T) {
	info := NewClientInfo("test", ClientTypeWorker, "Test")
	info.ConnectionStatus = ConnectionStatusConnected
	info.Capabilities = &WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1"},
		MaxConcurrentTasks: 2,
	}
	info.Stats.ActiveTasks = 0

	if !info.IsAvailable() {
		t.Error("Should be available with capacity")
	}

	// At capacity
	info.Stats.ActiveTasks = 2
	if info.IsAvailable() {
		t.Error("Should not be available at capacity")
	}

	// Reset and check maintenance status
	info.Stats.ActiveTasks = 0
	status := WorkerStatusMaintenance
	info.WorkerStatus = &status
	if info.IsAvailable() {
		t.Error("Should not be available during maintenance")
	}
}

func TestClientInfo_GetLoadPercentage(t *testing.T) {
	info := NewClientInfo("test", ClientTypeWorker, "Test")
	info.Capabilities = &WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1"},
		MaxConcurrentTasks: 4,
	}

	info.Stats.ActiveTasks = 0
	if info.GetLoadPercentage() != 0 {
		t.Errorf("Expected 0%%, got %.2f%%", info.GetLoadPercentage())
	}

	info.Stats.ActiveTasks = 2
	if info.GetLoadPercentage() != 50 {
		t.Errorf("Expected 50%%, got %.2f%%", info.GetLoadPercentage())
	}

	info.Stats.ActiveTasks = 4
	if info.GetLoadPercentage() != 100 {
		t.Errorf("Expected 100%%, got %.2f%%", info.GetLoadPercentage())
	}
}

func TestClient_Connect(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test", "1.0")

	client.Connect("session-123")

	if client.Info.ConnectionStatus != ConnectionStatusConnected {
		t.Error("Client should be connected")
	}

	if client.Info.SessionID != "session-123" {
		t.Errorf("Expected session-123, got %s", client.Info.SessionID)
	}
}

func TestClient_Disconnect(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test", "1.0")
	client.Connect("session-123")

	client.Disconnect()

	if client.Info.ConnectionStatus != ConnectionStatusDisconnected {
		t.Error("Client should be disconnected")
	}

	if client.Info.Stats.DisconnectionCount != 1 {
		t.Errorf("Expected DisconnectionCount 1, got %d", client.Info.Stats.DisconnectionCount)
	}
}

func TestClient_AssignTask(t *testing.T) {
	client := CreateWorker("worker-1", "Test Worker", &WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1"},
		MaxConcurrentTasks: 2,
	})
	client.Info.ConnectionStatus = ConnectionStatusConnected

	// Assign first task
	if !client.AssignTask("task-1") {
		t.Error("Should be able to assign first task")
	}

	if client.Info.Stats.ActiveTasks != 1 {
		t.Errorf("Expected 1 active task, got %d", client.Info.Stats.ActiveTasks)
	}

	// Assign second task
	if !client.AssignTask("task-2") {
		t.Error("Should be able to assign second task")
	}

	// Try to assign third task (should fail)
	if client.AssignTask("task-3") {
		t.Error("Should not be able to assign third task (at capacity)")
	}
}

func TestClient_ReleaseTask(t *testing.T) {
	client := CreateWorker("worker-1", "Test Worker", &WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1"},
		MaxConcurrentTasks: 5,
	})
	client.Info.ConnectionStatus = ConnectionStatusConnected

	client.AssignTask("task-1")
	client.AssignTask("task-2")

	if client.Info.Stats.ActiveTasks != 2 {
		t.Errorf("Expected 2 active tasks, got %d", client.Info.Stats.ActiveTasks)
	}

	// Release task
	if !client.ReleaseTask("task-1") {
		t.Error("Should be able to release task-1")
	}

	if client.Info.Stats.ActiveTasks != 1 {
		t.Errorf("Expected 1 active task after release, got %d", client.Info.Stats.ActiveTasks)
	}

	// Try to release non-existent task
	if client.ReleaseTask("task-99") {
		t.Error("Should not be able to release non-existent task")
	}
}

func TestClient_CompleteTask(t *testing.T) {
	client := CreateWorker("worker-1", "Test Worker", &WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1"},
		MaxConcurrentTasks: 5,
	})
	client.Info.ConnectionStatus = ConnectionStatusConnected

	client.AssignTask("task-1")
	client.CompleteTask("task-1", TaskStatusCompleted, 100.0)

	if client.Info.Stats.SuccessfulTasks != 1 {
		t.Errorf("Expected 1 successful task, got %d", client.Info.Stats.SuccessfulTasks)
	}

	if client.Info.Stats.ActiveTasks != 0 {
		t.Errorf("Expected 0 active tasks after completion, got %d", client.Info.Stats.ActiveTasks)
	}

	// Check history
	if len(client.TaskHistory) != 1 {
		t.Errorf("Expected 1 history entry, got %d", len(client.TaskHistory))
	}
}

func TestClient_PingPong(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test", "1.0")

	client.Ping()
	if client.Info.LastPing == nil {
		t.Error("LastPing should be set after Ping()")
	}

	client.Pong()
	if client.Info.LastPong == nil {
		t.Error("LastPong should be set after Pong()")
	}
}

func TestClient_IsHealthy(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test", "1.0")
	client.Info.ConnectionStatus = ConnectionStatusConnected

	// Without any pong, should be healthy
	if !client.IsHealthy(time.Minute) {
		t.Error("Should be healthy without previous pong")
	}

	// With recent pong
	client.Pong()
	if !client.IsHealthy(time.Minute) {
		t.Error("Should be healthy with recent pong")
	}

	// With old pong (simulate by setting lastPong to past)
	oldTime := time.Now().Add(-2 * time.Minute)
	client.Info.LastPong = &oldTime
	if client.IsHealthy(time.Minute) {
		t.Error("Should not be healthy with old pong")
	}

	// When disconnected
	client.Info.ConnectionStatus = ConnectionStatusDisconnected
	if client.IsHealthy(time.Minute) {
		t.Error("Should not be healthy when disconnected")
	}
}

func TestCreateBot(t *testing.T) {
	caps := &WorkerCapabilities{
		SupportedTaskTypes: []string{"bot_task"},
	}
	bot := CreateBot("bot-1", "My Bot", caps)

	if bot.Info.ClientType != ClientTypeBot {
		t.Errorf("Expected ClientTypeBot, got %s", bot.Info.ClientType)
	}

	if bot.Info.Capabilities != caps {
		t.Error("Capabilities should be set")
	}
}

func TestCreateWorker(t *testing.T) {
	caps := &WorkerCapabilities{
		SupportedTaskTypes: []string{"worker_task"},
	}
	worker := CreateWorker("worker-1", "My Worker", caps)

	if worker.Info.ClientType != ClientTypeWorker {
		t.Errorf("Expected ClientTypeWorker, got %s", worker.Info.ClientType)
	}

	if worker.Info.WorkerStatus == nil || *worker.Info.WorkerStatus != WorkerStatusIdle {
		t.Error("Worker should have Idle status")
	}
}

func TestCreateMonitor(t *testing.T) {
	monitor := CreateMonitor("monitor-1", "System Monitor")

	if monitor.Info.ClientType != ClientTypeMonitor {
		t.Errorf("Expected ClientTypeMonitor, got %s", monitor.Info.ClientType)
	}
}

func TestCreateAdmin(t *testing.T) {
	admin := CreateAdmin("admin-1", "Admin User")

	if admin.Info.ClientType != ClientTypeAdmin {
		t.Errorf("Expected ClientTypeAdmin, got %s", admin.Info.ClientType)
	}
}

func TestClient_ToMap(t *testing.T) {
	client := NewClient("client-1", ClientTypeBot, "Test Bot", "1.0.0")
	client.Info.RemoteAddress = "192.168.1.1"

	m := client.ToMap()

	if m["client_id"] != "client-1" {
		t.Errorf("Expected client_id 'client-1', got '%v'", m["client_id"])
	}

	if m["client_type"] != "bot" {
		t.Errorf("Expected client_type 'bot', got '%v'", m["client_type"])
	}

	if m["remote_address"] != "192.168.1.1" {
		t.Errorf("Expected remote_address '192.168.1.1', got '%v'", m["remote_address"])
	}

	stats, ok := m["stats"].(map[string]any)
	if !ok {
		t.Fatal("stats should be a map")
	}

	if stats["total_tasks"] != int64(0) {
		t.Errorf("Expected total_tasks 0, got %v", stats["total_tasks"])
	}
}
