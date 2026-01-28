// Package apikey provides API key management functionality.
package apikey

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/eventbus"
	"github.com/tetra/core-hub/pkg/logger"
	"golang.org/x/crypto/bcrypt"
)

// UseCase provides API key operations.
type UseCase struct {
	apiKeyRepo repository.APIKeyRepository
	roleRepo   repository.RoleRepository
	eventBus   eventbus.EventBus
	log        logger.LogFields
	maxKeysPerUser int
}

// NewUseCase creates a new API key UseCase.
func NewUseCase(apiKeyRepo repository.APIKeyRepository, roleRepo repository.RoleRepository, eventBus eventbus.EventBus) *UseCase {
	return &UseCase{
		apiKeyRepo:     apiKeyRepo,
		roleRepo:       roleRepo,
		eventBus:       eventBus,
		log:            logger.LogFields{"component": "apikey-usecase"},
		maxKeysPerUser: 10, // Default max keys per user
	}
}

// SetMaxKeysPerUser sets the maximum number of API keys per user.
func (uc *UseCase) SetMaxKeysPerUser(max int) {
	uc.maxKeysPerUser = max
}

// CreateKeyInput represents input for creating an API key.
type CreateKeyInput struct {
	Name        string              `json:"name"`
	UserID      string              `json:"user_id"`
	RoleID      entity.RoleID       `json:"role_id"`
	Permissions []entity.Permission `json:"permissions,omitempty"`
	RateLimit   int                 `json:"rate_limit,omitempty"`
	ExpiresIn   *time.Duration      `json:"expires_in,omitempty"`
	Metadata    entity.APIKeyMetadata `json:"metadata,omitempty"`
}

// CreateKey creates a new API key.
func (uc *UseCase) CreateKey(ctx context.Context, input CreateKeyInput) (*entity.APIKeyWithPlainKey, error) {
	log := logger.WithFields(uc.log)

	// Check if user has reached max keys
	count, err := uc.apiKeyRepo.CountByUser(ctx, input.UserID)
	if err != nil {
		return nil, fmt.Errorf("failed to count user keys: %w", err)
	}
	if int(count) >= uc.maxKeysPerUser {
		return nil, fmt.Errorf("maximum number of API keys (%d) reached", uc.maxKeysPerUser)
	}

	// Validate role exists
	exists, err := uc.roleRepo.Exists(ctx, input.RoleID)
	if err != nil {
		return nil, fmt.Errorf("failed to check role: %w", err)
	}
	if !exists {
		return nil, fmt.Errorf("role %s does not exist", input.RoleID)
	}

	// Generate random key
	keyBytes := make([]byte, 32)
	if _, err := rand.Read(keyBytes); err != nil {
		return nil, fmt.Errorf("failed to generate key: %w", err)
	}
	plainKey := entity.APIKeyPrefix + hex.EncodeToString(keyBytes)
	prefix := plainKey[:12]

	// Hash the key
	hashedKey, err := bcrypt.GenerateFromPassword([]byte(plainKey), bcrypt.DefaultCost)
	if err != nil {
		return nil, fmt.Errorf("failed to hash key: %w", err)
	}

	now := time.Now().UTC()
	apiKey := &entity.APIKey{
		ID:          entity.GenerateID(),
		Name:        input.Name,
		KeyHash:     string(hashedKey),
		Prefix:      prefix,
		UserID:      input.UserID,
		RoleID:      input.RoleID,
		Permissions: input.Permissions,
		RateLimit:   input.RateLimit,
		IsActive:    true,
		Metadata:    input.Metadata,
		CreatedAt:   now,
		UpdatedAt:   now,
	}

	if input.ExpiresIn != nil {
		expiresAt := now.Add(*input.ExpiresIn)
		apiKey.ExpiresAt = &expiresAt
	}

	if err := uc.apiKeyRepo.Create(ctx, apiKey); err != nil {
		return nil, fmt.Errorf("failed to create api key: %w", err)
	}

	log.Info().Str("key_id", apiKey.ID).Str("user_id", input.UserID).Msg("API key created")

	// Publish event
	if uc.eventBus != nil {
		uc.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"apikey.created",
			"apikey",
			map[string]any{
				"key_id":  apiKey.ID,
				"user_id": input.UserID,
				"name":    input.Name,
			},
		))
	}

	return &entity.APIKeyWithPlainKey{
		APIKey:   apiKey,
		PlainKey: plainKey,
	}, nil
}

// GetKey retrieves an API key by ID.
func (uc *UseCase) GetKey(ctx context.Context, id string) (*entity.APIKey, error) {
	return uc.apiKeyRepo.GetByID(ctx, id)
}

