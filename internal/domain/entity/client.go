// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"sync"
	"time"

	"github.com/google/uuid"
)

// ClientType represents the type of client in the system.
type ClientType string

const (
	ClientTypeBot       ClientType = "bot"
	ClientTypeWorker    ClientType = "worker"
	ClientTypeWorkerAPI ClientType = "worker_api"
	ClientTypeStreamHub ClientType = "stream_hub"
	ClientTypeMonitor   ClientType = "monitor"
	ClientTypeAdmin     ClientType = "admin"
)

// ConnectionStatus represents the client's connection state.
type ConnectionStatus string

const (
	ConnectionStatusConnected    ConnectionStatus = "connected"
	ConnectionStatusDisconnected ConnectionStatus = "disconnected"
	ConnectionStatusConnecting   ConnectionStatus = "connecting"
	ConnectionStatusReconnecting ConnectionStatus = "reconnecting"
	ConnectionStatusError        ConnectionStatus = "error"
)

// WorkerStatus represents the worker's operational state.
type WorkerStatus string

const (
	WorkerStatusIdle        WorkerStatus = "idle"
	WorkerStatusBusy        WorkerStatus = "busy"
	WorkerStatusOverloaded  WorkerStatus = "overloaded"
	WorkerStatusMaintenance WorkerStatus = "maintenance"
	WorkerStatusError       WorkerStatus = "error"
)

// WorkerCapabilities describes what a worker can do.
type WorkerCapabilities struct {
	SupportedTaskTypes    []string `json:"supported_task_types"`
	MaxConcurrentTasks    int      `json:"max_concurrent_tasks"`
	AverageProcessingTime float64  `json:"average_processing_time"`
	MaxTaskSize           int64    `json:"max_task_size"`
	SupportedFormats      []string `json:"supported_formats"`
	SpecialCapabilities   []string `json:"special_capabilities"`
	APIVersion            string   `json:"api_version"`
	MinPriority           string   `json:"min_priority"`
	MaxPriority           string   `json:"max_priority"`
}

// NewWorkerCapabilities creates default worker capabilities.
func NewWorkerCapabilities() *WorkerCapabilities {
	return &WorkerCapabilities{
		SupportedTaskTypes:    []string{},
		MaxConcurrentTasks:    1,
		AverageProcessingTime: 0.0,
		MaxTaskSize:           1024 * 1024, // 1MB
		SupportedFormats:      []string{"json"},
		SpecialCapabilities:   []string{},
		APIVersion:            "1.0.0",
		MinPriority:           "low",
		MaxPriority:           "critical",
	}
}

// ClientStats holds client statistics.
type ClientStats struct {
	TotalTasks            int64              `json:"total_tasks"`
	SuccessfulTasks       int64              `json:"successful_tasks"`
	FailedTasks           int64              `json:"failed_tasks"`
	TimeoutTasks          int64              `json:"timeout_tasks"`
	ActiveTasks           int                `json:"active_tasks"`
	AverageProcessingTime float64            `json:"average_processing_time"`
	LastActivity          time.Time          `json:"last_activity"`
	ConnectedAt           time.Time          `json:"connected_at"`
	TotalConnectionTime   float64            `json:"total_connection_time"`
	DisconnectionCount    int                `json:"disconnection_count"`
	ErrorStats            map[string]int     `json:"error_stats"`
	ResourceUsage         map[string]float64 `json:"resource_usage"`
}

// NewClientStats creates new client statistics.
func NewClientStats() *ClientStats {
	now := time.Now().UTC()
	return &ClientStats{
		LastActivity:  now,
		ConnectedAt:   now,
		ErrorStats:    make(map[string]int),
		ResourceUsage: make(map[string]float64),
	}
}

