// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"time"
)

// APIKey represents an API key for programmatic access.
type APIKey struct {
	ID          string       `json:"id"`
	Name        string       `json:"name"`
	KeyHash     string       `json:"-"`              // bcrypt hash of the key
	Prefix      string       `json:"prefix"`         // First 8 chars for identification (tk_xxxxxxxx)
	UserID      string       `json:"user_id"`        // Owner of the key
	RoleID      RoleID       `json:"role_id"`        // Role for RBAC
	Permissions []Permission `json:"permissions"`    // Additional permissions override
	RateLimit   int          `json:"rate_limit"`     // Requests per minute (0 = no limit)
	ExpiresAt   *time.Time   `json:"expires_at,omitempty"`
	LastUsedAt  *time.Time   `json:"last_used_at,omitempty"`
	LastUsedIP  string       `json:"last_used_ip,omitempty"`
	IsActive    bool         `json:"is_active"`
	Metadata    APIKeyMetadata `json:"metadata,omitempty"`
	CreatedAt   time.Time    `json:"created_at"`
	UpdatedAt   time.Time    `json:"updated_at"`
}

// APIKeyMetadata contains additional API key information.
type APIKeyMetadata struct {
	Description string   `json:"description,omitempty"`
	AllowedIPs  []string `json:"allowed_ips,omitempty"`   // IP whitelist
	Environment string   `json:"environment,omitempty"`   // dev, staging, prod
}

// APIKey errors
var (
	ErrAPIKeyNotFound      = errors.New("api key not found")
	ErrAPIKeyAlreadyExists = errors.New("api key already exists")
	ErrAPIKeyExpired       = errors.New("api key has expired")
	ErrAPIKeyInactive      = errors.New("api key is inactive")
	ErrAPIKeyInvalid       = errors.New("api key is invalid")
	ErrAPIKeyIPNotAllowed  = errors.New("ip address not allowed")
)

// APIKeyPrefix is the prefix for all API keys.
const APIKeyPrefix = "tk_"

// NewAPIKey creates a new APIKey. Returns the key and the plain text key.
func NewAPIKey(name, userID string, roleID RoleID, keyHash string) (*APIKey, string, error) {
	// Generate random key
	keyBytes := make([]byte, 32) // 256 bits
	if _, err := rand.Read(keyBytes); err != nil {
		return nil, "", err
	}
	plainKey := APIKeyPrefix + hex.EncodeToString(keyBytes)
	prefix := plainKey[:12] // tk_ + 8 chars

	now := time.Now().UTC()
	key := &APIKey{
		ID:        GenerateID(),
		Name:      name,
		KeyHash:   keyHash,
		Prefix:    prefix,
		UserID:    userID,
		RoleID:    roleID,
		IsActive:  true,
		CreatedAt: now,
		UpdatedAt: now,
	}

	return key, plainKey, nil
}

// IsExpired returns true if the API key has expired.
func (k *APIKey) IsExpired() bool {
	if k.ExpiresAt == nil {
		return false
	}
	return time.Now().After(*k.ExpiresAt)
}

// IsValid returns true if the API key is active and not expired.
func (k *APIKey) IsValid() bool {
	return k.IsActive && !k.IsExpired()
}

// RecordUsage records API key usage.
func (k *APIKey) RecordUsage(ip string) {
	now := time.Now().UTC()
	k.LastUsedAt = &now
	k.LastUsedIP = ip
	k.UpdatedAt = now
}

// IsIPAllowed checks if the given IP is allowed to use this key.
func (k *APIKey) IsIPAllowed(ip string) bool {
	if len(k.Metadata.AllowedIPs) == 0 {
		return true // No whitelist means all IPs allowed
	}
	for _, allowedIP := range k.Metadata.AllowedIPs {
		if allowedIP == ip || allowedIP == "*" {
			return true
		}
	}
	return false
}

// Deactivate deactivates the API key.
func (k *APIKey) Deactivate() {
	k.IsActive = false
	k.UpdatedAt = time.Now().UTC()
}

// Activate activates the API key.
func (k *APIKey) Activate() {
	k.IsActive = true
	k.UpdatedAt = time.Now().UTC()
}

// GetEffectivePermissions returns the effective permissions for this API key.
// If custom permissions are set, returns those; otherwise returns role permissions.
func (k *APIKey) GetEffectivePermissions(rolePermissions []Permission) []Permission {
	if len(k.Permissions) > 0 {
		return k.Permissions
	}
	return rolePermissions
}

// APIKeyPublic represents the public view of an API key (no sensitive data).
type APIKeyPublic struct {
	ID         string         `json:"id"`
	Name       string         `json:"name"`
	Prefix     string         `json:"prefix"`
	UserID     string         `json:"user_id"`
	RoleID     RoleID         `json:"role_id"`
	RateLimit  int            `json:"rate_limit"`
	ExpiresAt  *time.Time     `json:"expires_at,omitempty"`
	LastUsedAt *time.Time     `json:"last_used_at,omitempty"`
	IsActive   bool           `json:"is_active"`
	Metadata   APIKeyMetadata `json:"metadata,omitempty"`
	CreatedAt  time.Time      `json:"created_at"`
}

// ToPublic converts APIKey to APIKeyPublic.
func (k *APIKey) ToPublic() APIKeyPublic {
	return APIKeyPublic{
		ID:         k.ID,
		Name:       k.Name,
		Prefix:     k.Prefix,
		UserID:     k.UserID,
		RoleID:     k.RoleID,
		RateLimit:  k.RateLimit,
		ExpiresAt:  k.ExpiresAt,
		LastUsedAt: k.LastUsedAt,
		IsActive:   k.IsActive,
		Metadata:   k.Metadata,
		CreatedAt:  k.CreatedAt,
	}
}

// APIKeyWithPlainKey is returned when creating a new key (includes the plain key).
type APIKeyWithPlainKey struct {
	APIKey   *APIKey `json:"api_key"`
	PlainKey string  `json:"plain_key"` // Only returned once on creation
}
