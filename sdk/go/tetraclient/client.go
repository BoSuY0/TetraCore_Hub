// Package tetraclient provides a Go SDK for TetraCore Hub API.
package tetraclient

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client is the main TetraCore Hub client.
type Client struct {
	baseURL    string
	apiKey     string
	jwt        string
	httpClient *http.Client

	// Sub-clients
	Tasks     *TaskService
	Clients   *ClientService
	Templates *TemplateService
	DLQ       *DLQService
	Users     *UserService
	APIKeys   *APIKeyService
	Secrets   *SecretService
}

// Config holds client configuration.
type Config struct {
	BaseURL    string
	APIKey     string
	JWT        string
	Timeout    time.Duration
	HTTPClient *http.Client
}

// DefaultConfig returns default client configuration.
func DefaultConfig() Config {
	return Config{
		BaseURL: "http://localhost:8000",
		Timeout: 30 * time.Second,
	}
}

// NewClient creates a new TetraCore Hub client.
func NewClient(cfg Config) *Client {
	if cfg.Timeout == 0 {
		cfg.Timeout = 30 * time.Second
	}

	httpClient := cfg.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{
			Timeout: cfg.Timeout,
		}
	}

	c := &Client{
		baseURL:    cfg.BaseURL,
		apiKey:     cfg.APIKey,
		jwt:        cfg.JWT,
		httpClient: httpClient,
	}

	// Initialize sub-clients
	c.Tasks = &TaskService{client: c}
	c.Clients = &ClientService{client: c}
	c.Templates = &TemplateService{client: c}
	c.DLQ = &DLQService{client: c}
	c.Users = &UserService{client: c}
	c.APIKeys = &APIKeyService{client: c}
	c.Secrets = &SecretService{client: c}

	return c
}

// NewWithAPIKey creates a client with API key authentication.
func NewWithAPIKey(baseURL, apiKey string) *Client {
	return NewClient(Config{
		BaseURL: baseURL,
		APIKey:  apiKey,
	})
}

// NewWithJWT creates a client with JWT authentication.
func NewWithJWT(baseURL, jwt string) *Client {
	return NewClient(Config{
		BaseURL: baseURL,
		JWT:     jwt,
	})
}

// NewWithCredentials creates a client by logging in with credentials.
func NewWithCredentials(baseURL, username, password string) (*Client, error) {
	c := NewClient(Config{BaseURL: baseURL})

	token, err := c.Login(context.Background(), username, password)
	if err != nil {
		return nil, fmt.Errorf("failed to login: %w", err)
	}

	c.jwt = token.Token
	return c, nil
}

// SetJWT sets the JWT token.
func (c *Client) SetJWT(jwt string) {
	c.jwt = jwt
}

// SetAPIKey sets the API key.
func (c *Client) SetAPIKey(apiKey string) {
	c.apiKey = apiKey
}

// doRequest performs an HTTP request.
func (c *Client) doRequest(ctx context.Context, method, path string, body interface{}, result interface{}) error {
	var bodyReader io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("failed to marshal request body: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")

	// Add authentication
	if c.apiKey != "" {
		req.Header.Set("X-API-Key", c.apiKey)
	} else if c.jwt != "" {
		req.Header.Set("Authorization", "Bearer "+c.jwt)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	// Read response body
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read response: %w", err)
	}

	// Check for errors
	if resp.StatusCode >= 400 {
		var apiErr APIError
		if err := json.Unmarshal(respBody, &apiErr); err == nil && apiErr.Message != "" {
			return &apiErr
		}
		return fmt.Errorf("API error: %s (status %d)", string(respBody), resp.StatusCode)
	}

	// Parse result
	if result != nil && len(respBody) > 0 {
		if err := json.Unmarshal(respBody, result); err != nil {
			return fmt.Errorf("failed to parse response: %w", err)
		}
	}

	return nil
}

// Login authenticates with username and password.
func (c *Client) Login(ctx context.Context, username, password string) (*LoginResponse, error) {
	var result LoginResponse
	err := c.doRequest(ctx, "POST", "/auth/login", map[string]string{
		"username": username,
		"password": password,
	}, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Logout logs out the current session.
func (c *Client) Logout(ctx context.Context) error {
	return c.doRequest(ctx, "POST", "/auth/logout", nil, nil)
}

// RefreshToken refreshes the JWT token.
func (c *Client) RefreshToken(ctx context.Context, refreshToken string) (*LoginResponse, error) {
	var result LoginResponse
	err := c.doRequest(ctx, "POST", "/auth/refresh", map[string]string{
		"refresh_token": refreshToken,
	}, &result)
	if err != nil {
		return nil, err
	}
	c.jwt = result.Token
	return &result, nil
}

// Health checks the service health.
func (c *Client) Health(ctx context.Context) (*HealthResponse, error) {
	var result HealthResponse
	err := c.doRequest(ctx, "GET", "/health", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}