// ClientInfo contains client metadata and state.
type ClientInfo struct {
	ClientID         string              `json:"client_id"`
	ClientType       ClientType          `json:"client_type"`
	ClientName       string              `json:"client_name"`
	ClientVersion    string              `json:"client_version"`
	ConnectionStatus ConnectionStatus    `json:"connection_status"`
	SessionID        string              `json:"session_id,omitempty"`
	RemoteAddress    string              `json:"remote_address,omitempty"`
	UserAgent        string              `json:"user_agent,omitempty"`
	RegisteredAt     time.Time           `json:"registered_at"`
	LastSeen         time.Time           `json:"last_seen"`
	LastPing         *time.Time          `json:"last_ping,omitempty"`
	LastPong         *time.Time          `json:"last_pong,omitempty"`
	Capabilities     *WorkerCapabilities `json:"capabilities,omitempty"`
	WorkerStatus     *WorkerStatus       `json:"worker_status,omitempty"`
	CurrentLoad      int                 `json:"current_load"`
	Stats            *ClientStats        `json:"stats"`
	Config           map[string]any      `json:"config"`
	Metadata         map[string]any      `json:"metadata"`
	Metrics          map[string]any      `json:"metrics"`
	Tags             []string            `json:"tags"`
	ReconnectCount   int                 `json:"reconnect_count"`
	DisconnectReason string              `json:"disconnect_reason,omitempty"`
}

// NewClientInfo creates new client info with defaults.
func NewClientInfo(clientID string, clientType ClientType, clientName string) *ClientInfo {
	now := time.Now().UTC()
	return &ClientInfo{
		ClientID:         clientID,
		ClientType:       clientType,
		ClientName:       clientName,
		ClientVersion:    "1.0.0",
		ConnectionStatus: ConnectionStatusDisconnected,
		RegisteredAt:     now,
		LastSeen:         now,
		Stats:            NewClientStats(),
		Config:           make(map[string]any),
		Metadata:         make(map[string]any),
		Metrics:          make(map[string]any),
		Tags:             []string{},
	}
}

// IsConnected checks if the client is connected.
func (c *ClientInfo) IsConnected() bool {
	return c.ConnectionStatus == ConnectionStatusConnected
}

// IsWorker checks if the client is a worker type.
func (c *ClientInfo) IsWorker() bool {
	return c.ClientType == ClientTypeWorker || c.ClientType == ClientTypeWorkerAPI
}

// IsBot checks if the client is a bot.
func (c *ClientInfo) IsBot() bool {
	return c.ClientType == ClientTypeBot
}

// CanExecuteTasks checks if the client can execute tasks.
func (c *ClientInfo) CanExecuteTasks() bool {
	if c.ClientType == ClientTypeMonitor || c.ClientType == ClientTypeAdmin {
		return false
	}
	return c.Capabilities != nil && len(c.Capabilities.SupportedTaskTypes) > 0
}

// CanHandleTask checks if the client can handle a specific task type.
func (c *ClientInfo) CanHandleTask(taskType string) bool {
	if !c.CanExecuteTasks() {
		return false
	}
	for _, t := range c.Capabilities.SupportedTaskTypes {
		if t == taskType {
			return true
		}
	}
	return false
}

// IsAvailable checks if the client is available for new tasks.
func (c *ClientInfo) IsAvailable() bool {
	if !c.CanExecuteTasks() || !c.IsConnected() {
		return false
	}
	if c.IsWorker() && c.WorkerStatus != nil {
		status := *c.WorkerStatus
		if status == WorkerStatusMaintenance || status == WorkerStatusError {
			return false
		}
	}
	return c.Stats.ActiveTasks < c.Capabilities.MaxConcurrentTasks
}

// GetLoadPercentage returns the load percentage.
func (c *ClientInfo) GetLoadPercentage() float64 {
	if !c.CanExecuteTasks() || c.Capabilities.MaxConcurrentTasks == 0 {
		return 0.0
	}
	return float64(c.Stats.ActiveTasks) / float64(c.Capabilities.MaxConcurrentTasks) * 100
}

// GetCurrentLoad returns the current load (number of active tasks).
func (c *ClientInfo) GetCurrentLoad() int {
	return c.Stats.ActiveTasks
}

// Client represents a connected client with WebSocket connection.
type Client struct {
	Info              *ClientInfo          `json:"info"`
	TaskQueue         []string             `json:"task_queue"`
	ActiveTasks       map[string]time.Time `json:"active_tasks"`
	TaskHistory       []map[string]any     `json:"task_history"`

	// Non-serialized fields
	mu               sync.RWMutex
	securityClientID string
}