// ValidateKey validates an API key and returns the key if valid.
func (uc *UseCase) ValidateKey(ctx context.Context, plainKey string) (*entity.APIKey, error) {
	if len(plainKey) < 12 {
		return nil, entity.ErrAPIKeyInvalid
	}

	prefix := plainKey[:12]
	apiKey, err := uc.apiKeyRepo.GetByPrefix(ctx, prefix)
	if err != nil {
		return nil, entity.ErrAPIKeyInvalid
	}

	// Check if active
	if !apiKey.IsActive {
		return nil, entity.ErrAPIKeyInactive
	}

	// Check if expired
	if apiKey.IsExpired() {
		return nil, entity.ErrAPIKeyExpired
	}

	// Verify key hash
	if err := bcrypt.CompareHashAndPassword([]byte(apiKey.KeyHash), []byte(plainKey)); err != nil {
		return nil, entity.ErrAPIKeyInvalid
	}

	return apiKey, nil
}

// ValidateKeyWithIP validates an API key and checks IP whitelist.
func (uc *UseCase) ValidateKeyWithIP(ctx context.Context, plainKey, ip string) (*entity.APIKey, error) {
	apiKey, err := uc.ValidateKey(ctx, plainKey)
	if err != nil {
		return nil, err
	}

	if !apiKey.IsIPAllowed(ip) {
		return nil, entity.ErrAPIKeyIPNotAllowed
	}

	return apiKey, nil
}

// RecordUsage records API key usage.
func (uc *UseCase) RecordUsage(ctx context.Context, keyID, ip string) error {
	apiKey, err := uc.apiKeyRepo.GetByID(ctx, keyID)
	if err != nil {
		return err
	}

	apiKey.RecordUsage(ip)
	return uc.apiKeyRepo.Update(ctx, apiKey)
}

// DeactivateKey deactivates an API key.
func (uc *UseCase) DeactivateKey(ctx context.Context, id string) error {
	apiKey, err := uc.apiKeyRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	apiKey.Deactivate()
	return uc.apiKeyRepo.Update(ctx, apiKey)
}

// ActivateKey activates an API key.
func (uc *UseCase) ActivateKey(ctx context.Context, id string) error {
	apiKey, err := uc.apiKeyRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	apiKey.Activate()
	return uc.apiKeyRepo.Update(ctx, apiKey)
}

// DeleteKey deletes an API key.
func (uc *UseCase) DeleteKey(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log)

	apiKey, err := uc.apiKeyRepo.GetByID(ctx, id)
	if err != nil {
		return err
	}

	if err := uc.apiKeyRepo.Delete(ctx, id); err != nil {
		return fmt.Errorf("failed to delete api key: %w", err)
	}

	log.Info().Str("key_id", id).Str("user_id", apiKey.UserID).Msg("API key deleted")

	// Publish event
	if uc.eventBus != nil {
		uc.eventBus.PublishAsync(ctx, eventbus.NewEvent(
			"apikey.deleted",
			"apikey",
			map[string]any{
				"key_id":  id,
				"user_id": apiKey.UserID,
			},
		))
	}

	return nil
}

// RotateKey rotates an API key (creates new key, deactivates old).
func (uc *UseCase) RotateKey(ctx context.Context, id string) (*entity.APIKeyWithPlainKey, error) {
	oldKey, err := uc.apiKeyRepo.GetByID(ctx, id)
	if err != nil {
		return nil, err
	}

	// Create new key with same settings
	newKey, err := uc.CreateKey(ctx, CreateKeyInput{
		Name:        oldKey.Name + " (rotated)",
		UserID:      oldKey.UserID,
		RoleID:      oldKey.RoleID,
		Permissions: oldKey.Permissions,
		RateLimit:   oldKey.RateLimit,
		Metadata:    oldKey.Metadata,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create rotated key: %w", err)
	}

	// Deactivate old key
	if err := uc.DeactivateKey(ctx, id); err != nil {
		// Try to clean up new key
		_ = uc.DeleteKey(ctx, newKey.APIKey.ID)
		return nil, fmt.Errorf("failed to deactivate old key: %w", err)
	}

	return newKey, nil
}

// ListUserKeys lists all API keys for a user.
func (uc *UseCase) ListUserKeys(ctx context.Context, userID string) ([]*entity.APIKey, error) {
	return uc.apiKeyRepo.ListByUser(ctx, userID)
}

// ListKeys lists all API keys with optional filtering.
func (uc *UseCase) ListKeys(ctx context.Context, filter repository.APIKeyFilter) ([]*entity.APIKey, error) {
	return uc.apiKeyRepo.List(ctx, filter)
}

// GetKeyPermissions returns the effective permissions for an API key.
func (uc *UseCase) GetKeyPermissions(ctx context.Context, keyID string) (entity.PermissionSet, error) {
	apiKey, err := uc.apiKeyRepo.GetByID(ctx, keyID)
	if err != nil {
		return nil, err
	}

	role, err := uc.roleRepo.GetByID(ctx, apiKey.RoleID)
	if err != nil {
		return nil, err
	}

	effectivePerms := apiKey.GetEffectivePermissions(role.Permissions)
	return entity.NewPermissionSet(effectivePerms), nil
}
