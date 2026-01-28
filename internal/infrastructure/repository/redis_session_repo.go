// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	sessionKeyPrefix      = "session:"
	sessionSetKey         = "sessions"
	sessionUserSetKey     = "sessions:user:"
	sessionTokenKey       = "sessions:token:"
	sessionRefreshKey     = "sessions:refresh:"
	loginAttemptKeyPrefix = "login_attempts:"
	tokenBlacklistKey     = "tokens:blacklist:"
)

// RedisSessionRepository implements SessionRepository using Redis.
type RedisSessionRepository struct {
	client *redis.Client
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisSessionRepository creates a new Redis session repository.
func NewRedisSessionRepository(client *redis.Client, ttl time.Duration) *RedisSessionRepository {
	return &RedisSessionRepository{
		client: client,
		ttl:    ttl,
		log:    logger.LogFields{"component": "redis-session-repo"},
	}
}

// Save stores a session.
func (r *RedisSessionRepository) Save(ctx context.Context, session *entity.Session) error {
	data, err := json.Marshal(session)
	if err != nil {
		return fmt.Errorf("failed to marshal session: %w", err)
	}

	// Calculate TTL based on session expiration
	ttl := time.Until(session.ExpiresAt)
	if ttl <= 0 {
		ttl = r.ttl
	}

	key := sessionKeyPrefix + session.SessionID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, ttl)
	pipe.SAdd(ctx, sessionSetKey, session.SessionID)
	pipe.SAdd(ctx, sessionUserSetKey+session.UserID, session.SessionID)
	pipe.Set(ctx, sessionTokenKey+session.AccessToken, session.SessionID, ttl)
	pipe.Set(ctx, sessionRefreshKey+session.RefreshToken, session.SessionID, ttl)

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a session by ID.
func (r *RedisSessionRepository) Get(ctx context.Context, sessionID string) (*entity.Session, error) {
	key := sessionKeyPrefix + sessionID
	data, err := r.client.Get(ctx, key)
	if err != nil {
		return nil, ErrSessionNotFound
	}

	var session entity.Session
	if err := json.Unmarshal([]byte(data), &session); err != nil {
		return nil, fmt.Errorf("failed to unmarshal session: %w", err)
	}

	return &session, nil
}

// GetByToken retrieves a session by access token.
func (r *RedisSessionRepository) GetByToken(ctx context.Context, token string) (*entity.Session, error) {
	sessionID, err := r.client.Get(ctx, sessionTokenKey+token)
	if err != nil {
		return nil, ErrSessionNotFound
	}

	return r.Get(ctx, sessionID)
}

// GetByRefreshToken retrieves a session by refresh token.
func (r *RedisSessionRepository) GetByRefreshToken(ctx context.Context, token string) (*entity.Session, error) {
	sessionID, err := r.client.Get(ctx, sessionRefreshKey+token)
	if err != nil {
		return nil, ErrSessionNotFound
	}

	return r.Get(ctx, sessionID)
}

// GetByUser retrieves all sessions for a user.
func (r *RedisSessionRepository) GetByUser(ctx context.Context, userID string) ([]*entity.Session, error) {
	sessionIDs, err := r.client.SMembers(ctx, sessionUserSetKey+userID)
	if err != nil {
		return nil, err
	}

	sessions := make([]*entity.Session, 0, len(sessionIDs))
	for _, id := range sessionIDs {
		session, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		sessions = append(sessions, session)
	}

	return sessions, nil
}

// GetAll retrieves all sessions.
func (r *RedisSessionRepository) GetAll(ctx context.Context) ([]*entity.Session, error) {
	sessionIDs, err := r.client.SMembers(ctx, sessionSetKey)
	if err != nil {
		return nil, err
	}

	sessions := make([]*entity.Session, 0, len(sessionIDs))
	for _, id := range sessionIDs {
		session, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		sessions = append(sessions, session)
	}

	return sessions, nil
}

// Delete removes a session.
func (r *RedisSessionRepository) Delete(ctx context.Context, sessionID string) error {
	session, err := r.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, sessionKeyPrefix+sessionID)
	pipe.SRem(ctx, sessionSetKey, sessionID)
	pipe.SRem(ctx, sessionUserSetKey+session.UserID, sessionID)
	pipe.Del(ctx, sessionTokenKey+session.AccessToken)
	pipe.Del(ctx, sessionRefreshKey+session.RefreshToken)

	_, err = pipe.Exec(ctx)
	return err
}

// DeleteByUser removes all sessions for a user.
func (r *RedisSessionRepository) DeleteByUser(ctx context.Context, userID string) error {
	sessions, err := r.GetByUser(ctx, userID)
	if err != nil {
		return err
	}

	for _, session := range sessions {
		if err := r.Delete(ctx, session.SessionID); err != nil {
			continue
		}
	}

	return nil
}