// NewClient creates a new client with the given parameters.
func NewClient(clientID string, clientType ClientType, name, version string) *Client {
	info := NewClientInfo(clientID, clientType, name)
	info.ClientVersion = version
	info.ConnectionStatus = ConnectionStatusConnected
	return &Client{
		Info:        info,
		TaskQueue:   []string{},
		ActiveTasks: make(map[string]time.Time),
		TaskHistory: []map[string]any{},
	}
}

// NewClientFromInfo creates a new client from existing info.
func NewClientFromInfo(info *ClientInfo) *Client {
	return &Client{
		Info:        info,
		TaskQueue:   []string{},
		ActiveTasks: make(map[string]time.Time),
		TaskHistory: []map[string]any{},
	}
}

// CreateBot creates a bot client.
func CreateBot(clientID, clientName string, capabilities *WorkerCapabilities) *Client {
	info := NewClientInfo(clientID, ClientTypeBot, clientName)
	info.Capabilities = capabilities
	return NewClientFromInfo(info)
}

// CreateWorker creates a worker client.
func CreateWorker(clientID, clientName string, capabilities *WorkerCapabilities) *Client {
	info := NewClientInfo(clientID, ClientTypeWorker, clientName)
	info.Capabilities = capabilities
	status := WorkerStatusIdle
	info.WorkerStatus = &status
	return NewClientFromInfo(info)
}

// CreateWorkerAPI creates a worker API client.
func CreateWorkerAPI(clientID, clientName string, capabilities *WorkerCapabilities) *Client {
	info := NewClientInfo(clientID, ClientTypeWorkerAPI, clientName)
	info.Capabilities = capabilities
	status := WorkerStatusIdle
	info.WorkerStatus = &status
	return NewClientFromInfo(info)
}

// CreateMonitor creates a monitor client.
func CreateMonitor(clientID, clientName string) *Client {
	info := NewClientInfo(clientID, ClientTypeMonitor, clientName)
	return NewClientFromInfo(info)
}

// CreateAdmin creates an admin client.
func CreateAdmin(clientID, clientName string) *Client {
	info := NewClientInfo(clientID, ClientTypeAdmin, clientName)
	return NewClientFromInfo(info)
}

// Connect marks the client as connected.
func (c *Client) Connect(sessionID string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.Info.ConnectionStatus = ConnectionStatusConnected
	if sessionID == "" {
		sessionID = uuid.New().String()
	}
	c.Info.SessionID = sessionID
	c.Info.Stats.ConnectedAt = time.Now().UTC()
}

// Disconnect marks the client as disconnected.
func (c *Client) Disconnect() {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.Info.ConnectionStatus = ConnectionStatusDisconnected
	c.Info.Stats.DisconnectionCount++

	// Update total connection time
	connectionTime := time.Since(c.Info.Stats.ConnectedAt).Seconds()
	c.Info.Stats.TotalConnectionTime += connectionTime
}

// AssignTask assigns a task to the client.
func (c *Client) AssignTask(taskID string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()

	if !c.Info.CanExecuteTasks() {
		return false
	}

	if c.Info.Stats.ActiveTasks >= c.Info.Capabilities.MaxConcurrentTasks {
		return false
	}

	c.ActiveTasks[taskID] = time.Now().UTC()
	c.Info.Stats.ActiveTasks = len(c.ActiveTasks)
	c.Info.Stats.TotalTasks++
	c.Info.Stats.LastActivity = time.Now().UTC()

	return true
}

// ReleaseTask releases a task from the client.
func (c *Client) ReleaseTask(taskID string) bool {
	c.mu.Lock()
	defer c.mu.Unlock()

	if _, exists := c.ActiveTasks[taskID]; exists {
		delete(c.ActiveTasks, taskID)
		c.Info.Stats.ActiveTasks = len(c.ActiveTasks)
		c.Info.Stats.LastActivity = time.Now().UTC()
		return true
	}
	return false
}

