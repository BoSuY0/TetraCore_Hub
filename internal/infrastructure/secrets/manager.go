// Package secrets provides secure secret management for TetraCore Hub.
package secrets

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/infrastructure/eventbus"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	secretKeyPrefix = "secrets:"
	secretListKey   = "secrets:list"
)

// Secret errors
var (
	ErrSecretNotFound     = errors.New("secret not found")
	ErrSecretKeyInvalid   = errors.New("invalid encryption key")
	ErrSecretDecryptFail  = errors.New("failed to decrypt secret")
	ErrSecretEncryptFail  = errors.New("failed to encrypt secret")
)

// Secret represents a stored secret.
type Secret struct {
	Key         string            `json:"key"`
	Value       string            `json:"-"` // Never serialize plaintext
	Encrypted   string            `json:"encrypted"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
	Version     int               `json:"version"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
	CreatedBy   string            `json:"created_by,omitempty"`
	UpdatedBy   string            `json:"updated_by,omitempty"`
}

// SecretPublic is the public view of a secret (no value).
type SecretPublic struct {
	Key         string            `json:"key"`
	Description string            `json:"description,omitempty"`
	Tags        []string          `json:"tags,omitempty"`
	Metadata    map[string]string `json:"metadata,omitempty"`
	Version     int               `json:"version"`
	CreatedAt   time.Time         `json:"created_at"`
	UpdatedAt   time.Time         `json:"updated_at"`
}

// ToPublic converts Secret to SecretPublic.
func (s *Secret) ToPublic() SecretPublic {
	return SecretPublic{
		Key:         s.Key,
		Description: s.Description,
		Tags:        s.Tags,
		Metadata:    s.Metadata,
		Version:     s.Version,
		CreatedAt:   s.CreatedAt,
		UpdatedAt:   s.UpdatedAt,
	}
}

// Manager provides secure secret storage and retrieval.
type Manager struct {
	client    redis.UniversalClient
	cipher    cipher.AEAD
	eventBus  eventbus.EventBus
	log       logger.LogFields
	mu        sync.RWMutex
	cache     map[string]*Secret // In-memory cache for frequently accessed secrets
	cacheSize int
}

// ManagerConfig holds configuration for the secrets manager.
type ManagerConfig struct {
	EncryptionKey string // 32-byte key for AES-256-GCM
	CacheSize     int    // Number of secrets to cache (0 = no cache)
}

// NewManager creates a new secrets manager.
func NewManager(client redis.UniversalClient, cfg ManagerConfig, eventBus eventbus.EventBus) (*Manager, error) {
	// Validate and decode encryption key
	keyBytes, err := base64.StdEncoding.DecodeString(cfg.EncryptionKey)
	if err != nil {
		return nil, fmt.Errorf("%w: failed to decode key", ErrSecretKeyInvalid)
	}
	if len(keyBytes) != 32 {
		return nil, fmt.Errorf("%w: key must be 32 bytes (256 bits)", ErrSecretKeyInvalid)
	}

	// Create AES cipher
	block, err := aes.NewCipher(keyBytes)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrSecretKeyInvalid, err)
	}

	// Create GCM mode
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrSecretKeyInvalid, err)
	}

	m := &Manager{
		client:    client,
		cipher:    gcm,
		eventBus:  eventBus,
		log:       logger.LogFields{"component": "secrets-manager"},
		cacheSize: cfg.CacheSize,
	}

	if cfg.CacheSize > 0 {
		m.cache = make(map[string]*Secret, cfg.CacheSize)
	}

	return m, nil
}

// GenerateKey generates a new random encryption key.
func GenerateKey() (string, error) {
	key := make([]byte, 32)
	if _, err := rand.Read(key); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(key), nil
}

// encrypt encrypts a plaintext value.
func (m *Manager) encrypt(plaintext string) (string, error) {
	// Generate random nonce
	nonce := make([]byte, m.cipher.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", ErrSecretEncryptFail
	}

	// Encrypt
	ciphertext := m.cipher.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// decrypt decrypts an encrypted value.
func (m *Manager) decrypt(encrypted string) (string, error) {
	ciphertext, err := base64.StdEncoding.DecodeString(encrypted)
	if err != nil {
		return "", ErrSecretDecryptFail
	}

	if len(ciphertext) < m.cipher.NonceSize() {
		return "", ErrSecretDecryptFail
	}

	nonce := ciphertext[:m.cipher.NonceSize()]
	ciphertext = ciphertext[m.cipher.NonceSize():]

	plaintext, err := m.cipher.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", ErrSecretDecryptFail
	}

	return string(plaintext), nil
}

// Set stores a secret.
func (m *Manager) Set(ctx context.Context, key, value string, opts ...SetOption) error {
	log := logger.WithFields(m.log)

	// Apply options
	options := &setOptions{}
	for _, opt := range opts {
		opt(options)
	}

	// Encrypt the value
	encrypted, err := m.encrypt(value)
	if err != nil {
		return err
	}

	// Get existing secret or create new
	existing, _ := m.getSecretData(ctx, key)
	version := 1
	createdAt := time.Now().UTC()
	if existing != nil {
		version = existing.Version + 1
		createdAt = existing.CreatedAt
	}

	secret := &Secret{
		Key:         key,
		Encrypted:   encrypted,
		Description: options.description,
		Tags:        options.tags,
		Metadata:    options.metadata,
		Version:     version,
		CreatedAt:   createdAt,
		UpdatedAt:   time.Now().UTC(),
		CreatedBy:   options.createdBy,
		UpdatedBy:   options.updatedBy,
	}

	// Store in Redis
	data, err := json.Marshal(secret)
	if err != nil {
		return fmt.Errorf("failed to marshal secret: %w", err)
	}

	pipe := m.client.Pipeline()
	pipe.Set(ctx, secretKeyPrefix+key, data, 0)
	pipe.SAdd(ctx, secretListKey, key)
	if _, err := pipe.Exec(ctx); err != nil {
		return fmt.Errorf("failed to store secret: %w", err)
	}

	// Update cache
	if m.cache != nil {
		m.mu.Lock()
		secret.Value = value // Cache includes decrypted value
		m.cache[key] = secret
		m.mu.Unlock()
	}

	log.Info().Str("key", key).Int("version", version).Msg("Secret stored")

	// Publish event
	if m.eventBus != nil {
		m.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"secret.updated",
			"secrets",
			map[string]any{
				"key":     key,
				"version": version,
			},
		))
	}

	return nil
}

