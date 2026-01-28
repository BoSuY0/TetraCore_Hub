// Package websocket provides WebSocket handling for TetraCore Hub.
package websocket

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/infrastructure/security"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds WebSocket handler configuration.
type Config struct {
	Path              string
	Timeout           time.Duration
	HeartbeatInterval time.Duration
	MaxConnections    int
	ReadBufferSize    int
	WriteBufferSize   int
	RequireAuth       bool
}

// SessionValidator validates authentication tokens.
type SessionValidator interface {
	ValidateToken(ctx context.Context, token string) (*entity.Session, error)
}

// MessageHandler handles WebSocket messages.
type MessageHandler interface {
	HandleClientRegistration(ctx context.Context, msg entity.ClientRegistrationMessage) (*entity.Client, error)
	HandleClientDisconnect(ctx context.Context, clientID string, reason string) error
	HandleTaskSubmission(ctx context.Context, msg entity.TaskMessage, clientID string) (*entity.Task, error)
	HandleTaskResult(ctx context.Context, msg entity.TaskResultMessage) error
	HandleTaskProgress(ctx context.Context, msg entity.TaskProgressMessage) error
	HandleHeartbeat(ctx context.Context, clientID string, metrics map[string]any) error
	HandleWorkerStatusChange(ctx context.Context, clientID string, status entity.WorkerStatus) error
	IncrementMessageCount()
}

// Handler handles WebSocket connections.
type Handler struct {
	config            Config
	jwtManager        *security.JWTManager
	sessionValidator  SessionValidator
	messageHandler    MessageHandler
	connections       map[string]*Connection
	clientConnections map[string]string // clientID -> connID
	mu                sync.RWMutex
	log               logger.LogFields
}

// Connection represents a WebSocket connection.
type Connection struct {
	ID          string
	Conn        *websocket.Conn
	Client      *entity.Client
	ClientID    string
	SessionID   string
	RemoteAddr  string
	UserAgent   string
	ConnectedAt time.Time
	LastPing    time.Time
	LastPong    time.Time
	SendCh      chan []byte
	Done        chan struct{}
	mu          sync.Mutex
}

// NewHandler creates a new WebSocket handler.
func NewHandler(cfg Config, jwtManager *security.JWTManager, sessionValidator SessionValidator) *Handler {
	return &Handler{
		config:            cfg,
		jwtManager:        jwtManager,
		sessionValidator:  sessionValidator,
		connections:       make(map[string]*Connection),
		clientConnections: make(map[string]string),
		log:               logger.LogFields{"component": "websocket"},
	}
}

// SetupRoutes registers WebSocket routes.
func (h *Handler) SetupRoutes(app *fiber.App, msgHandler MessageHandler) {
	h.messageHandler = msgHandler

	// WebSocket upgrade middleware
	app.Use(h.config.Path, func(c *fiber.Ctx) error {
		if websocket.IsWebSocketUpgrade(c) {
			// Extract token from query or header
			token := c.Query("token")
			if token == "" {
				token = c.Get("Authorization")
				if len(token) > 7 && token[:7] == "Bearer " {
					token = token[7:]
				}
			}

			// Validate token if auth is required
			if h.config.RequireAuth && token == "" {
				return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
					"error": "authentication required",
				})
			}

			if token != "" {
				session, err := h.sessionValidator.ValidateToken(c.Context(), token)
				if err != nil {
					return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
						"error": "invalid token",
					})
				}
				c.Locals("session", session)
				c.Locals("sessionID", session.SessionID)
			}

			c.Locals("allowed", true)
			return c.Next()
		}
		return fiber.ErrUpgradeRequired
	})

	// WebSocket handler
	app.Get(h.config.Path, websocket.New(h.handleConnection, websocket.Config{
		ReadBufferSize:  h.config.ReadBufferSize,
		WriteBufferSize: h.config.WriteBufferSize,
	}))
}

