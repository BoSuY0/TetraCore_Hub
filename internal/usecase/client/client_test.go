// Package client provides client management use cases for TetraCore Hub.
package client

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// ============================================================
// Mock Repository
// ============================================================

type mockClientRepo struct {
	mu      sync.RWMutex
	clients map[string]*entity.Client
}

func newMockClientRepo() *mockClientRepo {
	return &mockClientRepo{
		clients: make(map[string]*entity.Client),
	}
}

func (r *mockClientRepo) Save(ctx context.Context, client *entity.Client) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.clients[client.Info.ClientID] = client
	return nil
}

func (r *mockClientRepo) Get(ctx context.Context, clientID string) (*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	if c, ok := r.clients[clientID]; ok {
		return c, nil
	}
	return nil, errors.New("client not found")
}

func (r *mockClientRepo) GetAll(ctx context.Context) ([]*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]*entity.Client, 0, len(r.clients))
	for _, c := range r.clients {
		result = append(result, c)
	}
	return result, nil
}

func (r *mockClientRepo) GetByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var result []*entity.Client
	for _, c := range r.clients {
		if c.Info.ClientType == clientType {
			result = append(result, c)
		}
	}
	return result, nil
}

func (r *mockClientRepo) GetConnected(ctx context.Context) ([]*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var result []*entity.Client
	for _, c := range r.clients {
		if c.Info.ConnectionStatus == entity.ConnectionStatusConnected {
			result = append(result, c)
		}
	}
	return result, nil
}

func (r *mockClientRepo) GetAvailableWorkers(ctx context.Context, taskType string) ([]*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var result []*entity.Client
	for _, c := range r.clients {
		if c.Info.ClientType == entity.ClientTypeWorker &&
			c.Info.ConnectionStatus == entity.ConnectionStatusConnected &&
			c.Info.WorkerStatus != nil && *c.Info.WorkerStatus == entity.WorkerStatusIdle {
			result = append(result, c)
		}
	}
	return result, nil
}

func (r *mockClientRepo) GetAvailableExecutors(ctx context.Context, executorType entity.ExecutorType, taskType string) ([]*entity.Client, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	var result []*entity.Client
	for _, c := range r.clients {
		if c.Info.ConnectionStatus != entity.ConnectionStatusConnected {
			continue
		}

		switch executorType {
		case entity.ExecutorTypeBot:
			if c.Info.ClientType != entity.ClientTypeBot {
				continue
			}
		case entity.ExecutorTypeWorkerAPI:
			if c.Info.ClientType != entity.ClientTypeWorkerAPI {
				continue
			}
		default:
			// "worker" (та дефолт) — дозволяємо і worker_api.
			if c.Info.ClientType != entity.ClientTypeWorker && c.Info.ClientType != entity.ClientTypeWorkerAPI {
				continue
			}
		}

		// Для простоти: як і раніше, враховуємо idle-статус тільки для воркерів.
		if c.Info.ClientType == entity.ClientTypeWorker || c.Info.ClientType == entity.ClientTypeWorkerAPI {
			if c.Info.WorkerStatus == nil || *c.Info.WorkerStatus != entity.WorkerStatusIdle {
				continue
			}
		}

		result = append(result, c)
	}

	return result, nil
}

func (r *mockClientRepo) Delete(ctx context.Context, clientID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.clients, clientID)
	return nil
}

func (r *mockClientRepo) UpdateStatus(ctx context.Context, clientID string, status entity.ConnectionStatus) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		c.Info.ConnectionStatus = status
	}
	return nil
}

func (r *mockClientRepo) UpdateWorkerStatus(ctx context.Context, clientID string, status entity.WorkerStatus) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		c.Info.WorkerStatus = &status
	}
	return nil
}

func (r *mockClientRepo) IncrementTaskCount(ctx context.Context, clientID string, status entity.TaskStatus) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		if c.Info.Stats == nil {
			c.Info.Stats = &entity.ClientStats{}
		}
		switch status {
		case entity.TaskStatusCompleted:
			c.Info.Stats.SuccessfulTasks++
		case entity.TaskStatusFailed:
			c.Info.Stats.FailedTasks++
		}
		c.Info.Stats.TotalTasks++
	}
	return nil
}

func (r *mockClientRepo) SetActiveTask(ctx context.Context, clientID, taskID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		if c.ActiveTasks == nil {
			c.ActiveTasks = make(map[string]time.Time)
		}
		c.ActiveTasks[taskID] = time.Now()
		if c.Info.Stats != nil {
			c.Info.Stats.ActiveTasks++
		}
	}
	return nil
}

