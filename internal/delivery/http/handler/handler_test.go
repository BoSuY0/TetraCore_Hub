// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"encoding/json"
	"io"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// Mock implementations for testing

// mockClientService implements ClientService for testing.
type mockClientService struct {
	clients []*entity.Client
	stats   *ClientStats
	err     error
}

func (m *mockClientService) GetClient(ctx context.Context, clientID string) (*entity.Client, error) {
	if m.err != nil {
		return nil, m.err
	}
	for _, c := range m.clients {
		if c.Info.ClientID == clientID {
			return c, nil
		}
	}
	return nil, entity.ErrClientNotFound
}

func (m *mockClientService) GetAllClients(ctx context.Context) ([]*entity.Client, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.clients, nil
}

func (m *mockClientService) GetClientsByType(ctx context.Context, clientType entity.ClientType) ([]*entity.Client, error) {
	if m.err != nil {
		return nil, m.err
	}
	var result []*entity.Client
	for _, c := range m.clients {
		if c.Info.ClientType == clientType {
			result = append(result, c)
		}
	}
	return result, nil
}

func (m *mockClientService) GetConnectedClients(ctx context.Context) ([]*entity.Client, error) {
	if m.err != nil {
		return nil, m.err
	}
	var result []*entity.Client
	for _, c := range m.clients {
		if c.Info.ConnectionStatus == entity.ConnectionStatusConnected {
			result = append(result, c)
		}
	}
	return result, nil
}

func (m *mockClientService) DisconnectClient(ctx context.Context, clientID string, reason string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockClientService) DeleteClient(ctx context.Context, clientID string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockClientService) GetStats(ctx context.Context) (*ClientStats, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.stats, nil
}

// mockTaskService implements TaskService for testing.
type mockTaskService struct {
	tasks []*entity.Task
	stats *TaskStatsResponse
	err   error
}

func (m *mockTaskService) SubmitTask(ctx context.Context, input TaskSubmitInput) (*entity.Task, error) {
	if m.err != nil {
		return nil, m.err
	}
	task := entity.CreateTask(input.TaskType, input.Payload)
	m.tasks = append(m.tasks, task)
	return task, nil
}

func (m *mockTaskService) GetTask(ctx context.Context, taskID string) (*entity.Task, error) {
	if m.err != nil {
		return nil, m.err
	}
	for _, t := range m.tasks {
		if t.TaskID == taskID {
			return t, nil
		}
	}
	return nil, entity.ErrTaskNotFound
}

func (m *mockTaskService) GetAllTasks(ctx context.Context, limit, offset int) ([]*entity.Task, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.tasks, nil
}

func (m *mockTaskService) GetTasksByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error) {
	if m.err != nil {
		return nil, m.err
	}
	var result []*entity.Task
	for _, t := range m.tasks {
		if t.Context.CurrentStatus == status {
			result = append(result, t)
		}
	}
	return result, nil
}

func (m *mockTaskService) GetTasksByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error) {
	if m.err != nil {
		return nil, m.err
	}
	var result []*entity.Task
	for _, t := range m.tasks {
		if t.TaskType == taskType {
			result = append(result, t)
		}
	}
	return result, nil
}

func (m *mockTaskService) CancelTask(ctx context.Context, taskID string, reason string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockTaskService) RetryTask(ctx context.Context, taskID string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockTaskService) DeleteTask(ctx context.Context, taskID string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockTaskService) GetStats(ctx context.Context) (*TaskStatsResponse, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.stats, nil
}

// mockSessionService implements SessionService for testing.
type mockSessionService struct {
	sessions []*entity.Session
	count    int64
	err      error
}

func (m *mockSessionService) GetSession(ctx context.Context, sessionID string) (*entity.Session, error) {
	if m.err != nil {
		return nil, m.err
	}
	for _, s := range m.sessions {
		if s.SessionID == sessionID {
			return s, nil
		}
	}
	return nil, entity.ErrSessionNotFound
}