func (h *Handler) handleConnection(c *websocket.Conn) {
	log := logger.WithFields(h.log)

	// Check connection limit
	h.mu.RLock()
	connCount := len(h.connections)
	h.mu.RUnlock()

	if h.config.MaxConnections > 0 && connCount >= h.config.MaxConnections {
		log.Warn().Msg("Max connections reached, rejecting new connection")
		c.Close()
		return
	}

	// Create connection
	conn := &Connection{
		ID:          uuid.New().String(),
		Conn:        c,
		RemoteAddr:  c.RemoteAddr().String(),
		UserAgent:   c.Headers("User-Agent"),
		ConnectedAt: time.Now().UTC(),
		SendCh:      make(chan []byte, 256),
		Done:        make(chan struct{}),
	}

	// Get session ID from locals if available
	if sessionID := c.Locals("sessionID"); sessionID != nil {
		conn.SessionID = sessionID.(string)
	}

	// Register connection
	h.mu.Lock()
	h.connections[conn.ID] = conn
	h.mu.Unlock()

	log.Info().
		Str("conn_id", conn.ID).
		Str("remote_addr", conn.RemoteAddr).
		Msg("WebSocket connection established")

	// Start goroutines for reading and writing
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go h.writePump(conn, ctx)
	go h.heartbeat(conn, ctx)

	// Read pump (main loop)
	h.readPump(conn)

	// Cleanup
	close(conn.Done)

	h.mu.Lock()
	delete(h.connections, conn.ID)
	if conn.ClientID != "" {
		delete(h.clientConnections, conn.ClientID)
	}
	h.mu.Unlock()

	// Notify disconnect
	if h.messageHandler != nil && conn.ClientID != "" {
		h.messageHandler.HandleClientDisconnect(context.Background(), conn.ClientID, "connection_closed")
	}

	log.Info().
		Str("conn_id", conn.ID).
		Str("client_id", conn.ClientID).
		Msg("WebSocket connection closed")
}

func (h *Handler) readPump(conn *Connection) {
	log := logger.WithFields(h.log)

	defer conn.Conn.Close()

	for {
		// Set read deadline
		conn.Conn.SetReadDeadline(time.Now().Add(h.config.Timeout))

		_, message, err := conn.Conn.ReadMessage()
		if err != nil {
			if websocket.IsCloseError(err, websocket.CloseNormalClosure, websocket.CloseGoingAway) {
				log.Debug().Str("conn_id", conn.ID).Msg("WebSocket closed normally")
			} else {
				log.Debug().Err(err).Str("conn_id", conn.ID).Msg("WebSocket read error")
			}
			return
		}

		// Handle message
		h.handleMessage(conn, message)
	}
}

func (h *Handler) writePump(conn *Connection, ctx context.Context) {
	log := logger.WithFields(h.log)

	for {
		select {
		case <-ctx.Done():
			return
		case <-conn.Done:
			return
		case message := <-conn.SendCh:
			conn.mu.Lock()
			conn.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			err := conn.Conn.WriteMessage(websocket.TextMessage, message)
			conn.mu.Unlock()

			if err != nil {
				log.Debug().Err(err).Str("conn_id", conn.ID).Msg("WebSocket write error")
				return
			}
		}
	}
}

func (h *Handler) heartbeat(conn *Connection, ctx context.Context) {
	ticker := time.NewTicker(h.config.HeartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-conn.Done:
			return
		case <-ticker.C:
			conn.mu.Lock()
			conn.LastPing = time.Now().UTC()
			conn.Conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			err := conn.Conn.WriteMessage(websocket.PingMessage, nil)
			conn.mu.Unlock()

			if err != nil {
				return
			}
		}
	}
}

func (h *Handler) handleMessage(conn *Connection, data []byte) {
	log := logger.WithFields(h.log).With("conn_id", conn.ID)

	if h.messageHandler != nil {
		h.messageHandler.IncrementMessageCount()
	}

	// Parse base message
	var baseMsg entity.BaseMessage
	if err := json.Unmarshal(data, &baseMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse message")
		h.sendError(conn, "PARSE_ERROR", "Invalid message format")
		return
	}

	ctx := context.Background()

	switch baseMsg.Type {
	case entity.MessageTypeClientRegistration:
		h.handleClientRegistration(ctx, conn, data)

	case entity.MessageTypeTask:
		h.handleTaskSubmission(ctx, conn, data)

	case entity.MessageTypeTaskResult:
		h.handleTaskResult(ctx, conn, data)

	case entity.MessageTypeTaskProgress:
		h.handleTaskProgress(ctx, conn, data)

	case entity.MessageTypeHeartbeat:
		h.handleHeartbeat(ctx, conn, data)

	case entity.MessageTypeWorkerStatus:
		h.handleWorkerStatus(ctx, conn, data)

	case entity.MessageTypePong:
		conn.LastPong = time.Now().UTC()

	default:
		log.Warn().Str("type", string(baseMsg.Type)).Msg("Unknown message type")
		h.sendError(conn, "UNKNOWN_TYPE", "Unknown message type: "+string(baseMsg.Type))
	}
}