// CompleteTask marks a task as completed and updates stats.
func (c *Client) CompleteTask(taskID string, status TaskStatus, executionTime float64) {
	c.mu.Lock()
	defer c.mu.Unlock()

	startTime, exists := c.ActiveTasks[taskID]
	if !exists {
		return
	}

	delete(c.ActiveTasks, taskID)
	c.Info.Stats.ActiveTasks = len(c.ActiveTasks)

	// Calculate execution time if not provided
	if executionTime == 0 {
		executionTime = time.Since(startTime).Seconds() * 1000 // Convert to milliseconds
	}

	// Update stats based on status
	switch status {
	case TaskStatusCompleted:
		c.Info.Stats.SuccessfulTasks++
	case TaskStatusFailed:
		c.Info.Stats.FailedTasks++
	case TaskStatusTimeout:
		c.Info.Stats.TimeoutTasks++
	}

	// Update average processing time
	totalTime := c.Info.Stats.AverageProcessingTime*float64(c.Info.Stats.TotalTasks-1) + executionTime
	c.Info.Stats.AverageProcessingTime = totalTime / float64(c.Info.Stats.TotalTasks)

	// Add to history
	historyEntry := map[string]any{
		"task_id":        taskID,
		"status":         string(status),
		"execution_time": executionTime,
		"completed_at":   time.Now().UTC().Format(time.RFC3339),
	}
	c.TaskHistory = append(c.TaskHistory, historyEntry)

	// Limit history size
	if len(c.TaskHistory) > 100 {
		c.TaskHistory = c.TaskHistory[len(c.TaskHistory)-100:]
	}
}

// Ping records a ping sent to the client.
func (c *Client) Ping() {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now().UTC()
	c.Info.LastPing = &now
}

// Pong records a pong received from the client.
func (c *Client) Pong() {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now().UTC()
	c.Info.LastPong = &now
}

// IsHealthy checks if the client is healthy (has responded to pings).
func (c *Client) IsHealthy(timeout time.Duration) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()

	if !c.Info.IsConnected() {
		return false
	}

	if c.Info.LastPong != nil {
		return time.Since(*c.Info.LastPong) < timeout
	}

	return true
}

// ToMap converts the client to a map for JSON serialization.
func (c *Client) ToMap() map[string]any {
	c.mu.RLock()
	defer c.mu.RUnlock()

	var lastPing, lastPong, registeredAt *string
	if c.Info.LastPing != nil {
		s := c.Info.LastPing.Format(time.RFC3339)
		lastPing = &s
	}
	if c.Info.LastPong != nil {
		s := c.Info.LastPong.Format(time.RFC3339)
		lastPong = &s
	}
	s := c.Info.RegisteredAt.Format(time.RFC3339)
	registeredAt = &s

	var workerStatus *string
	if c.Info.WorkerStatus != nil {
		ws := string(*c.Info.WorkerStatus)
		workerStatus = &ws
	}

	return map[string]any{
		"client_id":         c.Info.ClientID,
		"client_type":       string(c.Info.ClientType),
		"client_name":       c.Info.ClientName,
		"client_version":    c.Info.ClientVersion,
		"connection_status": string(c.Info.ConnectionStatus),
		"worker_status":     workerStatus,
		"current_load":      c.Info.GetLoadPercentage(),
		"remote_address":    c.Info.RemoteAddress,
		"session_id":        c.Info.SessionID,
		"last_ping":         lastPing,
		"last_pong":         lastPong,
		"registered_at":     registeredAt,
		"stats": map[string]any{
			"total_tasks":             c.Info.Stats.TotalTasks,
			"successful_tasks":        c.Info.Stats.SuccessfulTasks,
			"failed_tasks":            c.Info.Stats.FailedTasks,
			"timeout_tasks":           c.Info.Stats.TimeoutTasks,
			"active_tasks":            c.Info.Stats.ActiveTasks,
			"average_processing_time": c.Info.Stats.AverageProcessingTime,
			"disconnection_count":     c.Info.Stats.DisconnectionCount,
		},
		"capabilities":       c.Info.Capabilities,
		"active_tasks_count": len(c.ActiveTasks),
		"is_healthy":         c.IsHealthy(60 * time.Second),
		"metadata":           c.Info.Metadata,
		"config":             c.Info.Config,
		"tags":               c.Info.Tags,
	}
}
