// Package security provides security utilities for TetraCore Hub.
package security

import (
	"github.com/tetra/core-hub/internal/domain/entity"
)

// PasswordValidator provides password validation services.
type PasswordValidator struct {
	policy *entity.PasswordPolicy
}

// NewPasswordValidator creates a new PasswordValidator with the given policy.
func NewPasswordValidator(policy *entity.PasswordPolicy) *PasswordValidator {
	if policy == nil {
		policy = entity.DefaultPasswordPolicy()
	}
	return &PasswordValidator{
		policy: policy,
	}
}

// Validate validates a password against the configured policy.
func (v *PasswordValidator) Validate(password string) error {
	return v.policy.Validate(password)
}

// ValidateWithDetails validates and returns detailed results.
func (v *PasswordValidator) ValidateWithDetails(password string) entity.ValidateResult {
	return v.policy.ValidateWithDetails(password)
}

// GetPolicy returns the current password policy.
func (v *PasswordValidator) GetPolicy() *entity.PasswordPolicy {
	return v.policy
}

// SetPolicy updates the password policy.
func (v *PasswordValidator) SetPolicy(policy *entity.PasswordPolicy) {
	v.policy = policy
}

// CheckStrength returns the password strength score.
func (v *PasswordValidator) CheckStrength(password string) (int, string) {
	result := v.policy.ValidateWithDetails(password)
	return result.Score, result.ScoreLabel
}