// DeleteExpired removes expired sessions.
func (r *RedisSessionRepository) DeleteExpired(ctx context.Context) (int64, error) {
	sessions, err := r.GetAll(ctx)
	if err != nil {
		return 0, err
	}

	var deleted int64
	for _, session := range sessions {
		if session.IsExpired() {
			if err := r.Delete(ctx, session.SessionID); err == nil {
				deleted++
			}
		}
	}

	return deleted, nil
}

// Touch updates the last activity time.
func (r *RedisSessionRepository) Touch(ctx context.Context, sessionID string) error {
	session, err := r.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	session.Touch()
	return r.Save(ctx, session)
}

// Extend extends a session's expiration.
func (r *RedisSessionRepository) Extend(ctx context.Context, sessionID string, duration time.Duration) error {
	session, err := r.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	session.Extend(duration)
	return r.Save(ctx, session)
}

// Invalidate marks a session as inactive.
func (r *RedisSessionRepository) Invalidate(ctx context.Context, sessionID string) error {
	session, err := r.Get(ctx, sessionID)
	if err != nil {
		return err
	}

	session.Invalidate()
	return r.Save(ctx, session)
}

// RefreshTokens generates new tokens for a session.
func (r *RedisSessionRepository) RefreshTokens(ctx context.Context, sessionID string) (*entity.Session, error) {
	session, err := r.Get(ctx, sessionID)
	if err != nil {
		return nil, err
	}

	// Delete old token mappings
	r.client.Del(ctx, sessionTokenKey+session.AccessToken)
	r.client.Del(ctx, sessionRefreshKey+session.RefreshToken)

	// Generate new tokens
	session.RefreshTokens()

	if err := r.Save(ctx, session); err != nil {
		return nil, err
	}

	return session, nil
}

// Count returns the total number of active sessions.
func (r *RedisSessionRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, sessionSetKey)
}

// CountByUser returns the count of sessions for a user.
func (r *RedisSessionRepository) CountByUser(ctx context.Context, userID string) (int64, error) {
	return r.client.SCard(ctx, sessionUserSetKey+userID)
}

// Exists checks if a session exists and is valid.
func (r *RedisSessionRepository) Exists(ctx context.Context, sessionID string) (bool, error) {
	exists, err := r.client.Exists(ctx, sessionKeyPrefix+sessionID)
	return exists > 0, err
}

// Repository errors
var (
	ErrSessionNotFound = fmt.Errorf("session not found")
)

// Ensure interface compliance
var _ repository.SessionRepository = (*RedisSessionRepository)(nil)

// RedisLoginAttemptRepository implements LoginAttemptRepository using Redis.
type RedisLoginAttemptRepository struct {
	client          *redis.Client
	maxAttempts     int
	windowDuration  time.Duration
	lockoutDuration time.Duration
	log             logger.LogFields
}

// NewRedisLoginAttemptRepository creates a new Redis login attempt repository.
func NewRedisLoginAttemptRepository(
	client *redis.Client,
	maxAttempts int,
	windowDuration, lockoutDuration time.Duration,
) *RedisLoginAttemptRepository {
	return &RedisLoginAttemptRepository{
		client:          client,
		maxAttempts:     maxAttempts,
		windowDuration:  windowDuration,
		lockoutDuration: lockoutDuration,
		log:             logger.LogFields{"component": "redis-login-attempt-repo"},
	}
}

// Record records a login attempt.
func (r *RedisLoginAttemptRepository) Record(ctx context.Context, username, ipAddress string, success bool, failureReason string) error {
	key := loginAttemptKeyPrefix + username + ":" + ipAddress

	attempt := entity.LoginAttempt{
		Username:      username,
		IPAddress:     ipAddress,
		Timestamp:     time.Now().UTC(),
		Success:       success,
		FailureReason: failureReason,
	}

	data, err := json.Marshal(attempt)
	if err != nil {
		return err
	}

	pipe := r.client.Pipeline()
	pipe.LPush(ctx, key, data)
	pipe.Expire(ctx, key, r.lockoutDuration)

	_, err = pipe.Exec(ctx)
	return err
}

// GetRecentAttempts retrieves recent login attempts for a user/IP.
func (r *RedisLoginAttemptRepository) GetRecentAttempts(ctx context.Context, username, ipAddress string, window time.Duration) ([]entity.LoginAttempt, error) {
	key := loginAttemptKeyPrefix + username + ":" + ipAddress
	data, err := r.client.LRange(ctx, key, 0, -1)
	if err != nil {
		return nil, err
	}

	cutoff := time.Now().UTC().Add(-window)
	attempts := make([]entity.LoginAttempt, 0)

	for _, item := range data {
		var attempt entity.LoginAttempt
		if err := json.Unmarshal([]byte(item), &attempt); err != nil {
			continue
		}
		if attempt.Timestamp.After(cutoff) {
			attempts = append(attempts, attempt)
		}
	}

	return attempts, nil
}

