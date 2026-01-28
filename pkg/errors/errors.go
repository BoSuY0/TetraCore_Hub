// Package errors provides custom error types for TetraCore Hub.
package errors

import (
	"errors"
	"fmt"
)

// ErrorCode represents error type codes.
type ErrorCode string

const (
	CodeUnauthorized    ErrorCode = "UNAUTHORIZED"
	CodeNotFound        ErrorCode = "NOT_FOUND"
	CodeConflict        ErrorCode = "CONFLICT"
	CodeValidation      ErrorCode = "VALIDATION"
	CodeInternalServer  ErrorCode = "INTERNAL_SERVER"
	CodeTimeout         ErrorCode = "TIMEOUT"
	CodeRateLimited     ErrorCode = "RATE_LIMITED"
)

// TypedError is an error with chainable methods.
type TypedError struct {
	Code    ErrorCode
	Message string
	cause   error
}

func (e *TypedError) Error() string {
	if e.cause != nil {
		return fmt.Sprintf("%s: %v", e.Message, e.cause)
	}
	return e.Message
}

func (e *TypedError) Unwrap() error {
	return e.cause
}

// With creates a new error with additional message context.
func (e *TypedError) With(msg string) *TypedError {
	return &TypedError{
		Code:    e.Code,
		Message: msg,
		cause:   e,
	}
}

// Wrap wraps an underlying error.
func (e *TypedError) Wrap(err error, msg string) *TypedError {
	return &TypedError{
		Code:    e.Code,
		Message: msg,
		cause:   err,
	}
}

// Typed error constants
var (
	// Common typed errors
	ErrNotFound       = &TypedError{Code: CodeNotFound, Message: "not found"}
	ErrConflict       = &TypedError{Code: CodeConflict, Message: "conflict"}
	ErrUnauthorized   = &TypedError{Code: CodeUnauthorized, Message: "unauthorized"}
	ErrValidation     = &TypedError{Code: CodeValidation, Message: "validation error"}
	ErrInternalServer = &TypedError{Code: CodeInternalServer, Message: "internal server error"}
	ErrTimeout        = &TypedError{Code: CodeTimeout, Message: "timeout"}
	ErrRateLimited    = &TypedError{Code: CodeRateLimited, Message: "rate limit exceeded"}
)

// Standard errors (for compatibility)
var (
	// Authentication errors
	ErrInvalidToken      = errors.New("invalid token")
	ErrTokenExpired      = errors.New("token expired")
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrSessionNotFound   = errors.New("session not found")
	ErrSessionExpired    = errors.New("session expired")
	ErrTooManyAttempts   = errors.New("too many login attempts")

	// Client errors
	ErrClientNotFound     = errors.New("client not found")
	ErrClientAlreadyExists = errors.New("client already exists")
	ErrClientDisconnected = errors.New("client disconnected")
	ErrInvalidClientType  = errors.New("invalid client type")
	ErrMaxConnectionsReached = errors.New("maximum connections reached")

	// Task errors
	ErrTaskNotFound       = errors.New("task not found")
	ErrTaskAlreadyExists  = errors.New("task already exists")
	ErrTaskTimeout        = errors.New("task timeout")
	ErrNoWorkersAvailable = errors.New("no workers available")
	ErrTaskCancelled      = errors.New("task cancelled")
	ErrInvalidTaskStatus  = errors.New("invalid task status")
	ErrMaxRetriesExceeded = errors.New("max retries exceeded")

	// Redis errors
	ErrRedisConnection    = errors.New("redis connection failed")
	ErrRedisTimeout       = errors.New("redis operation timeout")
	ErrRedisKeyNotFound   = errors.New("redis key not found")

	// WebSocket errors
	ErrWebSocketClosed    = errors.New("websocket connection closed")
	ErrWebSocketUpgrade   = errors.New("websocket upgrade failed")
	ErrInvalidMessage     = errors.New("invalid message format")

	// Validation errors
	ErrMissingField       = errors.New("missing required field")
	ErrInvalidFormat      = errors.New("invalid format")

	// Rate limiting
	ErrRateLimitExceeded  = errors.New("rate limit exceeded")
)

// AppError represents an application-level error with additional context.
type AppError struct {
	Err     error
	Message string
	Code    string
	Details map[string]any
}

// Error implements the error interface.
func (e *AppError) Error() string {
	if e.Message != "" {
		return fmt.Sprintf("%s: %v", e.Message, e.Err)
	}
	return e.Err.Error()
}

// Unwrap returns the underlying error.
func (e *AppError) Unwrap() error {
	return e.Err
}

// New creates a new AppError.
func New(err error, message string) *AppError {
	return &AppError{
		Err:     err,
		Message: message,
	}
}

// WithCode adds an error code.
func (e *AppError) WithCode(code string) *AppError {
	e.Code = code
	return e
}

// WithDetails adds error details.
func (e *AppError) WithDetails(details map[string]any) *AppError {
	e.Details = details
	return e
}

// Wrap wraps an error with additional context.
func Wrap(err error, message string) *AppError {
	if err == nil {
		return nil
	}
	return &AppError{
		Err:     err,
		Message: message,
	}
}

// Is checks if the error matches a target error.
func Is(err, target error) bool {
	return errors.Is(err, target)
}

// As finds the first error in err's chain that matches target.
func As(err error, target any) bool {
	return errors.As(err, target)
}

// ValidationError represents a validation error with field details.
type ValidationError struct {
	Field   string `json:"field"`
	Message string `json:"message"`
	Value   any    `json:"value,omitempty"`
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("validation error on field '%s': %s", e.Field, e.Message)
}

// NewValidationError creates a new validation error.
func NewValidationError(field, message string) *ValidationError {
	return &ValidationError{
		Field:   field,
		Message: message,
	}
}

// WithValue adds the invalid value to the error.
func (e *ValidationError) WithValue(value any) *ValidationError {
	e.Value = value
	return e
}

// HTTPError represents an HTTP error response.
type HTTPError struct {
	StatusCode int    `json:"status_code"`
	Message    string `json:"message"`
	Code       string `json:"code,omitempty"`
}

func (e *HTTPError) Error() string {
	return fmt.Sprintf("HTTP %d: %s", e.StatusCode, e.Message)
}

// NewHTTPError creates a new HTTP error.
func NewHTTPError(statusCode int, message string) *HTTPError {
	return &HTTPError{
		StatusCode: statusCode,
		Message:    message,
	}
}

// Common HTTP errors
func BadRequest(message string) *HTTPError {
	return NewHTTPError(400, message)
}

func Unauthorized(message string) *HTTPError {
	if message == "" {
		message = "Unauthorized"
	}
	return NewHTTPError(401, message)
}

func Forbidden(message string) *HTTPError {
	if message == "" {
		message = "Forbidden"
	}
	return NewHTTPError(403, message)
}

func NotFound(message string) *HTTPError {
	if message == "" {
		message = "Not found"
	}
	return NewHTTPError(404, message)
}

func TooManyRequests(message string) *HTTPError {
	if message == "" {
		message = "Too many requests"
	}
	return NewHTTPError(429, message)
}

func InternalServerError(message string) *HTTPError {
	if message == "" {
		message = "Internal server error"
	}
	return NewHTTPError(500, message)
}

func ServiceUnavailable(message string) *HTTPError {
	if message == "" {
		message = "Service unavailable"
	}
	return NewHTTPError(503, message)
}
