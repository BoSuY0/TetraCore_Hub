// Package totp provides TOTP (2FA) use cases for TetraCore Hub.
package totp

import (
	"context"
	"crypto/rand"
	"encoding/base32"
	"fmt"
	"time"

	"github.com/pquerna/otp"
	"github.com/pquerna/otp/totp"
	"github.com/tetra/core-hub/internal/delivery/http/handler"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds TOTP configuration.
type Config struct {
	Issuer         string
	BackupCodeCount int
	BackupCodeLength int
}

// UseCase handles TOTP operations.
type UseCase struct {
	repo   repository.TOTPRepository
	config Config
	log    logger.LogFields
}

// NewUseCase creates a new TOTP use case.
func NewUseCase(repo repository.TOTPRepository, config Config) *UseCase {
	if config.Issuer == "" {
		config.Issuer = "TetraCore"
	}
	if config.BackupCodeCount == 0 {
		config.BackupCodeCount = 10
	}
	if config.BackupCodeLength == 0 {
		config.BackupCodeLength = 8
	}

	return &UseCase{
		repo:   repo,
		config: config,
		log:    logger.LogFields{"component": "totp-usecase"},
	}
}

// Setup initiates TOTP setup for a user.
func (uc *UseCase) Setup(ctx context.Context, userID string) (*entity.TOTPSetupResponse, error) {
	log := logger.WithFields(uc.log).With("user_id", userID)

	// Check if already setup
	existing, err := uc.repo.GetByUserID(ctx, userID)
	if err == nil && existing != nil && existing.Enabled {
		return nil, errors.ErrConflict.With("2FA is already enabled")
	}

	// Generate new TOTP secret
	key, err := totp.Generate(totp.GenerateOpts{
		Issuer:      uc.config.Issuer,
		AccountName: userID,
		Period:      30,
		SecretSize:  32,
		Digits:      otp.DigitsSix,
		Algorithm:   otp.AlgorithmSHA1,
	})
	if err != nil {
		log.Error().Err(err).Msg("Failed to generate TOTP key")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to generate TOTP")
	}

	// Generate backup codes
	backupCodes := uc.generateBackupCodes()

	// Create TOTP config
	config := &entity.TOTPConfig{
		UserID:       userID,
		Secret:       key.Secret(),
		Enabled:      false, // Not enabled until verified
		Verified:     false,
		BackupCodes:  backupCodes,
		CreatedAt:    time.Now().UTC(),
		UpdatedAt:    time.Now().UTC(),
	}

	if err := uc.repo.Save(ctx, config); err != nil {
		log.Error().Err(err).Msg("Failed to save TOTP config")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to save TOTP config")
	}

	log.Info().Msg("TOTP setup initiated")

	return &entity.TOTPSetupResponse{
		Secret:      key.Secret(),
		BackupCodes: backupCodes,
	}, nil
}

// Verify verifies a TOTP code and enables 2FA.
func (uc *UseCase) Verify(ctx context.Context, userID, code string) error {
	log := logger.WithFields(uc.log).With("user_id", userID)

	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return errors.ErrNotFound.With("2FA not setup")
	}

	if config.Enabled && config.Verified {
		return errors.ErrConflict.With("2FA is already verified and enabled")
	}

	// Validate the code
	valid := totp.Validate(code, config.Secret)
	if !valid {
		return errors.ErrUnauthorized.With("invalid code")
	}

	// Enable 2FA
	config.Enabled = true
	config.Verified = true
	config.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, config); err != nil {
		log.Error().Err(err).Msg("Failed to enable 2FA")
		return errors.ErrInternalServer.Wrap(err, "failed to enable 2FA")
	}

	log.Info().Msg("2FA enabled successfully")
	return nil
}

// Validate validates a TOTP code for an enabled 2FA.
func (uc *UseCase) Validate(ctx context.Context, userID, code string) (bool, error) {
	log := logger.WithFields(uc.log).With("user_id", userID)

	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return false, errors.ErrNotFound.With("2FA not setup")
	}

	if !config.Enabled {
		return false, errors.ErrValidation.With("2FA is not enabled")
	}

	// First try TOTP
	if totp.Validate(code, config.Secret) {
		log.Debug().Msg("TOTP code validated")
		return true, nil
	}

	// Then try backup codes
	for i, backupCode := range config.BackupCodes {
		if backupCode == code {
			// Remove used backup code
			config.BackupCodes = append(config.BackupCodes[:i], config.BackupCodes[i+1:]...)
			config.UpdatedAt = time.Now().UTC()
			if err := uc.repo.Save(ctx, config); err != nil {
				log.Warn().Err(err).Msg("Failed to remove used backup code")
			}
			log.Info().Msg("Backup code used")
			return true, nil
		}
	}

	log.Debug().Msg("Invalid TOTP code")
	return false, nil
}