// IsLocked checks if a user/IP is locked out.
func (r *RedisLoginAttemptRepository) IsLocked(ctx context.Context, username, ipAddress string) (bool, error) {
	attempts, err := r.GetRecentAttempts(ctx, username, ipAddress, r.windowDuration)
	if err != nil {
		return false, err
	}

	failedCount := 0
	for _, a := range attempts {
		if !a.Success {
			failedCount++
		}
	}

	return failedCount >= r.maxAttempts, nil
}

// GetLockoutRemaining returns the remaining lockout time.
func (r *RedisLoginAttemptRepository) GetLockoutRemaining(ctx context.Context, username, ipAddress string) (time.Duration, error) {
	locked, err := r.IsLocked(ctx, username, ipAddress)
	if err != nil || !locked {
		return 0, err
	}

	attempts, err := r.GetRecentAttempts(ctx, username, ipAddress, r.windowDuration)
	if err != nil {
		return 0, err
	}

	// Find oldest failed attempt in window
	var oldest time.Time
	for _, a := range attempts {
		if !a.Success && (oldest.IsZero() || a.Timestamp.Before(oldest)) {
			oldest = a.Timestamp
		}
	}

	if oldest.IsZero() {
		return 0, nil
	}

	lockoutEnd := oldest.Add(r.lockoutDuration)
	remaining := time.Until(lockoutEnd)
	if remaining < 0 {
		return 0, nil
	}

	return remaining, nil
}

// ClearAttempts clears login attempts for a user/IP.
func (r *RedisLoginAttemptRepository) ClearAttempts(ctx context.Context, username, ipAddress string) error {
	key := loginAttemptKeyPrefix + username + ":" + ipAddress
	return r.client.Del(ctx, key)
}

// CleanOld removes old login attempt records.
func (r *RedisLoginAttemptRepository) CleanOld(ctx context.Context, olderThan time.Duration) error {
	// Redis handles TTL automatically, but we can clean up explicitly
	keys, err := r.client.Keys(ctx, loginAttemptKeyPrefix+"*")
	if err != nil {
		return err
	}

	for _, key := range keys {
		// Check if key should be deleted based on content age
		data, err := r.client.LRange(ctx, key, 0, -1)
		if err != nil {
			continue
		}

		allOld := true
		cutoff := time.Now().UTC().Add(-olderThan)
		for _, item := range data {
			var attempt entity.LoginAttempt
			if err := json.Unmarshal([]byte(item), &attempt); err != nil {
				continue
			}
			if attempt.Timestamp.After(cutoff) {
				allOld = false
				break
			}
		}

		if allOld {
			r.client.Del(ctx, key)
		}
	}

	return nil
}

// Ensure interface compliance
var _ repository.LoginAttemptRepository = (*RedisLoginAttemptRepository)(nil)

// RedisTokenBlacklistRepository implements TokenBlacklistRepository using Redis.
type RedisTokenBlacklistRepository struct {
	client *redis.Client
	log    logger.LogFields
}

// NewRedisTokenBlacklistRepository creates a new Redis token blacklist repository.
func NewRedisTokenBlacklistRepository(client *redis.Client) *RedisTokenBlacklistRepository {
	return &RedisTokenBlacklistRepository{
		client: client,
		log:    logger.LogFields{"component": "redis-token-blacklist-repo"},
	}
}

// Add adds a token to the blacklist.
func (r *RedisTokenBlacklistRepository) Add(ctx context.Context, token string, expiresAt time.Time) error {
	ttl := time.Until(expiresAt)
	if ttl <= 0 {
		ttl = time.Hour // Default TTL
	}
	return r.client.Set(ctx, tokenBlacklistKey+token, "1", ttl)
}

// IsBlacklisted checks if a token is blacklisted.
func (r *RedisTokenBlacklistRepository) IsBlacklisted(ctx context.Context, token string) (bool, error) {
	exists, err := r.client.Exists(ctx, tokenBlacklistKey+token)
	return exists > 0, err
}

// Remove removes a token from the blacklist.
func (r *RedisTokenBlacklistRepository) Remove(ctx context.Context, token string) error {
	return r.client.Del(ctx, tokenBlacklistKey+token)
}

// CleanExpired removes expired tokens from the blacklist.
func (r *RedisTokenBlacklistRepository) CleanExpired(ctx context.Context) (int64, error) {
	// Redis handles TTL automatically
	return 0, nil
}

// Count returns the number of blacklisted tokens.
func (r *RedisTokenBlacklistRepository) Count(ctx context.Context) (int64, error) {
	keys, err := r.client.Keys(ctx, tokenBlacklistKey+"*")
	if err != nil {
		return 0, err
	}
	return int64(len(keys)), nil
}

// Ensure interface compliance
var _ repository.TokenBlacklistRepository = (*RedisTokenBlacklistRepository)(nil)