func (r *mockClientRepo) RemoveActiveTask(ctx context.Context, clientID, taskID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		if c.ActiveTasks != nil {
			delete(c.ActiveTasks, taskID)
		}
		if c.Info.Stats != nil && c.Info.Stats.ActiveTasks > 0 {
			c.Info.Stats.ActiveTasks--
		}
	}
	return nil
}

func (r *mockClientRepo) ClearActiveTasks(ctx context.Context, clientID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if c, ok := r.clients[clientID]; ok {
		c.ActiveTasks = make(map[string]time.Time)
		if c.Info.Stats != nil {
			c.Info.Stats.ActiveTasks = 0
		}
	}
	return nil
}

func (r *mockClientRepo) Count(ctx context.Context) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return int64(len(r.clients)), nil
}

func (r *mockClientRepo) CountByType(ctx context.Context, clientType entity.ClientType) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var count int64
	for _, c := range r.clients {
		if c.Info.ClientType == clientType {
			count++
		}
	}
	return count, nil
}

func (r *mockClientRepo) Exists(ctx context.Context, clientID string) (bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.clients[clientID]
	return ok, nil
}

// ============================================================
// Test Helpers
// ============================================================

func setupClientUseCase(t *testing.T) (*UseCase, *mockClientRepo) {
	t.Helper()

	repo := newMockClientRepo()
	config := Config{
		HeartbeatTimeout:     30 * time.Second,
		CleanupInterval:      time.Minute,
		MaxClientsPerType:    100,
		AllowReconnect:       true,
		ReconnectGracePeriod: time.Minute,
	}

	uc := NewUseCase(repo, config)
	return uc, repo
}

// ============================================================
// Tests
// ============================================================

func TestRegisterClient_NewClient(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}

	client, err := uc.RegisterClient(ctx, input)
	if err != nil {
		t.Fatalf("RegisterClient failed: %v", err)
	}

	if client.Info.ClientID != "client-1" {
		t.Errorf("Expected ClientID client-1, got %s", client.Info.ClientID)
	}

	if client.Info.ClientType != entity.ClientTypeBot {
		t.Errorf("Expected ClientType bot, got %s", client.Info.ClientType)
	}

	if client.Info.ConnectionStatus != entity.ConnectionStatusConnected {
		t.Errorf("Expected ConnectionStatus connected, got %s", client.Info.ConnectionStatus)
	}
}

func TestRegisterClient_Worker(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	capabilities := &entity.WorkerCapabilities{
		SupportedTaskTypes: []string{"task_type_1", "task_type_2"},
		MaxConcurrentTasks: 5,
	}

	input := RegisterInput{
		ClientID:     "worker-1",
		ClientType:   entity.ClientTypeWorker,
		Name:         "Test Worker",
		Version:      "1.0.0",
		Capabilities: capabilities,
	}

	client, err := uc.RegisterClient(ctx, input)
	if err != nil {
		t.Fatalf("RegisterClient failed: %v", err)
	}

	if client.Info.WorkerStatus == nil {
		t.Fatal("Worker status should not be nil")
	}

	if *client.Info.WorkerStatus != entity.WorkerStatusIdle {
		t.Errorf("Expected WorkerStatus idle, got %s", *client.Info.WorkerStatus)
	}

	if client.Info.Capabilities == nil {
		t.Fatal("Capabilities should not be nil")
	}

	if len(client.Info.Capabilities.SupportedTaskTypes) != 2 {
		t.Errorf("Expected 2 supported tasks, got %d", len(client.Info.Capabilities.SupportedTaskTypes))
	}
}

func TestRegisterClient_Reconnect(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register first time
	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}

	client1, err := uc.RegisterClient(ctx, input)
	if err != nil {
		t.Fatalf("First RegisterClient failed: %v", err)
	}

	// Disconnect
	uc.DisconnectClient(ctx, "client-1", "test disconnect")

	// Reconnect
	client2, err := uc.RegisterClient(ctx, input)
	if err != nil {
		t.Fatalf("Reconnect failed: %v", err)
	}

	if client2.Info.ClientID != client1.Info.ClientID {
		t.Error("Client ID should be the same after reconnect")
	}

	if client2.Info.ReconnectCount != 1 {
		t.Errorf("Expected ReconnectCount 1, got %d", client2.Info.ReconnectCount)
	}
}

