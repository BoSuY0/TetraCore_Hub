// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// SessionRepository defines the interface for session data access.
type SessionRepository interface {
	// Save stores a session.
	Save(ctx context.Context, session *entity.Session) error

	// Get retrieves a session by ID.
	Get(ctx context.Context, sessionID string) (*entity.Session, error)

	// GetByToken retrieves a session by access token.
	GetByToken(ctx context.Context, token string) (*entity.Session, error)

	// GetByRefreshToken retrieves a session by refresh token.
	GetByRefreshToken(ctx context.Context, token string) (*entity.Session, error)

	// GetByUser retrieves all sessions for a user.
	GetByUser(ctx context.Context, userID string) ([]*entity.Session, error)

	// GetAll retrieves all sessions.
	GetAll(ctx context.Context) ([]*entity.Session, error)

	// Delete removes a session.
	Delete(ctx context.Context, sessionID string) error

	// DeleteByUser removes all sessions for a user.
	DeleteByUser(ctx context.Context, userID string) error

	// DeleteExpired removes expired sessions.
	DeleteExpired(ctx context.Context) (int64, error)

	// Touch updates the last activity time.
	Touch(ctx context.Context, sessionID string) error

	// Extend extends a session's expiration.
	Extend(ctx context.Context, sessionID string, duration time.Duration) error

	// Invalidate marks a session as inactive.
	Invalidate(ctx context.Context, sessionID string) error

	// RefreshTokens generates new tokens for a session.
	RefreshTokens(ctx context.Context, sessionID string) (*entity.Session, error)

	// Count returns the total number of active sessions.
	Count(ctx context.Context) (int64, error)

	// CountByUser returns the count of sessions for a user.
	CountByUser(ctx context.Context, userID string) (int64, error)

	// Exists checks if a session exists and is valid.
	Exists(ctx context.Context, sessionID string) (bool, error)
}

// LoginAttemptRepository defines the interface for login attempt tracking.
type LoginAttemptRepository interface {
	// Record records a login attempt.
	Record(ctx context.Context, username, ipAddress string, success bool, failureReason string) error

	// GetRecentAttempts retrieves recent login attempts for a user/IP.
	GetRecentAttempts(ctx context.Context, username, ipAddress string, window time.Duration) ([]entity.LoginAttempt, error)

	// IsLocked checks if a user/IP is locked out.
	IsLocked(ctx context.Context, username, ipAddress string) (bool, error)

	// GetLockoutRemaining returns the remaining lockout time.
	GetLockoutRemaining(ctx context.Context, username, ipAddress string) (time.Duration, error)

	// ClearAttempts clears login attempts for a user/IP.
	ClearAttempts(ctx context.Context, username, ipAddress string) error

	// CleanOld removes old login attempt records.
	CleanOld(ctx context.Context, olderThan time.Duration) error
}

// TokenBlacklistRepository defines the interface for token blacklisting.
type TokenBlacklistRepository interface {
	// Add adds a token to the blacklist.
	Add(ctx context.Context, token string, expiresAt time.Time) error

	// IsBlacklisted checks if a token is blacklisted.
	IsBlacklisted(ctx context.Context, token string) (bool, error)

	// Remove removes a token from the blacklist.
	Remove(ctx context.Context, token string) error

	// CleanExpired removes expired tokens from the blacklist.
	CleanExpired(ctx context.Context) (int64, error)

	// Count returns the number of blacklisted tokens.
	Count(ctx context.Context) (int64, error)
}
