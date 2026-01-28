// Package secrets provides secret management and rotation for TetraCore Hub.
package secrets

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"time"
)

// Errors
var (
	ErrSecretNotFound = errors.New("secret not found")
	ErrRotationFailed = errors.New("rotation failed")
)

// SecretType defines the type of secret for generation.
type SecretType string

const (
	SecretTypeJWT        SecretType = "jwt_secret"
	SecretTypeAPIKey     SecretType = "api_key"
	SecretTypePassword   SecretType = "password"
	SecretTypeEncryption SecretType = "encryption_key"
	SecretTypeToken      SecretType = "token"
	SecretTypeWebhook    SecretType = "webhook_secret"
)

// SecretTypeConfig defines generation parameters for a secret type.
type SecretTypeConfig struct {
	Length int
	Chars  string
}

var secretTypeConfigs = map[SecretType]SecretTypeConfig{
	SecretTypeJWT: {
		Length: 64,
		Chars:  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
	},
	SecretTypeAPIKey: {
		Length: 32,
		Chars:  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
	},
	SecretTypePassword: {
		Length: 24,
		Chars:  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*",
	},
	SecretTypeEncryption: {
		Length: 32,
		Chars:  "", // Binary key
	},
	SecretTypeToken: {
		Length: 48,
		Chars:  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
	},
	SecretTypeWebhook: {
		Length: 32,
		Chars:  "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
	},
}

// CriticalSecrets is the list of secrets that should be rotated regularly.
var CriticalSecrets = []string{
	"JWT_SECRET",
	"ADMIN_PASSWORD",
	"REDIS_PASSWORD",
	"ENCRYPTION_KEY",
	"API_SECRET_KEY",
	"BOT_TOKEN_PROD",
	"BOT_TOKEN_DEV",
	"API_ID",
	"API_HASH",
	"AWS_ACCESS_KEY_ID",
	"AWS_SECRET_ACCESS_KEY",
	"WEBHOOK_SECRET",
	"SESSION_SECRET",
}

// SecretTypeMapping maps secret keys to their types.
var SecretTypeMapping = map[string]SecretType{
	"JWT_SECRET":            SecretTypeJWT,
	"ADMIN_PASSWORD":        SecretTypePassword,
	"REDIS_PASSWORD":        SecretTypePassword,
	"ENCRYPTION_KEY":        SecretTypeEncryption,
	"API_SECRET_KEY":        SecretTypeAPIKey,
	"BOT_TOKEN_PROD":        SecretTypeToken,
	"BOT_TOKEN_DEV":         SecretTypeToken,
	"API_ID":                SecretTypeAPIKey,
	"API_HASH":              SecretTypeAPIKey,
	"AWS_ACCESS_KEY_ID":     SecretTypeAPIKey,
	"AWS_SECRET_ACCESS_KEY": SecretTypeAPIKey,
	"WEBHOOK_SECRET":        SecretTypeWebhook,
	"SESSION_SECRET":        SecretTypeJWT,
}

// RotationResult holds the result of a rotation operation.
type RotationResult struct {
	Key      string
	Success  bool
	NewValue string
	Error    error
}

// RotationLog represents a log entry for a rotation operation.
type RotationLog struct {
	Timestamp string `json:"timestamp"`
	Key       string `json:"key"`
	Status    string `json:"status"`
	Error     string `json:"error,omitempty"`
}

// Rotator handles secret rotation.
type Rotator struct {
	provider  Provider
	backupDir string
	logFile   string
}

// RotatorConfig holds rotator configuration.
type RotatorConfig struct {
	BackupDir string
	LogFile   string
}

// NewRotator creates a new secret rotator.
func NewRotator(provider Provider, cfg RotatorConfig) (*Rotator, error) {
	if cfg.BackupDir == "" {
		cfg.BackupDir = "secrets_backup"
	}
	if cfg.LogFile == "" {
		cfg.LogFile = "logs/secret_rotation.log"
	}

	// Create directories
	if err := os.MkdirAll(cfg.BackupDir, 0700); err != nil {
		return nil, fmt.Errorf("failed to create backup directory: %w", err)
	}

	logDir := filepath.Dir(cfg.LogFile)
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log directory: %w", err)
	}

	return &Rotator{
		provider:  provider,
		backupDir: cfg.BackupDir,
		logFile:   cfg.LogFile,
	}, nil
}

