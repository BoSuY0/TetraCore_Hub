// Package entity defines domain entities for TetraCore Hub.
package entity

import (
	"crypto/rand"
	"encoding/base32"
	"time"
)

// TOTPConfig represents TOTP configuration for a user.
type TOTPConfig struct {
	UserID       string     `json:"user_id"`
	Secret       string     `json:"-"` // Never expose in JSON
	Enabled      bool       `json:"enabled"`
	Verified     bool       `json:"verified"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
	VerifiedAt   *time.Time `json:"verified_at,omitempty"`
	LastUsedAt   *time.Time `json:"last_used_at,omitempty"`
	BackupCodes  []string   `json:"-"` // Never expose in JSON
	UsedBackups  []string   `json:"-"`
	RecoveryKey  string     `json:"-"` // Never expose in JSON
}

// NewTOTPConfig creates a new TOTP configuration.
func NewTOTPConfig(userID string) (*TOTPConfig, error) {
	secret, err := generateTOTPSecret()
	if err != nil {
		return nil, err
	}

	backupCodes, err := generateBackupCodes(10)
	if err != nil {
		return nil, err
	}

	return &TOTPConfig{
		UserID:      userID,
		Secret:      secret,
		Enabled:     false,
		Verified:    false,
		CreatedAt:   time.Now(),
		BackupCodes: backupCodes,
	}, nil
}

// Verify marks the TOTP as verified and enabled.
func (t *TOTPConfig) Verify() {
	now := time.Now()
	t.Verified = true
	t.Enabled = true
	t.VerifiedAt = &now
}

// Disable disables the TOTP.
func (t *TOTPConfig) Disable() {
	t.Enabled = false
}

// RecordUsage records a successful TOTP usage.
func (t *TOTPConfig) RecordUsage() {
	now := time.Now()
	t.LastUsedAt = &now
}

// UseBackupCode attempts to use a backup code.
// Returns true if the code was valid and unused.
func (t *TOTPConfig) UseBackupCode(code string) bool {
	// Check if already used
	for _, used := range t.UsedBackups {
		if used == code {
			return false
		}
	}

	// Check if valid
	for _, valid := range t.BackupCodes {
		if valid == code {
			t.UsedBackups = append(t.UsedBackups, code)
			return true
		}
	}

	return false
}

// RemainingBackupCodes returns the count of unused backup codes.
func (t *TOTPConfig) RemainingBackupCodes() int {
	return len(t.BackupCodes) - len(t.UsedBackups)
}

// RegenerateBackupCodes generates new backup codes.
func (t *TOTPConfig) RegenerateBackupCodes() ([]string, error) {
	codes, err := generateBackupCodes(10)
	if err != nil {
		return nil, err
	}
	t.BackupCodes = codes
	t.UsedBackups = nil
	return codes, nil
}

// generateTOTPSecret generates a random TOTP secret.
func generateTOTPSecret() (string, error) {
	secret := make([]byte, 20)
	if _, err := rand.Read(secret); err != nil {
		return "", err
	}
	return base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(secret), nil
}

// generateBackupCodes generates random backup codes.
func generateBackupCodes(count int) ([]string, error) {
	codes := make([]string, count)
	for i := 0; i < count; i++ {
		code := make([]byte, 4)
		if _, err := rand.Read(code); err != nil {
			return nil, err
		}
		// Format as XXXX-XXXX
		codes[i] = base32.StdEncoding.WithPadding(base32.NoPadding).EncodeToString(code)[:8]
	}
	return codes, nil
}

// TOTPSetupResponse represents the response for TOTP setup.
type TOTPSetupResponse struct {
	Secret      string   `json:"secret"`
	QRCodeURL   string   `json:"qr_code_url"`
	BackupCodes []string `json:"backup_codes"`
}