func (h *Handler) handleClientRegistration(ctx context.Context, conn *Connection, data []byte) {
	log := logger.WithFields(h.log).With("conn_id", conn.ID)

	var msg entity.ClientRegistrationMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse registration message")
		h.sendError(conn, "PARSE_ERROR", "Invalid registration message")
		return
	}

	if h.messageHandler == nil {
		h.sendError(conn, "INTERNAL_ERROR", "Message handler not configured")
		return
	}

	client, err := h.messageHandler.HandleClientRegistration(ctx, msg)
	if err != nil {
		log.Warn().Err(err).Msg("Client registration failed")
		h.sendError(conn, "REGISTRATION_FAILED", err.Error())
		return
	}

	// Associate client with connection
	conn.Client = client
	conn.ClientID = client.Info.ClientID

	h.mu.Lock()
	h.clientConnections[client.Info.ClientID] = conn.ID
	h.mu.Unlock()

	// Send success response
	response := entity.ClientRegistrationResponse{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeClientRegistration,
			Timestamp: time.Now().UTC(),
		},
		Success:  true,
		ClientID: client.Info.ClientID,
		Message:  "Registration successful",
	}
	conn.Send(response)

	log.Info().
		Str("client_id", client.Info.ClientID).
		Str("type", string(client.Info.ClientType)).
		Msg("Client registered")
}

func (h *Handler) handleTaskSubmission(ctx context.Context, conn *Connection, data []byte) {
	log := logger.WithFields(h.log).With("conn_id", conn.ID)

	var msg entity.TaskMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse task message")
		h.sendError(conn, "PARSE_ERROR", "Invalid task message")
		return
	}

	if h.messageHandler == nil {
		h.sendError(conn, "INTERNAL_ERROR", "Message handler not configured")
		return
	}

	task, err := h.messageHandler.HandleTaskSubmission(ctx, msg, conn.ClientID)
	if err != nil {
		log.Warn().Err(err).Msg("Task submission failed")
		h.sendError(conn, "TASK_ERROR", err.Error())
		return
	}

	// Send acknowledgment
	ack := entity.TaskAckMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeTaskAck,
			Timestamp: time.Now().UTC(),
		},
		TaskID:  task.TaskID,
		Success: true,
		Message: "Task submitted successfully",
	}
	conn.Send(ack)

	log.Info().Str("task_id", task.TaskID).Msg("Task submitted")
}

func (h *Handler) handleTaskResult(ctx context.Context, conn *Connection, data []byte) {
	log := logger.WithFields(h.log).With("conn_id", conn.ID)

	var msg entity.TaskResultMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse result message")
		return
	}

	if h.messageHandler == nil {
		return
	}

	if err := h.messageHandler.HandleTaskResult(ctx, msg); err != nil {
		log.Warn().Err(err).Str("task_id", msg.TaskID).Msg("Failed to process task result")
	}
}

func (h *Handler) handleTaskProgress(ctx context.Context, conn *Connection, data []byte) {
	var msg entity.TaskProgressMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		return
	}

	if h.messageHandler != nil {
		_ = h.messageHandler.HandleTaskProgress(ctx, msg)
	}
}

func (h *Handler) handleHeartbeat(ctx context.Context, conn *Connection, data []byte) {
	var msg entity.HeartbeatMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		return
	}

	if h.messageHandler != nil && conn.ClientID != "" {
		_ = h.messageHandler.HandleHeartbeat(ctx, conn.ClientID, msg.Metrics)
	}

	// Send pong
	pong := entity.HeartbeatMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypePong,
			Timestamp: time.Now().UTC(),
		},
	}
	conn.Send(pong)
}

func (h *Handler) handleWorkerStatus(ctx context.Context, conn *Connection, data []byte) {
	log := logger.WithFields(h.log).With("conn_id", conn.ID)

	var msg entity.WorkerStatusMessage
	if err := json.Unmarshal(data, &msg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse worker status message")
		return
	}

	if h.messageHandler != nil && conn.ClientID != "" {
		_ = h.messageHandler.HandleWorkerStatusChange(ctx, conn.ClientID, msg.Status)
	}
}

func (h *Handler) sendError(conn *Connection, code, message string) {
	errMsg := entity.ErrorMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeError,
			Timestamp: time.Now().UTC(),
		},
		Code:    code,
		Message: message,
	}
	conn.Send(errMsg)
}

// Send sends a message through this connection.
func (c *Connection) Send(message any) error {
	var data []byte
	var err error

	switch v := message.(type) {
	case []byte:
		data = v
	case string:
		data = []byte(v)
	default:
		data, err = json.Marshal(message)
		if err != nil {
			return err
		}
	}

	select {
	case c.SendCh <- data:
		return nil
	default:
		return ErrBufferFull
	}
}