// Get retrieves a secret value.
func (m *Manager) Get(ctx context.Context, key string) (string, error) {
	// Check cache first
	if m.cache != nil {
		m.mu.RLock()
		if secret, ok := m.cache[key]; ok {
			m.mu.RUnlock()
			return secret.Value, nil
		}
		m.mu.RUnlock()
	}

	secret, err := m.getSecretData(ctx, key)
	if err != nil {
		return "", err
	}

	// Decrypt
	value, err := m.decrypt(secret.Encrypted)
	if err != nil {
		return "", err
	}

	// Update cache
	if m.cache != nil {
		m.mu.Lock()
		secret.Value = value
		m.cache[key] = secret
		m.mu.Unlock()
	}

	return value, nil
}

// GetSecret retrieves secret metadata (without value).
func (m *Manager) GetSecret(ctx context.Context, key string) (*Secret, error) {
	return m.getSecretData(ctx, key)
}

// getSecretData retrieves the secret data from Redis.
func (m *Manager) getSecretData(ctx context.Context, key string) (*Secret, error) {
	data, err := m.client.Get(ctx, secretKeyPrefix+key).Bytes()
	if err == redis.Nil {
		return nil, ErrSecretNotFound
	}
	if err != nil {
		return nil, err
	}

	var secret Secret
	if err := json.Unmarshal(data, &secret); err != nil {
		return nil, fmt.Errorf("failed to unmarshal secret: %w", err)
	}

	return &secret, nil
}

// Delete deletes a secret.
func (m *Manager) Delete(ctx context.Context, key string) error {
	log := logger.WithFields(m.log)

	pipe := m.client.Pipeline()
	pipe.Del(ctx, secretKeyPrefix+key)
	pipe.SRem(ctx, secretListKey, key)
	if _, err := pipe.Exec(ctx); err != nil {
		return fmt.Errorf("failed to delete secret: %w", err)
	}

	// Remove from cache
	if m.cache != nil {
		m.mu.Lock()
		delete(m.cache, key)
		m.mu.Unlock()
	}

	log.Info().Str("key", key).Msg("Secret deleted")

	// Publish event
	if m.eventBus != nil {
		m.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"secret.deleted",
			"secrets",
			map[string]any{"key": key},
		))
	}

	return nil
}

// List lists all secret keys (not values).
func (m *Manager) List(ctx context.Context) ([]SecretPublic, error) {
	keys, err := m.client.SMembers(ctx, secretListKey).Result()
	if err != nil {
		return nil, err
	}

	secrets := make([]SecretPublic, 0, len(keys))
	for _, key := range keys {
		secret, err := m.getSecretData(ctx, key)
		if err != nil {
			continue
		}
		secrets = append(secrets, secret.ToPublic())
	}

	return secrets, nil
}

// ListByTag lists secrets with a specific tag.
func (m *Manager) ListByTag(ctx context.Context, tag string) ([]SecretPublic, error) {
	all, err := m.List(ctx)
	if err != nil {
		return nil, err
	}

	filtered := make([]SecretPublic, 0)
	for _, s := range all {
		for _, t := range s.Tags {
			if t == tag {
				filtered = append(filtered, s)
				break
			}
		}
	}

	return filtered, nil
}

// Exists checks if a secret exists.
func (m *Manager) Exists(ctx context.Context, key string) (bool, error) {
	exists, err := m.client.Exists(ctx, secretKeyPrefix+key).Result()
	return exists > 0, err
}

// ClearCache clears the in-memory cache.
func (m *Manager) ClearCache() {
	if m.cache != nil {
		m.mu.Lock()
		m.cache = make(map[string]*Secret, m.cacheSize)
		m.mu.Unlock()
	}
}

// Set options

type setOptions struct {
	description string
	tags        []string
	metadata    map[string]string
	createdBy   string
	updatedBy   string
}

// SetOption configures secret storage.
type SetOption func(*setOptions)

// WithDescription sets the secret description.
func WithDescription(desc string) SetOption {
	return func(o *setOptions) {
		o.description = desc
	}
}

// WithTags sets the secret tags.
func WithTags(tags ...string) SetOption {
	return func(o *setOptions) {
		o.tags = tags
	}
}

// WithMetadata sets the secret metadata.
func WithMetadata(metadata map[string]string) SetOption {
	return func(o *setOptions) {
		o.metadata = metadata
	}
}

// WithCreatedBy sets who created the secret.
func WithCreatedBy(userID string) SetOption {
	return func(o *setOptions) {
		o.createdBy = userID
	}
}

// WithUpdatedBy sets who updated the secret.
func WithUpdatedBy(userID string) SetOption {
	return func(o *setOptions) {
		o.updatedBy = userID
	}
}
