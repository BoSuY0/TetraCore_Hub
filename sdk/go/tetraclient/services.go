// Package tetraclient provides a Go SDK for TetraCore Hub API.
package tetraclient

import (
	"context"
	"net/url"
	"strconv"
)

// ClientService provides client operations.
type ClientService struct {
	client *Client
}

// List lists all connected clients.
func (s *ClientService) List(ctx context.Context) (*ClientList, error) {
	var result ClientList
	err := s.client.doRequest(ctx, "GET", "/api/v1/clients", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a client by ID.
func (s *ClientService) Get(ctx context.Context, id string) (*Client, error) {
	var result Client
	err := s.client.doRequest(ctx, "GET", "/api/v1/clients/"+id, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Disconnect disconnects a client.
func (s *ClientService) Disconnect(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "POST", "/api/v1/clients/"+id+"/disconnect", nil, nil)
}

// TemplateService provides template operations.
type TemplateService struct {
	client *Client
}

// List lists all templates.
func (s *TemplateService) List(ctx context.Context, limit, offset int) (*TemplateList, error) {
	path := "/api/v1/templates"
	params := url.Values{}
	if limit > 0 {
		params.Set("limit", strconv.Itoa(limit))
	}
	if offset > 0 {
		params.Set("offset", strconv.Itoa(offset))
	}
	if len(params) > 0 {
		path += "?" + params.Encode()
	}

	var result TemplateList
	err := s.client.doRequest(ctx, "GET", path, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a template by ID.
func (s *TemplateService) Get(ctx context.Context, id string) (*Template, error) {
	var result Template
	err := s.client.doRequest(ctx, "GET", "/api/v1/templates/"+id, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Create creates a new template.
func (s *TemplateService) Create(ctx context.Context, input CreateTemplateInput) (*Template, error) {
	var result Template
	err := s.client.doRequest(ctx, "POST", "/api/v1/templates", input, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Delete deletes a template.
func (s *TemplateService) Delete(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/templates/"+id, nil, nil)
}

// Execute creates a task from a template.
func (s *TemplateService) Execute(ctx context.Context, id string, variables map[string]any) (*Task, error) {
	var result struct {
		Task Task `json:"task"`
	}
	err := s.client.doRequest(ctx, "POST", "/api/v1/templates/"+id+"/execute", map[string]any{
		"variables": variables,
	}, &result)
	if err != nil {
		return nil, err
	}
	return &result.Task, nil
}

// DLQService provides DLQ operations.
type DLQService struct {
	client *Client
}

// List lists DLQ entries.
func (s *DLQService) List(ctx context.Context, limit, offset int) (*DLQList, error) {
	path := "/api/v1/dlq"
	params := url.Values{}
	if limit > 0 {
		params.Set("limit", strconv.Itoa(limit))
	}
	if offset > 0 {
		params.Set("offset", strconv.Itoa(offset))
	}
	if len(params) > 0 {
		path += "?" + params.Encode()
	}

	var result DLQList
	err := s.client.doRequest(ctx, "GET", path, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a DLQ entry by ID.
func (s *DLQService) Get(ctx context.Context, id string) (*DLQEntry, error) {
	var result DLQEntry
	err := s.client.doRequest(ctx, "GET", "/api/v1/dlq/"+id, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Retry retries a DLQ entry.
func (s *DLQService) Retry(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "POST", "/api/v1/dlq/"+id+"/retry", nil, nil)
}

// Delete deletes a DLQ entry.
func (s *DLQService) Delete(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/dlq/"+id, nil, nil)
}

// GetStats retrieves DLQ statistics.
func (s *DLQService) GetStats(ctx context.Context) (*DLQStats, error) {
	var result DLQStats
	err := s.client.doRequest(ctx, "GET", "/api/v1/dlq/stats", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// UserService provides user operations.
type UserService struct {
	client *Client
}

// List lists all users.
func (s *UserService) List(ctx context.Context) (*UserList, error) {
	var result UserList
	err := s.client.doRequest(ctx, "GET", "/api/v1/users", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a user by ID.
func (s *UserService) Get(ctx context.Context, id string) (*User, error) {
	var result User
	err := s.client.doRequest(ctx, "GET", "/api/v1/users/"+id, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Create creates a new user.
func (s *UserService) Create(ctx context.Context, input CreateUserInput) (*User, error) {
	var result User
	err := s.client.doRequest(ctx, "POST", "/api/v1/users", input, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Delete deletes a user.
func (s *UserService) Delete(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/users/"+id, nil, nil)
}

// APIKeyService provides API key operations.
type APIKeyService struct {
	client *Client
}

// List lists all API keys.
func (s *APIKeyService) List(ctx context.Context) (*APIKeyList, error) {
	var result APIKeyList
	err := s.client.doRequest(ctx, "GET", "/api/v1/apikeys", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Create creates a new API key.
func (s *APIKeyService) Create(ctx context.Context, input CreateAPIKeyInput) (*APIKeyWithSecret, error) {
	var result APIKeyWithSecret
	err := s.client.doRequest(ctx, "POST", "/api/v1/apikeys", input, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Delete deletes an API key.
func (s *APIKeyService) Delete(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/apikeys/"+id, nil, nil)
}

// Rotate rotates an API key.
func (s *APIKeyService) Rotate(ctx context.Context, id string) (*APIKeyWithSecret, error) {
	var result APIKeyWithSecret
	err := s.client.doRequest(ctx, "POST", "/api/v1/apikeys/"+id+"/rotate", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// SecretService provides secret operations.
type SecretService struct {
	client *Client
}

// List lists all secrets (without values).
func (s *SecretService) List(ctx context.Context) (*SecretList, error) {
	var result SecretList
	err := s.client.doRequest(ctx, "GET", "/api/v1/secrets", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a secret's metadata.
func (s *SecretService) Get(ctx context.Context, key string) (*Secret, error) {
	var result Secret
	err := s.client.doRequest(ctx, "GET", "/api/v1/secrets/"+key, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// GetValue retrieves a secret's value.
func (s *SecretService) GetValue(ctx context.Context, key string) (string, error) {
	var result struct {
		Key   string `json:"key"`
		Value string `json:"value"`
	}
	err := s.client.doRequest(ctx, "GET", "/api/v1/secrets/"+key+"/value", nil, &result)
	if err != nil {
		return "", err
	}
	return result.Value, nil
}

// Create creates a new secret.
func (s *SecretService) Create(ctx context.Context, input CreateSecretInput) (*Secret, error) {
	var result Secret
	err := s.client.doRequest(ctx, "POST", "/api/v1/secrets", input, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Delete deletes a secret.
func (s *SecretService) Delete(ctx context.Context, key string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/secrets/"+key, nil, nil)
}