// SendToClient sends a message to a specific client (implements ConnectionManager).
func (h *Handler) SendToClient(clientID string, message any) error {
	h.mu.RLock()
	connID, exists := h.clientConnections[clientID]
	if !exists {
		h.mu.RUnlock()
		return ErrClientNotFound
	}
	conn, exists := h.connections[connID]
	h.mu.RUnlock()

	if !exists {
		return ErrConnectionNotFound
	}

	return conn.Send(message)
}

// Broadcast sends a message to all connections (implements ConnectionManager).
func (h *Handler) Broadcast(message any) error {
	h.mu.RLock()
	defer h.mu.RUnlock()

	var data []byte
	switch v := message.(type) {
	case []byte:
		data = v
	case string:
		data = []byte(v)
	default:
		var err error
		data, err = json.Marshal(message)
		if err != nil {
			return err
		}
	}

	for _, conn := range h.connections {
		select {
		case conn.SendCh <- data:
		default:
			// Skip if buffer is full
		}
	}
	return nil
}

// BroadcastToType sends a message to all connections of a specific client type (implements ConnectionManager).
func (h *Handler) BroadcastToType(clientType entity.ClientType, message any) error {
	h.mu.RLock()
	defer h.mu.RUnlock()

	var data []byte
	switch v := message.(type) {
	case []byte:
		data = v
	case string:
		data = []byte(v)
	default:
		var err error
		data, err = json.Marshal(message)
		if err != nil {
			return err
		}
	}

	for _, conn := range h.connections {
		if conn.Client != nil && conn.Client.Info.ClientType == clientType {
			select {
			case conn.SendCh <- data:
			default:
			}
		}
	}
	return nil
}

// CloseConnection closes a specific connection (implements ConnectionManager).
func (h *Handler) CloseConnection(clientID string, reason string) error {
	h.mu.Lock()
	connID, exists := h.clientConnections[clientID]
	if !exists {
		h.mu.Unlock()
		return ErrClientNotFound
	}
	conn, exists := h.connections[connID]
	if exists {
		delete(h.connections, connID)
		delete(h.clientConnections, clientID)
	}
	h.mu.Unlock()

	if !exists {
		return ErrConnectionNotFound
	}

	// Send close message
	closeMsg := entity.ErrorMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeError,
			Timestamp: time.Now().UTC(),
		},
		Code:    "CONNECTION_CLOSED",
		Message: reason,
	}
	conn.Send(closeMsg)

	return conn.Conn.Close()
}

// GetConnectedCount returns the number of connected clients (implements ConnectionManager).
func (h *Handler) GetConnectedCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	return len(h.connections)
}

// CloseAll closes all connections with a reason.
func (h *Handler) CloseAll(reason string) {
	h.mu.Lock()
	conns := make([]*Connection, 0, len(h.connections))
	for _, conn := range h.connections {
		conns = append(conns, conn)
	}
	h.connections = make(map[string]*Connection)
	h.clientConnections = make(map[string]string)
	h.mu.Unlock()

	closeMsg := entity.ErrorMessage{
		BaseMessage: entity.BaseMessage{
			Type:      entity.MessageTypeError,
			Timestamp: time.Now().UTC(),
		},
		Code:    "SERVER_SHUTDOWN",
		Message: reason,
	}
	data, _ := json.Marshal(closeMsg)

	for _, conn := range conns {
		conn.Conn.WriteMessage(websocket.TextMessage, data)
		conn.Conn.Close()
	}
}

// GetConnection retrieves a connection by ID.
func (h *Handler) GetConnection(connID string) (*Connection, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	conn, exists := h.connections[connID]
	return conn, exists
}

// GetConnectionByClientID retrieves a connection by client ID.
func (h *Handler) GetConnectionByClientID(clientID string) (*Connection, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	connID, exists := h.clientConnections[clientID]
	if !exists {
		return nil, false
	}
	conn, exists := h.connections[connID]
	return conn, exists
}

// Errors
var (
	ErrConnectionNotFound = &WebSocketError{Message: "connection not found"}
	ErrClientNotFound     = &WebSocketError{Message: "client not found"}
	ErrBufferFull         = &WebSocketError{Message: "send buffer full"}
)

// WebSocketError represents a WebSocket error.
type WebSocketError struct {
	Message string
}

func (e *WebSocketError) Error() string {
	return e.Message
}