func TestDisconnectClient(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}

	_, err := uc.RegisterClient(ctx, input)
	if err != nil {
		t.Fatalf("RegisterClient failed: %v", err)
	}

	// Disconnect
	err = uc.DisconnectClient(ctx, "client-1", "test reason")
	if err != nil {
		t.Fatalf("DisconnectClient failed: %v", err)
	}

	// Check status
	client, _ := uc.GetClient(ctx, "client-1")
	if client.Info.ConnectionStatus != entity.ConnectionStatusDisconnected {
		t.Errorf("Expected disconnected status, got %s", client.Info.ConnectionStatus)
	}

	if client.Info.DisconnectReason != "test reason" {
		t.Errorf("Expected disconnect reason 'test reason', got %s", client.Info.DisconnectReason)
	}
}

func TestGetClient_NotFound(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	_, err := uc.GetClient(ctx, "nonexistent")
	if err == nil {
		t.Error("Expected error for nonexistent client")
	}
}

func TestGetClientsByType(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register different types
	types := []entity.ClientType{entity.ClientTypeBot, entity.ClientTypeBot, entity.ClientTypeWorker}
	for i, ct := range types {
		input := RegisterInput{
			ClientID:   "client-" + string(rune('a'+i)),
			ClientType: ct,
			Name:       "Test",
			Version:    "1.0.0",
		}
		uc.RegisterClient(ctx, input)
	}

	bots, err := uc.GetClientsByType(ctx, entity.ClientTypeBot)
	if err != nil {
		t.Fatalf("GetClientsByType failed: %v", err)
	}

	if len(bots) != 2 {
		t.Errorf("Expected 2 bots, got %d", len(bots))
	}
}

func TestGetConnectedClients(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register clients
	for i := 0; i < 3; i++ {
		input := RegisterInput{
			ClientID:   "client-" + string(rune('0'+i)),
			ClientType: entity.ClientTypeBot,
			Name:       "Test",
			Version:    "1.0.0",
		}
		uc.RegisterClient(ctx, input)
	}

	// Disconnect one
	uc.DisconnectClient(ctx, "client-0", "test")

	connected, err := uc.GetConnectedClients(ctx)
	if err != nil {
		t.Fatalf("GetConnectedClients failed: %v", err)
	}

	if len(connected) != 2 {
		t.Errorf("Expected 2 connected clients, got %d", len(connected))
	}
}

func TestSelectWorker(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register workers
	for i := 0; i < 3; i++ {
		input := RegisterInput{
			ClientID:   "worker-" + string(rune('0'+i)),
			ClientType: entity.ClientTypeWorker,
			Name:       "Test Worker",
			Version:    "1.0.0",
			Capabilities: &entity.WorkerCapabilities{
				SupportedTaskTypes: []string{"test_task"},
				MaxConcurrentTasks: 5,
			},
		}
		uc.RegisterClient(ctx, input)
	}

	worker, err := uc.SelectWorker(ctx, "test_task", entity.TaskPriorityNormal)
	if err != nil {
		t.Fatalf("SelectWorker failed: %v", err)
	}

	if worker == nil {
		t.Error("Expected to select a worker")
	}
}

func TestSelectWorker_NoAvailable(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// No workers registered
	_, err := uc.SelectWorker(ctx, "test_task", entity.TaskPriorityNormal)
	if err == nil {
		t.Error("Expected error when no workers available")
	}
}