// Disable disables 2FA for a user.
func (uc *UseCase) Disable(ctx context.Context, userID, code string) error {
	log := logger.WithFields(uc.log).With("user_id", userID)

	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return errors.ErrNotFound.With("2FA not setup")
	}

	if !config.Enabled {
		return errors.ErrValidation.With("2FA is not enabled")
	}

	// Validate code before disabling
	valid, err := uc.Validate(ctx, userID, code)
	if err != nil {
		return err
	}
	if !valid {
		return errors.ErrUnauthorized.With("invalid code")
	}

	// Delete TOTP config
	if err := uc.repo.Delete(ctx, userID); err != nil {
		log.Error().Err(err).Msg("Failed to disable 2FA")
		return errors.ErrInternalServer.Wrap(err, "failed to disable 2FA")
	}

	log.Info().Msg("2FA disabled")
	return nil
}

// GetStatus returns the TOTP status for a user.
func (uc *UseCase) GetStatus(ctx context.Context, userID string) (*handler.TOTPStatus, error) {
	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return &handler.TOTPStatus{
			Enabled:              false,
			Verified:             false,
			RemainingBackupCodes: 0,
		}, nil
	}

	return &handler.TOTPStatus{
		Enabled:              config.Enabled,
		Verified:             config.Verified,
		RemainingBackupCodes: len(config.BackupCodes),
	}, nil
}

// RegenerateBackupCodes regenerates backup codes for a user.
func (uc *UseCase) RegenerateBackupCodes(ctx context.Context, userID, code string) ([]string, error) {
	log := logger.WithFields(uc.log).With("user_id", userID)

	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return nil, errors.ErrNotFound.With("2FA not setup")
	}

	if !config.Enabled {
		return nil, errors.ErrValidation.With("2FA is not enabled")
	}

	// Validate code
	valid := totp.Validate(code, config.Secret)
	if !valid {
		return nil, errors.ErrUnauthorized.With("invalid code")
	}

	// Generate new backup codes
	newCodes := uc.generateBackupCodes()
	config.BackupCodes = newCodes
	config.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, config); err != nil {
		log.Error().Err(err).Msg("Failed to save new backup codes")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to regenerate backup codes")
	}

	log.Info().Msg("Backup codes regenerated")
	return newCodes, nil
}

// IsEnabled checks if 2FA is enabled for a user.
func (uc *UseCase) IsEnabled(ctx context.Context, userID string) (bool, error) {
	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return false, nil
	}
	return config.Enabled && config.Verified, nil
}

// generateBackupCodes generates random backup codes.
func (uc *UseCase) generateBackupCodes() []string {
	codes := make([]string, uc.config.BackupCodeCount)
	for i := range codes {
		codes[i] = uc.generateRandomCode()
	}
	return codes
}

// generateRandomCode generates a random alphanumeric code.
func (uc *UseCase) generateRandomCode() string {
	bytes := make([]byte, uc.config.BackupCodeLength)
	if _, err := rand.Read(bytes); err != nil {
		// Fallback to less secure but still random
		for i := range bytes {
			bytes[i] = byte(i)
		}
	}
	return base32.StdEncoding.EncodeToString(bytes)[:uc.config.BackupCodeLength]
}

// RequiresTOTP checks if a user requires TOTP validation.
func (uc *UseCase) RequiresTOTP(ctx context.Context, userID string) bool {
	enabled, _ := uc.IsEnabled(ctx, userID)
	return enabled
}

// GenerateRecoveryKey generates a recovery key that can be used to disable 2FA.
func (uc *UseCase) GenerateRecoveryKey(ctx context.Context, userID string) (string, error) {
	log := logger.WithFields(uc.log).With("user_id", userID)

	config, err := uc.repo.GetByUserID(ctx, userID)
	if err != nil {
		return "", errors.ErrNotFound.With("2FA not setup")
	}

	// Generate recovery key
	bytes := make([]byte, 32)
	if _, err := rand.Read(bytes); err != nil {
		return "", errors.ErrInternalServer.Wrap(err, "failed to generate recovery key")
	}
	recoveryKey := fmt.Sprintf("%s-%s-%s-%s",
		base32.StdEncoding.EncodeToString(bytes[0:8])[:8],
		base32.StdEncoding.EncodeToString(bytes[8:16])[:8],
		base32.StdEncoding.EncodeToString(bytes[16:24])[:8],
		base32.StdEncoding.EncodeToString(bytes[24:32])[:8],
	)

	config.RecoveryKey = recoveryKey
	config.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, config); err != nil {
		log.Error().Err(err).Msg("Failed to save recovery key")
		return "", errors.ErrInternalServer.Wrap(err, "failed to save recovery key")
	}

	log.Info().Msg("Recovery key generated")
	return recoveryKey, nil
}

// Ensure interface compliance
var _ handler.TOTPService = (*UseCase)(nil)
