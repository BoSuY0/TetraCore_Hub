// Package security provides security infrastructure for TetraCore Hub.
package security

import (
	"errors"

	"golang.org/x/crypto/bcrypt"
)

// PasswordConfig holds password hashing configuration.
type PasswordConfig struct {
	Cost int
}

// DefaultPasswordConfig returns default password configuration.
func DefaultPasswordConfig() PasswordConfig {
	return PasswordConfig{
		Cost: bcrypt.DefaultCost, // 10
	}
}

// PasswordManager handles password hashing and verification.
type PasswordManager struct {
	cost int
}

// NewPasswordManager creates a new password manager.
func NewPasswordManager(cfg PasswordConfig) *PasswordManager {
	cost := cfg.Cost
	if cost < bcrypt.MinCost {
		cost = bcrypt.DefaultCost
	}
	if cost > bcrypt.MaxCost {
		cost = bcrypt.MaxCost
	}
	return &PasswordManager{cost: cost}
}

// HashPassword hashes a password using bcrypt.
func (m *PasswordManager) HashPassword(password string) (string, error) {
	if password == "" {
		return "", errors.New("password cannot be empty")
	}

	// bcrypt has a max password length of 72 bytes
	if len(password) > 72 {
		password = password[:72]
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(password), m.cost)
	if err != nil {
		return "", err
	}

	return string(hash), nil
}

// VerifyPassword verifies a password against a hash.
func (m *PasswordManager) VerifyPassword(password, hash string) bool {
	if password == "" || hash == "" {
		return false
	}

	// bcrypt has a max password length of 72 bytes
	if len(password) > 72 {
		password = password[:72]
	}

	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
	return err == nil
}

// NeedsRehash checks if a hash needs to be regenerated with current cost.
func (m *PasswordManager) NeedsRehash(hash string) bool {
	cost, err := bcrypt.Cost([]byte(hash))
	if err != nil {
		return true
	}
	return cost != m.cost
}

// GetCost returns the current bcrypt cost.
func (m *PasswordManager) GetCost() int {
	return m.cost
}

// SetCost updates the bcrypt cost for new passwords.
func (m *PasswordManager) SetCost(cost int) {
	if cost >= bcrypt.MinCost && cost <= bcrypt.MaxCost {
		m.cost = cost
	}
}

// ValidatePasswordStrength checks if a password meets minimum requirements.
func ValidatePasswordStrength(password string, minLength int, requireUppercase, requireLowercase, requireDigit, requireSpecial bool) error {
	if len(password) < minLength {
		return errors.New("password too short")
	}

	var hasUpper, hasLower, hasDigit, hasSpecial bool

	for _, c := range password {
		switch {
		case c >= 'A' && c <= 'Z':
			hasUpper = true
		case c >= 'a' && c <= 'z':
			hasLower = true
		case c >= '0' && c <= '9':
			hasDigit = true
		case isSpecialChar(c):
			hasSpecial = true
		}
	}

	if requireUppercase && !hasUpper {
		return errors.New("password must contain at least one uppercase letter")
	}
	if requireLowercase && !hasLower {
		return errors.New("password must contain at least one lowercase letter")
	}
	if requireDigit && !hasDigit {
		return errors.New("password must contain at least one digit")
	}
	if requireSpecial && !hasSpecial {
		return errors.New("password must contain at least one special character")
	}

	return nil
}

func isSpecialChar(c rune) bool {
	specials := "!@#$%^&*()_+-=[]{}|;':\",./<>?"
	for _, s := range specials {
		if c == s {
			return true
		}
	}
	return false
}

// HashPasswordWithSalt creates a salted hash (bcrypt handles salt internally).
func HashPasswordWithSalt(password string) (string, error) {
	pm := NewPasswordManager(DefaultPasswordConfig())
	return pm.HashPassword(password)
}

// VerifyPasswordWithSalt verifies a password against a salted hash.
func VerifyPasswordWithSalt(password, hash string) bool {
	pm := NewPasswordManager(DefaultPasswordConfig())
	return pm.VerifyPassword(password, hash)
}

// BCryptHasher is an alias for PasswordManager for backward compatibility.
type BCryptHasher = PasswordManager

// DefaultCost is the default bcrypt cost.
const DefaultCost = bcrypt.DefaultCost

// NewBCryptHasher creates a new BCrypt hasher with the specified cost.
func NewBCryptHasher(cost int) *BCryptHasher {
	return NewPasswordManager(PasswordConfig{Cost: cost})
}

// Hash hashes a password (alias for HashPassword).
func (m *PasswordManager) Hash(password string) (string, error) {
	return m.HashPassword(password)
}

// Verify verifies a password against a hash (alias for VerifyPassword).
func (m *PasswordManager) Verify(password, hash string) bool {
	return m.VerifyPassword(password, hash)
}
