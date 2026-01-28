// Package websocket provides WebSocket handling for TetraCore Hub.
package websocket

import (
	"encoding/json"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/pkg/logger"
)

// MessageRouter routes incoming WebSocket messages to handlers.
type MessageRouter struct {
	handlers map[entity.MessageType]MessageHandlerFunc
	log      logger.LogFields
}

// MessageHandlerFunc is a function that handles a specific message type.
type MessageHandlerFunc func(conn *Connection, data []byte) error

// NewMessageRouter creates a new message router.
func NewMessageRouter() *MessageRouter {
	return &MessageRouter{
		handlers: make(map[entity.MessageType]MessageHandlerFunc),
		log:      logger.LogFields{"component": "ws-message-router"},
	}
}

// Register registers a handler for a message type.
func (r *MessageRouter) Register(msgType entity.MessageType, handler MessageHandlerFunc) {
	r.handlers[msgType] = handler
}

// Route routes a message to its handler.
func (r *MessageRouter) Route(conn *Connection, data []byte) error {
	log := logger.WithFields(r.log)

	// Parse base message to get type
	var baseMsg entity.BaseMessage
	if err := json.Unmarshal(data, &baseMsg); err != nil {
		log.Warn().Err(err).Msg("Failed to parse message")
		return err
	}

	// Find handler
	handler, exists := r.handlers[baseMsg.Type]
	if !exists {
		log.Warn().Str("type", string(baseMsg.Type)).Msg("No handler for message type")
		return ErrNoHandler
	}

	// Execute handler
	return handler(conn, data)
}

// HasHandler checks if a handler exists for a message type.
func (r *MessageRouter) HasHandler(msgType entity.MessageType) bool {
	_, exists := r.handlers[msgType]
	return exists
}

// Errors
var (
	ErrNoHandler = &WebSocketError{Message: "no handler for message type"}
)
