// Package tetraclient provides a Go SDK for TetraCore Hub API.
package tetraclient

import "time"

// LoginResponse represents a login response.
type LoginResponse struct {
	Token        string    `json:"token"`
	RefreshToken string    `json:"refresh_token"`
	ExpiresAt    time.Time `json:"expires_at"`
}

// HealthResponse represents a health check response.
type HealthResponse struct {
	Status  string  `json:"status"`
	Version string  `json:"version"`
	Uptime  float64 `json:"uptime"`
}

// ConnectedClient represents a connected client in the Hub.
type ConnectedClient struct {
	ClientID    string    `json:"client_id"`
	Status      string    `json:"status"`
	Type        string    `json:"type"`
	Name        string    `json:"name,omitempty"`
	ConnectedAt time.Time `json:"connected_at"`
	LastSeen    time.Time `json:"last_seen"`
}

// ClientList represents a list of clients.
type ClientList struct {
	Clients []ConnectedClient `json:"clients"`
	Count   int               `json:"count"`
}

// Template represents a task template.
type Template struct {
	ID              string         `json:"id"`
	Name            string         `json:"name"`
	Description     string         `json:"description"`
	TaskType        string         `json:"task_type"`
	ExecutorType    string         `json:"executor_type"`
	DefaultPayload  map[string]any `json:"default_payload"`
	DefaultTags     []string       `json:"default_tags"`
	DefaultPriority string         `json:"default_priority"`
	Variables       []Variable     `json:"variables"`
	IsPublic        bool           `json:"is_public"`
	CreatedBy       string         `json:"created_by"`
	CreatedAt       time.Time      `json:"created_at"`
}

// Variable represents a template variable.
type Variable struct {
	Name        string `json:"name"`
	Type        string `json:"type"`
	Required    bool   `json:"required"`
	Default     any    `json:"default,omitempty"`
	Description string `json:"description,omitempty"`
}

// TemplateList represents a list of templates.
type TemplateList struct {
	Templates []Template `json:"templates"`
	Count     int        `json:"count"`
}

// CreateTemplateInput represents input for creating a template.
type CreateTemplateInput struct {
	Name            string         `json:"name"`
	Description     string         `json:"description,omitempty"`
	TaskType        string         `json:"task_type"`
	ExecutorType    string         `json:"executor_type"`
	DefaultPayload  map[string]any `json:"default_payload,omitempty"`
	DefaultTags     []string       `json:"default_tags,omitempty"`
	DefaultPriority string         `json:"default_priority,omitempty"`
	DefaultTimeout  int            `json:"default_timeout,omitempty"`
	Variables       []Variable     `json:"variables,omitempty"`
	IsPublic        bool           `json:"is_public,omitempty"`
}

// DLQEntry represents a dead letter queue entry.
type DLQEntry struct {
	ID           string     `json:"id"`
	TaskID       string     `json:"task_id"`
	Task         *Task      `json:"task"`
	FailureCount int        `json:"failure_count"`
	LastError    string     `json:"last_error"`
	Reason       string     `json:"reason"`
	FailedAt     time.Time  `json:"failed_at"`
	RetryAfter   *time.Time `json:"retry_after,omitempty"`
	CreatedAt    time.Time  `json:"created_at"`
}

// DLQList represents a list of DLQ entries.
type DLQList struct {
	Entries []DLQEntry `json:"entries"`
	Count   int        `json:"count"`
}

// DLQStats represents DLQ statistics.
type DLQStats struct {
	TotalEntries   int            `json:"total_entries"`
	ByReason       map[string]int `json:"by_reason"`
	ByTaskType     map[string]int `json:"by_task_type"`
	RecentFailures int            `json:"recent_failures"`
}

// User represents a user.
type User struct {
	ID          string     `json:"id"`
	Username    string     `json:"username"`
	Email       string     `json:"email,omitempty"`
	RoleID      string     `json:"role_id"`
	Status      string     `json:"status"`
	TOTPEnabled bool       `json:"totp_enabled"`
	LastLoginAt *time.Time `json:"last_login_at,omitempty"`
	CreatedAt   time.Time  `json:"created_at"`
}

// UserList represents a list of users.
type UserList struct {
	Users []User `json:"users"`
	Count int    `json:"count"`
}

// CreateUserInput represents input for creating a user.
type CreateUserInput struct {
	Username string `json:"username"`
	Email    string `json:"email,omitempty"`
	Password string `json:"password"`
	RoleID   string `json:"role_id"`
}

// APIKey represents an API key.
type APIKey struct {
	ID         string     `json:"id"`
	Name       string     `json:"name"`
	Prefix     string     `json:"prefix"`
	UserID     string     `json:"user_id"`
	RoleID     string     `json:"role_id"`
	RateLimit  int        `json:"rate_limit"`
	ExpiresAt  *time.Time `json:"expires_at,omitempty"`
	LastUsedAt *time.Time `json:"last_used_at,omitempty"`
	IsActive   bool       `json:"is_active"`
	CreatedAt  time.Time  `json:"created_at"`
}

// APIKeyList represents a list of API keys.
type APIKeyList struct {
	APIKeys []APIKey `json:"api_keys"`
	Count   int      `json:"count"`
}

// CreateAPIKeyInput represents input for creating an API key.
type CreateAPIKeyInput struct {
	Name      string `json:"name"`
	RoleID    string `json:"role_id"`
	RateLimit int    `json:"rate_limit,omitempty"`
	ExpiresIn string `json:"expires_in,omitempty"`
}

// APIKeyWithSecret represents an API key with its plain key (returned on creation).
type APIKeyWithSecret struct {
	APIKey   APIKey `json:"api_key"`
	PlainKey string `json:"plain_key"`
}

// Secret represents a secret (without value).
type Secret struct {
	Key         string            `json:"key"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
	Version     int               `json:"version"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
}

// SecretList represents a list of secrets.
type SecretList struct {
	Secrets []Secret `json:"secrets"`
	Count   int      `json:"count"`
}

// CreateSecretInput represents input for creating a secret.
type CreateSecretInput struct {
	Key         string            `json:"key"`
	Value       string            `json:"value"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
}
