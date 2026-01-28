// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode"
)

// PasswordPolicy defines password requirements.
type PasswordPolicy struct {
	MinLength        int           `json:"min_length"`
	MaxLength        int           `json:"max_length"`
	RequireUppercase bool          `json:"require_uppercase"`
	RequireLowercase bool          `json:"require_lowercase"`
	RequireDigit     bool          `json:"require_digit"`
	RequireSpecial   bool          `json:"require_special"`
	MaxAge           time.Duration `json:"max_age"`           // Password expiration (0 = no expiration)
	PreventReuse     int           `json:"prevent_reuse"`     // Number of previous passwords to check
	MinStrengthScore int           `json:"min_strength_score"` // Minimum entropy score (0-4)
	AllowCommon      bool          `json:"allow_common"`       // Allow common passwords
}

// Password policy errors
var (
	ErrPasswordTooShort       = errors.New("password is too short")
	ErrPasswordTooLong        = errors.New("password is too long")
	ErrPasswordNoUppercase    = errors.New("password must contain an uppercase letter")
	ErrPasswordNoLowercase    = errors.New("password must contain a lowercase letter")
	ErrPasswordNoDigit        = errors.New("password must contain a digit")
	ErrPasswordNoSpecial      = errors.New("password must contain a special character")
	ErrPasswordTooWeak        = errors.New("password is too weak")
	ErrPasswordIsCommon       = errors.New("password is too common")
)

// DefaultPasswordPolicy returns a sensible default password policy.
func DefaultPasswordPolicy() *PasswordPolicy {
	return &PasswordPolicy{
		MinLength:        8,
		MaxLength:        128,
		RequireUppercase: true,
		RequireLowercase: true,
		RequireDigit:     true,
		RequireSpecial:   false,
		MaxAge:           0, // No expiration by default
		PreventReuse:     5,
		MinStrengthScore: 2, // Moderate strength
		AllowCommon:      false,
	}
}

// StrictPasswordPolicy returns a strict password policy for high-security environments.
func StrictPasswordPolicy() *PasswordPolicy {
	return &PasswordPolicy{
		MinLength:        12,
		MaxLength:        128,
		RequireUppercase: true,
		RequireLowercase: true,
		RequireDigit:     true,
		RequireSpecial:   true,
		MaxAge:           90 * 24 * time.Hour, // 90 days
		PreventReuse:     10,
		MinStrengthScore: 3, // Strong
		AllowCommon:      false,
	}
}

// Validate validates a password against the policy.
func (p *PasswordPolicy) Validate(password string) error {
	// Length checks
	if len(password) < p.MinLength {
		return fmt.Errorf("%w: minimum %d characters required", ErrPasswordTooShort, p.MinLength)
	}
	if p.MaxLength > 0 && len(password) > p.MaxLength {
		return fmt.Errorf("%w: maximum %d characters allowed", ErrPasswordTooLong, p.MaxLength)
	}

	var hasUpper, hasLower, hasDigit, hasSpecial bool
	for _, r := range password {
		switch {
		case unicode.IsUpper(r):
			hasUpper = true
		case unicode.IsLower(r):
			hasLower = true
		case unicode.IsDigit(r):
			hasDigit = true
		case unicode.IsPunct(r) || unicode.IsSymbol(r):
			hasSpecial = true
		}
	}

	if p.RequireUppercase && !hasUpper {
		return ErrPasswordNoUppercase
	}
	if p.RequireLowercase && !hasLower {
		return ErrPasswordNoLowercase
	}
	if p.RequireDigit && !hasDigit {
		return ErrPasswordNoDigit
	}
	if p.RequireSpecial && !hasSpecial {
		return ErrPasswordNoSpecial
	}

	// Check strength score
	score := p.calculateStrength(password)
	if score < p.MinStrengthScore {
		return ErrPasswordTooWeak
	}

	// Check common passwords
	if !p.AllowCommon && p.isCommonPassword(password) {
		return ErrPasswordIsCommon
	}

	return nil
}

// calculateStrength calculates password strength (0-4).
func (p *PasswordPolicy) calculateStrength(password string) int {
	score := 0

	// Length bonus
	if len(password) >= 8 {
		score++
	}
	if len(password) >= 12 {
		score++
	}

	// Character variety bonus
	var hasUpper, hasLower, hasDigit, hasSpecial bool
	for _, r := range password {
		switch {
		case unicode.IsUpper(r):
			hasUpper = true
		case unicode.IsLower(r):
			hasLower = true
		case unicode.IsDigit(r):
			hasDigit = true
		case unicode.IsPunct(r) || unicode.IsSymbol(r):
			hasSpecial = true
		}
	}

	variety := 0
	if hasUpper {
		variety++
	}
	if hasLower {
		variety++
	}
	if hasDigit {
		variety++
	}
	if hasSpecial {
		variety++
	}

	if variety >= 3 {
		score++
	}
	if variety == 4 {
		score++
	}

	// Cap at 4
	if score > 4 {
		score = 4
	}

	return score
}