// GenerateSecret generates a new secret of the specified type.
func GenerateSecret(secretType SecretType) (string, error) {
	config, exists := secretTypeConfigs[secretType]
	if !exists {
		config = secretTypeConfigs[SecretTypeAPIKey]
	}

	// For encryption keys, generate random bytes
	if secretType == SecretTypeEncryption {
		bytes := make([]byte, config.Length)
		if _, err := rand.Read(bytes); err != nil {
			return "", fmt.Errorf("failed to generate random bytes: %w", err)
		}
		return base64.URLEncoding.EncodeToString(bytes), nil
	}

	// For other types, generate from character set
	result := make([]byte, config.Length)
	chars := config.Chars
	charLen := big.NewInt(int64(len(chars)))

	for i := 0; i < config.Length; i++ {
		idx, err := rand.Int(rand.Reader, charLen)
		if err != nil {
			return "", fmt.Errorf("failed to generate random index: %w", err)
		}
		result[i] = chars[idx.Int64()]
	}

	return string(result), nil
}

// Rotate rotates a single secret.
func (r *Rotator) Rotate(ctx context.Context, key string, secretType SecretType, customValue string) (*RotationResult, error) {
	result := &RotationResult{
		Key: key,
	}

	// Get old value for backup
	oldValue, err := r.provider.Get(ctx, key)
	if err != nil && !errors.Is(err, ErrSecretNotFound) {
		result.Error = fmt.Errorf("failed to get old value: %w", err)
		r.logRotation(key, "ERROR", result.Error.Error())
		return result, result.Error
	}

	// Create backup if old value exists
	if oldValue != "" {
		if err := SaveBackup(r.backupDir, key, oldValue, false); err != nil {
			// Log but don't fail - backup is best-effort
			fmt.Fprintf(os.Stderr, "Warning: failed to create backup for %s: %v\n", key, err)
		}
	}

	// Generate or use custom value
	var newValue string
	if customValue != "" {
		newValue = customValue
	} else {
		newValue, err = GenerateSecret(secretType)
		if err != nil {
			result.Error = fmt.Errorf("failed to generate secret: %w", err)
			r.logRotation(key, "ERROR", result.Error.Error())
			return result, result.Error
		}
	}

	// Set new value
	if err := r.provider.Set(ctx, key, newValue); err != nil {
		result.Error = fmt.Errorf("failed to set new value: %w", err)
		r.logRotation(key, "FAILED", result.Error.Error())
		return result, result.Error
	}

	result.Success = true
	result.NewValue = newValue
	r.logRotation(key, "SUCCESS", "")

	return result, nil
}

// RotateAll rotates all critical secrets.
func (r *Rotator) RotateAll(ctx context.Context) (map[string]*RotationResult, error) {
	results := make(map[string]*RotationResult)

	for _, key := range CriticalSecrets {
		secretType, exists := SecretTypeMapping[key]
		if !exists {
			secretType = SecretTypeAPIKey
		}

		result, _ := r.Rotate(ctx, key, secretType, "")
		results[key] = result
	}

	return results, nil
}

// Verify verifies that a secret was successfully rotated.
func (r *Rotator) Verify(ctx context.Context, key, oldValue string) (bool, error) {
	newValue, err := r.provider.Get(ctx, key)
	if err != nil {
		return false, err
	}
	return newValue != "" && newValue != oldValue, nil
}

// List lists all secrets from the provider.
func (r *Rotator) List(ctx context.Context) ([]string, error) {
	return r.provider.List(ctx)
}

// Provider returns the underlying provider.
func (r *Rotator) Provider() Provider {
	return r.provider
}

func (r *Rotator) logRotation(key, status, errMsg string) {
	entry := RotationLog{
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Key:       key,
		Status:    status,
		Error:     errMsg,
	}

	data, err := json.Marshal(entry)
	if err != nil {
		return
	}

	f, err := os.OpenFile(r.logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()

	f.WriteString(string(data) + "\n")
}

// GetSecretType returns the secret type for a given key.
func GetSecretType(key string) SecretType {
	if t, exists := SecretTypeMapping[key]; exists {
		return t
	}
	return SecretTypeAPIKey
}

// ParseSecretType parses a string into a SecretType.
func ParseSecretType(s string) SecretType {
	switch s {
	case "jwt_secret":
		return SecretTypeJWT
	case "api_key":
		return SecretTypeAPIKey
	case "password":
		return SecretTypePassword
	case "encryption_key":
		return SecretTypeEncryption
	case "token":
		return SecretTypeToken
	case "webhook_secret":
		return SecretTypeWebhook
	default:
		return SecretTypeAPIKey
	}
}