func (m *mockSessionService) GetAllSessions(ctx context.Context) ([]*entity.Session, error) {
	if m.err != nil {
		return nil, m.err
	}
	return m.sessions, nil
}

func (m *mockSessionService) GetSessionsByUser(ctx context.Context, userID string) ([]*entity.Session, error) {
	if m.err != nil {
		return nil, m.err
	}
	var result []*entity.Session
	for _, s := range m.sessions {
		if s.UserID == userID {
			result = append(result, s)
		}
	}
	return result, nil
}

func (m *mockSessionService) InvalidateSession(ctx context.Context, sessionID string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockSessionService) InvalidateUserSessions(ctx context.Context, userID string) error {
	if m.err != nil {
		return m.err
	}
	return nil
}

func (m *mockSessionService) GetSessionCount(ctx context.Context) (int64, error) {
	if m.err != nil {
		return 0, m.err
	}
	return m.count, nil
}

// Helper function to create a test client
func createTestClient(id string, clientType entity.ClientType) *entity.Client {
	return entity.NewClient(id, clientType, "Test Client", "1.0.0")
}

// Helper function to create a test task
func createTestTask(taskType entity.TaskType) *entity.Task {
	return entity.CreateTask(taskType, map[string]any{"test": true},
		entity.WithExecutorType(entity.ExecutorTypeWorker),
		entity.WithPriority(entity.TaskPriorityNormal))
}

// Helper function to create a test session
func createTestSession(userID, username, role string) *entity.Session {
	return entity.NewSession(userID, username, role, time.Hour)
}

// Client Handler Tests