func TestUpdateWorkerStatus(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register worker
	input := RegisterInput{
		ClientID:   "worker-1",
		ClientType: entity.ClientTypeWorker,
		Name:       "Test Worker",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Update status
	err := uc.UpdateWorkerStatus(ctx, "worker-1", entity.WorkerStatusBusy)
	if err != nil {
		t.Fatalf("UpdateWorkerStatus failed: %v", err)
	}

	client, _ := uc.GetClient(ctx, "worker-1")
	if *client.Info.WorkerStatus != entity.WorkerStatusBusy {
		t.Errorf("Expected busy status, got %s", *client.Info.WorkerStatus)
	}
}

func TestProcessHeartbeat(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Process heartbeat with metrics
	metrics := map[string]any{
		"cpu":    0.5,
		"memory": 0.7,
	}

	err := uc.ProcessHeartbeat(ctx, "client-1", metrics)
	if err != nil {
		t.Fatalf("ProcessHeartbeat failed: %v", err)
	}

	client, _ := uc.GetClient(ctx, "client-1")
	if client.Info.Metrics == nil {
		t.Error("Metrics should not be nil after heartbeat")
	}
}

func TestIncrementTaskCount(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "worker-1",
		ClientType: entity.ClientTypeWorker,
		Name:       "Test Worker",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Increment completed
	err := uc.IncrementTaskCount(ctx, "worker-1", entity.TaskStatusCompleted)
	if err != nil {
		t.Fatalf("IncrementTaskCount failed: %v", err)
	}

	client, _ := uc.GetClient(ctx, "worker-1")
	if client.Info.Stats == nil || client.Info.Stats.SuccessfulTasks != 1 {
		successfulTasks := int64(0)
		if client.Info.Stats != nil {
			successfulTasks = client.Info.Stats.SuccessfulTasks
		}
		t.Errorf("Expected SuccessfulTasks 1, got %d", successfulTasks)
	}
}

func TestSetAndRemoveActiveTask(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "worker-1",
		ClientType: entity.ClientTypeWorker,
		Name:       "Test Worker",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Set active task
	err := uc.SetActiveTask(ctx, "worker-1", "task-1")
	if err != nil {
		t.Fatalf("SetActiveTask failed: %v", err)
	}

	client, _ := uc.GetClient(ctx, "worker-1")
	if len(client.ActiveTasks) != 1 {
		t.Errorf("Expected 1 active task, got %d", len(client.ActiveTasks))
	}

	// Remove active task
	err = uc.RemoveActiveTask(ctx, "worker-1", "task-1")
	if err != nil {
		t.Fatalf("RemoveActiveTask failed: %v", err)
	}

	client, _ = uc.GetClient(ctx, "worker-1")
	if len(client.ActiveTasks) != 0 {
		t.Errorf("Expected 0 active tasks, got %d", len(client.ActiveTasks))
	}
}

func TestGetStats(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register various clients
	clients := []RegisterInput{
		{ClientID: "bot-1", ClientType: entity.ClientTypeBot, Name: "Bot 1", Version: "1.0"},
		{ClientID: "bot-2", ClientType: entity.ClientTypeBot, Name: "Bot 2", Version: "1.0"},
		{ClientID: "worker-1", ClientType: entity.ClientTypeWorker, Name: "Worker 1", Version: "1.0"},
		{ClientID: "monitor-1", ClientType: entity.ClientTypeMonitor, Name: "Monitor 1", Version: "1.0"},
	}

	for _, c := range clients {
		uc.RegisterClient(ctx, c)
	}

	// Disconnect one
	uc.DisconnectClient(ctx, "bot-1", "test")

	stats, err := uc.GetStats(ctx)
	if err != nil {
		t.Fatalf("GetStats failed: %v", err)
	}

	if stats.Total != 4 {
		t.Errorf("Expected Total 4, got %d", stats.Total)
	}

	if stats.Bots != 2 {
		t.Errorf("Expected Bots 2, got %d", stats.Bots)
	}

	if stats.Workers != 1 {
		t.Errorf("Expected Workers 1, got %d", stats.Workers)
	}

	if stats.Connected != 3 {
		t.Errorf("Expected Connected 3, got %d", stats.Connected)
	}
}

func TestDeleteClient(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Delete
	err := uc.DeleteClient(ctx, "client-1")
	if err != nil {
		t.Fatalf("DeleteClient failed: %v", err)
	}

	// Verify deleted
	_, err = uc.GetClient(ctx, "client-1")
	if err == nil {
		t.Error("Client should not exist after deletion")
	}
}

func TestConnectionInfo(t *testing.T) {
	uc, _ := setupClientUseCase(t)
	ctx := context.Background()

	// Register client
	input := RegisterInput{
		ClientID:   "client-1",
		ClientType: entity.ClientTypeBot,
		Name:       "Test Bot",
		Version:    "1.0.0",
	}
	uc.RegisterClient(ctx, input)

	// Get connection info
	info := uc.GetConnectionInfo("client-1")
	if info == nil {
		t.Fatal("Connection info should not be nil")
	}

	if info.ClientID != "client-1" {
		t.Errorf("Expected ClientID client-1, got %s", info.ClientID)
	}

	// Update message stats
	uc.UpdateMessageStats("client-1", 100, 50)

	info = uc.GetConnectionInfo("client-1")
	if info.MessageCount != 1 {
		t.Errorf("Expected MessageCount 1, got %d", info.MessageCount)
	}
}
