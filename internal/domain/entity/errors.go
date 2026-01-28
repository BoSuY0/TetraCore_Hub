// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"errors"

	"github.com/google/uuid"
)

// GenerateID generates a new unique identifier.
func GenerateID() string {
	return uuid.New().String()
}

// Domain error definitions.
var (
	// Client errors
	ErrClientNotFound      = errors.New("client not found")
	ErrClientAlreadyExists = errors.New("client already exists")
	ErrClientDisconnected  = errors.New("client is disconnected")

	// Task errors
	ErrTaskNotFound      = errors.New("task not found")
	ErrTaskAlreadyExists = errors.New("task already exists")
	ErrTaskCompleted     = errors.New("task is already completed")
	ErrTaskCancelled     = errors.New("task is already cancelled")

	// Session errors
	ErrSessionNotFound = errors.New("session not found")
	ErrSessionExpired  = errors.New("session has expired")
	ErrSessionInvalid  = errors.New("session is invalid")

	// Authentication errors
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrTokenExpired       = errors.New("token has expired")
	ErrTokenInvalid       = errors.New("token is invalid")
	ErrUnauthorized       = errors.New("unauthorized")

	// General errors
	ErrInvalidInput = errors.New("invalid input")
	ErrNotFound     = errors.New("not found")
	ErrConflict     = errors.New("conflict")
)