func TestClientHandler_GetClients(t *testing.T) {
	app := fiber.New()
	mockService := &mockClientService{
		clients: []*entity.Client{
			createTestClient("client-1", entity.ClientTypeBot),
			createTestClient("client-2", entity.ClientTypeWorker),
		},
	}
	handler := NewClientHandler(mockService)
	app.Get("/clients", handler.GetClients)

	req := httptest.NewRequest("GET", "/clients", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var result map[string]any
	json.Unmarshal(body, &result)

	total := int(result["total"].(float64))
	if total != 2 {
		t.Errorf("Expected 2 clients, got %d", total)
	}
}

func TestClientHandler_GetClient(t *testing.T) {
	app := fiber.New()
	testClient := createTestClient("client-1", entity.ClientTypeBot)
	mockService := &mockClientService{
		clients: []*entity.Client{testClient},
	}
	handler := NewClientHandler(mockService)
	app.Get("/clients/:id", handler.GetClient)

	req := httptest.NewRequest("GET", "/clients/client-1", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestClientHandler_GetClient_NotFound(t *testing.T) {
	app := fiber.New()
	mockService := &mockClientService{clients: []*entity.Client{}}
	handler := NewClientHandler(mockService)
	app.Get("/clients/:id", handler.GetClient)

	req := httptest.NewRequest("GET", "/clients/nonexistent", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusNotFound {
		t.Errorf("Expected status 404, got %d", resp.StatusCode)
	}
}

func TestClientHandler_DeleteClient(t *testing.T) {
	app := fiber.New()
	mockService := &mockClientService{
		clients: []*entity.Client{createTestClient("client-1", entity.ClientTypeBot)},
	}
	handler := NewClientHandler(mockService)
	app.Delete("/clients/:id", handler.DeleteClient)

	req := httptest.NewRequest("DELETE", "/clients/client-1", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestClientHandler_GetClientStats(t *testing.T) {
	app := fiber.New()
	mockService := &mockClientService{
		stats: &ClientStats{
			Total:        10,
			Bots:         5,
			Workers:      3,
			Connected:    8,
			Disconnected: 2,
		},
	}
	handler := NewClientHandler(mockService)
	app.Get("/clients/stats", handler.GetClientStats)

	req := httptest.NewRequest("GET", "/clients/stats", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var stats ClientStats
	json.Unmarshal(body, &stats)

	if stats.Total != 10 {
		t.Errorf("Expected total 10, got %d", stats.Total)
	}
}

// Task Handler Tests

func TestTaskHandler_GetTasks(t *testing.T) {
	app := fiber.New()
	mockService := &mockTaskService{
		tasks: []*entity.Task{
			createTestTask(entity.TaskTypeAPIRequest),
			createTestTask(entity.TaskTypeDataProcessing),
		},
	}
	handler := NewTaskHandler(mockService)
	app.Get("/tasks", handler.GetTasks)

	req := httptest.NewRequest("GET", "/tasks", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var result map[string]any
	json.Unmarshal(body, &result)

	total := int(result["total"].(float64))
	if total != 2 {
		t.Errorf("Expected 2 tasks, got %d", total)
	}
}

func TestTaskHandler_CreateTask(t *testing.T) {
	app := fiber.New()
	mockService := &mockTaskService{tasks: []*entity.Task{}}
	handler := NewTaskHandler(mockService)
	app.Post("/tasks", handler.SubmitTask)

	payload := `{"task_type":"api_request","priority":"normal","payload":{"url":"https://example.com"}}`
	req := httptest.NewRequest("POST", "/tasks", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")

	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusCreated {
		t.Errorf("Expected status 201, got %d", resp.StatusCode)
	}
}

func TestTaskHandler_CreateTask_MissingType(t *testing.T) {
	app := fiber.New()
	mockService := &mockTaskService{tasks: []*entity.Task{}}
	handler := NewTaskHandler(mockService)
	app.Post("/tasks", handler.SubmitTask)

	payload := `{"priority":"normal"}`
	req := httptest.NewRequest("POST", "/tasks", strings.NewReader(payload))
	req.Header.Set("Content-Type", "application/json")

	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusBadRequest {
		t.Errorf("Expected status 400, got %d", resp.StatusCode)
	}
}

func TestTaskHandler_GetTask(t *testing.T) {
	app := fiber.New()
	testTask := createTestTask(entity.TaskTypeAPIRequest)
	mockService := &mockTaskService{tasks: []*entity.Task{testTask}}
	handler := NewTaskHandler(mockService)
	app.Get("/tasks/:id", handler.GetTask)

	req := httptest.NewRequest("GET", "/tasks/"+testTask.TaskID, nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestTaskHandler_DeleteTask(t *testing.T) {
	app := fiber.New()
	mockService := &mockTaskService{tasks: []*entity.Task{createTestTask(entity.TaskTypeAPIRequest)}}
	handler := NewTaskHandler(mockService)
	app.Delete("/tasks/:id", handler.DeleteTask)

	req := httptest.NewRequest("DELETE", "/tasks/task-1", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestTaskHandler_GetTaskStats(t *testing.T) {
	app := fiber.New()
	mockService := &mockTaskService{
		stats: &TaskStatsResponse{
			TotalTasks:        100,
			PendingTasks:      10,
			ProcessingTasks:   5,
			CompletedTasks:    80,
			FailedTasks:       5,
			TasksByType:       map[string]int64{"api_request": 50, "data_processing": 50},
			AvgProcessingTime: 150.5,
		},
	}
	handler := NewTaskHandler(mockService)
	app.Get("/tasks/stats", handler.GetTaskStats)

	req := httptest.NewRequest("GET", "/tasks/stats", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var stats TaskStatsResponse
	json.Unmarshal(body, &stats)

	if stats.TotalTasks != 100 {
		t.Errorf("Expected total 100, got %d", stats.TotalTasks)
	}
}

// Session Handler Tests

func TestSessionHandler_GetSessions(t *testing.T) {
	app := fiber.New()
	mockService := &mockSessionService{
		sessions: []*entity.Session{
			createTestSession("user-1", "testuser1", "admin"),
			createTestSession("user-2", "testuser2", "user"),
		},
	}
	handler := NewSessionHandler(mockService)
	app.Get("/sessions", handler.GetSessions)

	req := httptest.NewRequest("GET", "/sessions", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var result map[string]any
	json.Unmarshal(body, &result)

	total := int(result["total"].(float64))
	if total != 2 {
		t.Errorf("Expected 2 sessions, got %d", total)
	}
}

func TestSessionHandler_GetSession(t *testing.T) {
	app := fiber.New()
	testSession := createTestSession("user-1", "testuser", "admin")
	mockService := &mockSessionService{sessions: []*entity.Session{testSession}}
	handler := NewSessionHandler(mockService)
	app.Get("/sessions/:id", handler.GetSession)

	req := httptest.NewRequest("GET", "/sessions/"+testSession.SessionID, nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestSessionHandler_DeleteSession(t *testing.T) {
	app := fiber.New()
	mockService := &mockSessionService{
		sessions: []*entity.Session{createTestSession("user-1", "testuser", "admin")},
	}
	handler := NewSessionHandler(mockService)
	app.Delete("/sessions/:id", handler.DeleteSession)

	req := httptest.NewRequest("DELETE", "/sessions/session-1", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}
}

func TestSessionHandler_GetSessionStats(t *testing.T) {
	app := fiber.New()
	mockService := &mockSessionService{count: 25}
	handler := NewSessionHandler(mockService)
	app.Get("/sessions/stats", handler.GetSessionStats)

	req := httptest.NewRequest("GET", "/sessions/stats", nil)
	resp, err := app.Test(req)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if resp.StatusCode != fiber.StatusOK {
		t.Errorf("Expected status 200, got %d", resp.StatusCode)
	}

	body, _ := io.ReadAll(resp.Body)
	var result map[string]any
	json.Unmarshal(body, &result)

	totalSessions := int(result["total_sessions"].(float64))
	if totalSessions != 25 {
		t.Errorf("Expected total_sessions 25, got %d", totalSessions)
	}
}

// Response conversion tests

func TestClientToResponse(t *testing.T) {
	client := createTestClient("client-1", entity.ClientTypeBot)
	client.Info.Stats.TotalTasks = 100
	client.Info.Stats.SuccessfulTasks = 90

	resp := clientToResponse(client)

	if resp.ClientID != "client-1" {
		t.Errorf("Expected ClientID 'client-1', got '%s'", resp.ClientID)
	}

	if resp.ClientType != "bot" {
		t.Errorf("Expected ClientType 'bot', got '%s'", resp.ClientType)
	}

	if resp.ConnectionStatus != "connected" {
		t.Errorf("Expected ConnectionStatus 'connected', got '%s'", resp.ConnectionStatus)
	}
}

func TestTaskToResponse(t *testing.T) {
	task := createTestTask(entity.TaskTypeAPIRequest)
	task.Context.WorkerID = "worker-1"

	resp := taskToResponse(task)

	if resp.TaskID != task.TaskID {
		t.Errorf("Expected TaskID '%s', got '%s'", task.TaskID, resp.TaskID)
	}

	if resp.TaskType != "api_request" {
		t.Errorf("Expected TaskType 'api_request', got '%s'", resp.TaskType)
	}

	if resp.Status != "pending" {
		t.Errorf("Expected Status 'pending', got '%s'", resp.Status)
	}

	if resp.WorkerID != "worker-1" {
		t.Errorf("Expected WorkerID 'worker-1', got '%s'", resp.WorkerID)
	}
}

func TestSessionToResponse(t *testing.T) {
	session := createTestSession("user-1", "testuser", "admin")
	session.IPAddress = "192.168.1.1"

	resp := sessionToResponse(session)

	if resp.SessionID != session.SessionID {
		t.Errorf("Expected SessionID '%s', got '%s'", session.SessionID, resp.SessionID)
	}

	if resp.UserID != "user-1" {
		t.Errorf("Expected UserID 'user-1', got '%s'", resp.UserID)
	}

	if resp.Username != "testuser" {
		t.Errorf("Expected Username 'testuser', got '%s'", resp.Username)
	}

	if resp.Role != "admin" {
		t.Errorf("Expected Role 'admin', got '%s'", resp.Role)
	}

	if resp.IPAddress != "192.168.1.1" {
		t.Errorf("Expected IPAddress '192.168.1.1', got '%s'", resp.IPAddress)
	}
}