// isCommonPassword checks if password is in the common passwords list.
func (p *PasswordPolicy) isCommonPassword(password string) bool {
	lower := strings.ToLower(password)
	for _, common := range commonPasswords {
		if lower == common {
			return true
		}
	}
	return false
}

// GetStrengthLabel returns a human-readable strength label.
func GetStrengthLabel(score int) string {
	switch score {
	case 0:
		return "Very Weak"
	case 1:
		return "Weak"
	case 2:
		return "Fair"
	case 3:
		return "Strong"
	case 4:
		return "Very Strong"
	default:
		return "Unknown"
	}
}

// ValidateResult contains detailed validation result.
type ValidateResult struct {
	Valid         bool     `json:"valid"`
	Score         int      `json:"score"`
	ScoreLabel    string   `json:"score_label"`
	Errors        []string `json:"errors,omitempty"`
	Suggestions   []string `json:"suggestions,omitempty"`
}

// ValidateWithDetails validates a password and returns detailed results.
func (p *PasswordPolicy) ValidateWithDetails(password string) ValidateResult {
	result := ValidateResult{
		Valid: true,
	}

	// Length checks
	if len(password) < p.MinLength {
		result.Valid = false
		result.Errors = append(result.Errors, fmt.Sprintf("Password must be at least %d characters", p.MinLength))
	}
	if p.MaxLength > 0 && len(password) > p.MaxLength {
		result.Valid = false
		result.Errors = append(result.Errors, fmt.Sprintf("Password must be at most %d characters", p.MaxLength))
	}

	var hasUpper, hasLower, hasDigit, hasSpecial bool
	for _, r := range password {
		switch {
		case unicode.IsUpper(r):
			hasUpper = true
		case unicode.IsLower(r):
			hasLower = true
		case unicode.IsDigit(r):
			hasDigit = true
		case unicode.IsPunct(r) || unicode.IsSymbol(r):
			hasSpecial = true
		}
	}

	if p.RequireUppercase && !hasUpper {
		result.Valid = false
		result.Errors = append(result.Errors, "Password must contain an uppercase letter")
	}
	if p.RequireLowercase && !hasLower {
		result.Valid = false
		result.Errors = append(result.Errors, "Password must contain a lowercase letter")
	}
	if p.RequireDigit && !hasDigit {
		result.Valid = false
		result.Errors = append(result.Errors, "Password must contain a digit")
	}
	if p.RequireSpecial && !hasSpecial {
		result.Valid = false
		result.Errors = append(result.Errors, "Password must contain a special character")
	}

	// Calculate strength
	result.Score = p.calculateStrength(password)
	result.ScoreLabel = GetStrengthLabel(result.Score)

	if result.Score < p.MinStrengthScore {
		result.Valid = false
		result.Errors = append(result.Errors, "Password is too weak")
	}

	// Check common passwords
	if !p.AllowCommon && p.isCommonPassword(password) {
		result.Valid = false
		result.Errors = append(result.Errors, "This password is too common")
	}

	// Suggestions
	if !hasUpper {
		result.Suggestions = append(result.Suggestions, "Add uppercase letters")
	}
	if !hasLower {
		result.Suggestions = append(result.Suggestions, "Add lowercase letters")
	}
	if !hasDigit {
		result.Suggestions = append(result.Suggestions, "Add numbers")
	}
	if !hasSpecial {
		result.Suggestions = append(result.Suggestions, "Add special characters")
	}
	if len(password) < 12 {
		result.Suggestions = append(result.Suggestions, "Use 12 or more characters")
	}

	return result
}

// Common passwords list (abbreviated)
var commonPasswords = []string{
	"password", "123456", "12345678", "qwerty", "abc123",
	"monkey", "1234567", "letmein", "trustno1", "dragon",
	"baseball", "iloveyou", "master", "sunshine", "ashley",
	"bailey", "passw0rd", "shadow", "123123", "654321",
	"superman", "qazwsx", "michael", "football", "password1",
	"password123", "welcome", "jesus", "ninja", "mustang",
	"password1!", "admin", "administrator", "root", "guest",
	"login", "welcome1", "changeme", "test", "testing",
}
