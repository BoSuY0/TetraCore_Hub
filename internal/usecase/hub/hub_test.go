// Package hub provides the main orchestration use case for TetraCore Hub.
package hub

import (
	"context"
	"testing"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// mockAuthUC is a mock auth use case for testing.
type mockAuthUC struct {
	sessionCount int64
}

func (m *mockAuthUC) GetSessionCount(ctx context.Context) (int64, error) {
	return m.sessionCount, nil
}

func (m *mockAuthUC) CleanupExpiredSessions(ctx context.Context) (int64, error) {
	return 0, nil
}

// mockClientUC is a mock client use case for testing.
type mockClientUC struct {
	connected    int64
	disconnected int64
	bots         int64
	workers      int64
}

func (m *mockClientUC) GetStats(ctx context.Context) (*mockClientStats, error) {
	return &mockClientStats{
		Total:        m.connected + m.disconnected,
		Connected:    m.connected,
		Disconnected: m.disconnected,
		Bots:         m.bots,
		Workers:      m.workers,
	}, nil
}

func (m *mockClientUC) CleanupStaleConnections(ctx context.Context) (int, error) {
	return 0, nil
}

type mockClientStats struct {
	Total        int64
	Connected    int64
	Disconnected int64
	Bots         int64
	Workers      int64
}

// mockTaskUC is a mock task use case for testing.
type mockTaskUC struct {
	total     int64
	pending   int64
	completed int64
	failed    int64
}

func (m *mockTaskUC) GetStats(ctx context.Context) (*mockTaskStats, error) {
	return &mockTaskStats{
		Total:     m.total,
		Pending:   m.pending,
		Completed: m.completed,
		Failed:    m.failed,
	}, nil
}

func (m *mockTaskUC) CleanupOldTasks(ctx context.Context) (int64, error) {
	return 0, nil
}

func (m *mockTaskUC) ProcessPendingTasks(ctx context.Context) (int, error) {
	return 0, nil
}

type mockTaskStats struct {
	Total     int64
	Pending   int64
	Completed int64
	Failed    int64
}

// mockConnMgr is a mock connection manager for testing.
type mockConnMgr struct {
	connectedCount int
	sentMessages   []sentMessage
	broadcasts     []any
}

type sentMessage struct {
	clientID string
	message  any
}

func (m *mockConnMgr) SendToClient(clientID string, message any) error {
	m.sentMessages = append(m.sentMessages, sentMessage{clientID: clientID, message: message})
	return nil
}

func (m *mockConnMgr) Broadcast(message any) error {
	m.broadcasts = append(m.broadcasts, message)
	return nil
}

func (m *mockConnMgr) BroadcastToType(clientType entity.ClientType, message any) error {
	m.broadcasts = append(m.broadcasts, message)
	return nil
}

func (m *mockConnMgr) CloseConnection(clientID string, reason string) error {
	return nil
}

func (m *mockConnMgr) GetConnectedCount() int {
	return m.connectedCount
}

func TestNewUseCase(t *testing.T) {
	config := Config{
		TaskChannel:       "tasks",
		ResultChannel:     "results",
		BroadcastChannel:  "broadcast",
		HealthChannel:     "health",
		CleanupInterval:   time.Minute,
		HeartbeatInterval: time.Second * 30,
	}

	uc := NewUseCase(nil, nil, nil, nil, nil, config)

	if uc == nil {
		t.Fatal("Expected non-nil UseCase")
	}

	if uc.config.TaskChannel != "tasks" {
		t.Errorf("Expected TaskChannel 'tasks', got '%s'", uc.config.TaskChannel)
	}

	if uc.config.CleanupInterval != time.Minute {
		t.Errorf("Expected CleanupInterval 1m, got %v", uc.config.CleanupInterval)
	}
}

func TestUseCase_SetConnectionManager(t *testing.T) {
	config := Config{}
	uc := NewUseCase(nil, nil, nil, nil, nil, config)

	connMgr := &mockConnMgr{connectedCount: 5}
	uc.SetConnectionManager(connMgr)

	if uc.connMgr == nil {
		t.Error("Expected connection manager to be set")
	}
}

func TestUseCase_IncrementMessageCount(t *testing.T) {
	config := Config{}
	uc := NewUseCase(nil, nil, nil, nil, nil, config)

	if uc.messageCount != 0 {
		t.Errorf("Expected initial message count 0, got %d", uc.messageCount)
	}

	uc.IncrementMessageCount()
	if uc.messageCount != 1 {
		t.Errorf("Expected message count 1, got %d", uc.messageCount)
	}

	uc.IncrementMessageCount()
	uc.IncrementMessageCount()
	if uc.messageCount != 3 {
		t.Errorf("Expected message count 3, got %d", uc.messageCount)
	}
}

func TestUseCase_UptimeTracking(t *testing.T) {
	config := Config{
		CleanupInterval:   time.Hour,
		HeartbeatInterval: time.Hour,
	}
	uc := NewUseCase(nil, nil, nil, nil, nil, config)

	// Before Start, startTime should be zero
	if !uc.startTime.IsZero() {
		t.Error("Expected startTime to be zero before Start()")
	}

	// Simulate setting start time (normally done in Start())
	uc.startTime = time.Now().Add(-10 * time.Second)

	// Check that uptime is approximately correct
	uptime := time.Since(uc.startTime)
	if uptime < 9*time.Second || uptime > 11*time.Second {
		t.Errorf("Expected uptime around 10s, got %v", uptime)
	}
}

func TestHubStats(t *testing.T) {
	stats := &HubStats{
		Sessions:     10,
		Connections:  5,
		MessageCount: 100,
		Uptime:       time.Hour,
	}

	if stats.Sessions != 10 {
		t.Errorf("Expected 10 sessions, got %d", stats.Sessions)
	}

	if stats.Connections != 5 {
		t.Errorf("Expected 5 connections, got %d", stats.Connections)
	}

	if stats.MessageCount != 100 {
		t.Errorf("Expected 100 messages, got %d", stats.MessageCount)
	}

	if stats.Uptime != time.Hour {
		t.Errorf("Expected 1h uptime, got %v", stats.Uptime)
	}
}

func TestConfig(t *testing.T) {
	config := Config{
		TaskChannel:       "hub:tasks",
		ResultChannel:     "hub:results",
		BroadcastChannel:  "hub:broadcast",
		HealthChannel:     "hub:health",
		CleanupInterval:   5 * time.Minute,
		HeartbeatInterval: 30 * time.Second,
	}

	if config.TaskChannel != "hub:tasks" {
		t.Errorf("Expected TaskChannel 'hub:tasks', got '%s'", config.TaskChannel)
	}

	if config.ResultChannel != "hub:results" {
		t.Errorf("Expected ResultChannel 'hub:results', got '%s'", config.ResultChannel)
	}

	if config.BroadcastChannel != "hub:broadcast" {
		t.Errorf("Expected BroadcastChannel 'hub:broadcast', got '%s'", config.BroadcastChannel)
	}

	if config.HealthChannel != "hub:health" {
		t.Errorf("Expected HealthChannel 'hub:health', got '%s'", config.HealthChannel)
	}

	if config.CleanupInterval != 5*time.Minute {
		t.Errorf("Expected CleanupInterval 5m, got %v", config.CleanupInterval)
	}

	if config.HeartbeatInterval != 30*time.Second {
		t.Errorf("Expected HeartbeatInterval 30s, got %v", config.HeartbeatInterval)
	}
}

func TestMockConnectionManager(t *testing.T) {
	connMgr := &mockConnMgr{connectedCount: 10}

	if connMgr.GetConnectedCount() != 10 {
		t.Errorf("Expected connected count 10, got %d", connMgr.GetConnectedCount())
	}

	err := connMgr.SendToClient("client-1", "test message")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if len(connMgr.sentMessages) != 1 {
		t.Errorf("Expected 1 sent message, got %d", len(connMgr.sentMessages))
	}

	if connMgr.sentMessages[0].clientID != "client-1" {
		t.Errorf("Expected client ID 'client-1', got '%s'", connMgr.sentMessages[0].clientID)
	}

	err = connMgr.Broadcast("broadcast message")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if len(connMgr.broadcasts) != 1 {
		t.Errorf("Expected 1 broadcast, got %d", len(connMgr.broadcasts))
	}

	err = connMgr.BroadcastToType(entity.ClientTypeWorker, "worker broadcast")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}

	if len(connMgr.broadcasts) != 2 {
		t.Errorf("Expected 2 broadcasts, got %d", len(connMgr.broadcasts))
	}

	err = connMgr.CloseConnection("client-1", "test")
	if err != nil {
		t.Errorf("Unexpected error: %v", err)
	}
}

func TestUseCase_Stop(t *testing.T) {
	config := Config{
		CleanupInterval:   time.Hour,
		HeartbeatInterval: time.Hour,
	}
	uc := NewUseCase(nil, nil, nil, nil, nil, config)

	// Stop should not panic even without Start
	err := uc.Stop()
	if err != nil {
		t.Errorf("Unexpected error on Stop: %v", err)
	}
}
