// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"errors"
	"time"
)

// UserStatus represents the status of a user account.
type UserStatus string

const (
	UserStatusActive   UserStatus = "active"
	UserStatusInactive UserStatus = "inactive"
	UserStatusLocked   UserStatus = "locked"
)

// User represents a system user.
type User struct {
	ID                 string     `json:"id"`
	Username           string     `json:"username"`
	Email              string     `json:"email,omitempty"`
	PasswordHash       string     `json:"-"` // Never expose
	RoleID             RoleID     `json:"role_id"`
	Status             UserStatus `json:"status"`
	FailedLoginAttempts int       `json:"failed_login_attempts"`
	LockedUntil        *time.Time `json:"locked_until,omitempty"`
	LastLoginAt        *time.Time `json:"last_login_at,omitempty"`
	LastLoginIP        string     `json:"last_login_ip,omitempty"`
	PasswordChangedAt  *time.Time `json:"password_changed_at,omitempty"`
	PasswordHistory    []string   `json:"-"` // For password reuse prevention
	TOTPEnabled        bool       `json:"totp_enabled"`
	TOTPSecret         string     `json:"-"` // Never expose
	BackupCodes        []string   `json:"-"` // Never expose
	Metadata           UserMetadata `json:"metadata,omitempty"`
	CreatedAt          time.Time  `json:"created_at"`
	UpdatedAt          time.Time  `json:"updated_at"`
}

// UserMetadata contains additional user information.
type UserMetadata struct {
	DisplayName string `json:"display_name,omitempty"`
	Avatar      string `json:"avatar,omitempty"`
	Timezone    string `json:"timezone,omitempty"`
	Locale      string `json:"locale,omitempty"`
}

// User errors
var (
	ErrUserNotFound      = errors.New("user not found")
	ErrUserAlreadyExists = errors.New("user already exists")
	ErrUserLocked        = errors.New("user account is locked")
	ErrUserInactive      = errors.New("user account is inactive")
	ErrInvalidPassword   = errors.New("invalid password")
	ErrPasswordReused    = errors.New("password has been used before")
	ErrPasswordExpired   = errors.New("password has expired")
)

// NewUser creates a new User.
func NewUser(username, email, passwordHash string, roleID RoleID) *User {
	now := time.Now().UTC()
	return &User{
		ID:                GenerateID(),
		Username:          username,
		Email:             email,
		PasswordHash:      passwordHash,
		RoleID:            roleID,
		Status:            UserStatusActive,
		PasswordChangedAt: &now,
		PasswordHistory:   []string{passwordHash},
		CreatedAt:         now,
		UpdatedAt:         now,
	}
}

// IsActive returns true if the user account is active.
func (u *User) IsActive() bool {
	return u.Status == UserStatusActive
}

// IsLocked returns true if the user account is currently locked.
func (u *User) IsLocked() bool {
	if u.Status == UserStatusLocked {
		if u.LockedUntil == nil {
			return true // Permanently locked
		}
		return time.Now().Before(*u.LockedUntil)
	}
	return false
}

// Lock locks the user account for the specified duration.
func (u *User) Lock(duration time.Duration) {
	u.Status = UserStatusLocked
	until := time.Now().Add(duration)
	u.LockedUntil = &until
	u.UpdatedAt = time.Now().UTC()
}

// Unlock unlocks the user account.
func (u *User) Unlock() {
	u.Status = UserStatusActive
	u.LockedUntil = nil
	u.FailedLoginAttempts = 0
	u.UpdatedAt = time.Now().UTC()
}

// RecordFailedLogin records a failed login attempt.
func (u *User) RecordFailedLogin() {
	u.FailedLoginAttempts++
	u.UpdatedAt = time.Now().UTC()
}

// RecordSuccessfulLogin records a successful login.
func (u *User) RecordSuccessfulLogin(ip string) {
	now := time.Now().UTC()
	u.FailedLoginAttempts = 0
	u.LastLoginAt = &now
	u.LastLoginIP = ip
	u.UpdatedAt = now
}

// UpdatePassword updates the user's password.
func (u *User) UpdatePassword(newPasswordHash string, keepHistory int) {
	now := time.Now().UTC()

	// Add to password history
	u.PasswordHistory = append([]string{u.PasswordHash}, u.PasswordHistory...)
	if len(u.PasswordHistory) > keepHistory {
		u.PasswordHistory = u.PasswordHistory[:keepHistory]
	}

	u.PasswordHash = newPasswordHash
	u.PasswordChangedAt = &now
	u.UpdatedAt = now
}

// IsPasswordInHistory checks if a password hash is in the user's history.
func (u *User) IsPasswordInHistory(passwordHash string) bool {
	for _, hash := range u.PasswordHistory {
		if hash == passwordHash {
			return true
		}
	}
	return false
}

// Enable2FA enables two-factor authentication.
func (u *User) Enable2FA(secret string, backupCodes []string) {
	u.TOTPEnabled = true
	u.TOTPSecret = secret
	u.BackupCodes = backupCodes
	u.UpdatedAt = time.Now().UTC()
}

// Disable2FA disables two-factor authentication.
func (u *User) Disable2FA() {
	u.TOTPEnabled = false
	u.TOTPSecret = ""
	u.BackupCodes = nil
	u.UpdatedAt = time.Now().UTC()
}

// UseBackupCode uses a backup code and removes it from the list.
func (u *User) UseBackupCode(code string) bool {
	for i, bc := range u.BackupCodes {
		if bc == code {
			u.BackupCodes = append(u.BackupCodes[:i], u.BackupCodes[i+1:]...)
			u.UpdatedAt = time.Now().UTC()
			return true
		}
	}
	return false
}

// UserPublic returns a public-safe representation of the user.
type UserPublic struct {
	ID          string       `json:"id"`
	Username    string       `json:"username"`
	Email       string       `json:"email,omitempty"`
	RoleID      RoleID       `json:"role_id"`
	Status      UserStatus   `json:"status"`
	TOTPEnabled bool         `json:"totp_enabled"`
	LastLoginAt *time.Time   `json:"last_login_at,omitempty"`
	Metadata    UserMetadata `json:"metadata,omitempty"`
	CreatedAt   time.Time    `json:"created_at"`
	UpdatedAt   time.Time    `json:"updated_at"`
}

// ToPublic converts User to UserPublic.
func (u *User) ToPublic() UserPublic {
	return UserPublic{
		ID:          u.ID,
		Username:    u.Username,
		Email:       u.Email,
		RoleID:      u.RoleID,
		Status:      u.Status,
		TOTPEnabled: u.TOTPEnabled,
		LastLoginAt: u.LastLoginAt,
		Metadata:    u.Metadata,
		CreatedAt:   u.CreatedAt,
		UpdatedAt:   u.UpdatedAt,
	}
}
