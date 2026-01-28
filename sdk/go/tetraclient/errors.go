// Package tetraclient provides a Go SDK for TetraCore Hub API.
package tetraclient

import "fmt"

// APIError represents an API error response.
type APIError struct {
	IsError bool   `json:"error"`
	Message string `json:"message"`
	Code    int    `json:"code,omitempty"`
}

// Error implements the error interface.
func (e *APIError) Error() string {
	if e.Code > 0 {
		return fmt.Sprintf("API error %d: %s", e.Code, e.Message)
	}
	return fmt.Sprintf("API error: %s", e.Message)
}

// IsNotFound returns true if the error is a not found error.
func (e *APIError) IsNotFound() bool {
	return e.Code == 404
}

// IsUnauthorized returns true if the error is an unauthorized error.
func (e *APIError) IsUnauthorized() bool {
	return e.Code == 401
}

// IsForbidden returns true if the error is a forbidden error.
func (e *APIError) IsForbidden() bool {
	return e.Code == 403
}

// IsConflict returns true if the error is a conflict error.
func (e *APIError) IsConflict() bool {
	return e.Code == 409
}

// IsBadRequest returns true if the error is a bad request error.
func (e *APIError) IsBadRequest() bool {
	return e.Code == 400
}

// IsAPIError checks if an error is an APIError.
func IsAPIError(err error) (*APIError, bool) {
	if apiErr, ok := err.(*APIError); ok {
		return apiErr, true
	}
	return nil, false
}
