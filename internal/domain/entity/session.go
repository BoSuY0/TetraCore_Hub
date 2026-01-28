// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"

	"github.com/google/uuid"
)

// Session represents an authenticated user session.
type Session struct {
	SessionID     string         `json:"session_id"`
	UserID        string         `json:"user_id"`
	Username      string         `json:"username"`
	Role          string         `json:"role"`
	Permissions   []string       `json:"permissions"`
	AccessToken   string         `json:"access_token"`
	RefreshToken  string         `json:"refresh_token"`
	CreatedAt     time.Time      `json:"created_at"`
	ExpiresAt     time.Time      `json:"expires_at"`
	LastActivity  time.Time      `json:"last_activity"`
	IPAddress     string         `json:"ip_address,omitempty"`
	UserAgent     string         `json:"user_agent,omitempty"`
	Metadata       map[string]any `json:"metadata,omitempty"`
	IsActive       bool           `json:"is_active"`
	ShouldRefresh  bool           `json:"should_refresh,omitempty"` // Indicates if token should be refreshed

	mu sync.RWMutex
}

// NewSession creates a new session.
func NewSession(userID, username, role string, duration time.Duration) *Session {
	now := time.Now().UTC()
	return &Session{
		SessionID:    uuid.New().String(),
		UserID:       userID,
		Username:     username,
		Role:         role,
		Permissions:  []string{},
		AccessToken:  generateToken(),
		RefreshToken: generateToken(),
		CreatedAt:    now,
		ExpiresAt:    now.Add(duration),
		LastActivity: now,
		Metadata:     make(map[string]any),
		IsActive:     true,
	}
}

// generateToken generates a random token.
func generateToken() string {
	bytes := make([]byte, 32)
	rand.Read(bytes)
	return hex.EncodeToString(bytes)
}

// IsExpired checks if the session has expired.
func (s *Session) IsExpired() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return time.Now().UTC().After(s.ExpiresAt)
}

// IsValid checks if the session is valid and active.
func (s *Session) IsValid() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.IsActive && !time.Now().UTC().After(s.ExpiresAt)
}

// Touch updates the last activity time.
func (s *Session) Touch() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.LastActivity = time.Now().UTC()
}

// Extend extends the session expiration.
func (s *Session) Extend(duration time.Duration) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.ExpiresAt = time.Now().UTC().Add(duration)
}

// Invalidate marks the session as inactive.
func (s *Session) Invalidate() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.IsActive = false
}

// RefreshTokens generates new tokens.
func (s *Session) RefreshTokens() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.AccessToken = generateToken()
	s.RefreshToken = generateToken()
}

// HasPermission checks if the session has a specific permission.
func (s *Session) HasPermission(permission string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Admin has all permissions
	if s.Role == "admin" {
		return true
	}

	// Check for wildcard permission
	for _, p := range s.Permissions {
		if p == "*" || p == permission {
			return true
		}
	}

	return false
}

// SetPermissions sets the session permissions.
func (s *Session) SetPermissions(permissions []string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.Permissions = permissions
}

// GetTimeRemaining returns the time remaining until expiration.
func (s *Session) GetTimeRemaining() time.Duration {
	s.mu.RLock()
	defer s.mu.RUnlock()
	remaining := s.ExpiresAt.Sub(time.Now().UTC())
	if remaining < 0 {
		return 0
	}
	return remaining
}

// NeedsRefresh checks if the session needs a token refresh.
func (s *Session) NeedsRefresh(threshold time.Duration) bool {
	return s.GetTimeRemaining() < threshold
}

// ToMap converts the session to a map for JSON serialization.
func (s *Session) ToMap() map[string]any {
	s.mu.RLock()
	defer s.mu.RUnlock()

	return map[string]any{
		"session_id":    s.SessionID,
		"user_id":       s.UserID,
		"username":      s.Username,
		"role":          s.Role,
		"permissions":   s.Permissions,
		"created_at":    s.CreatedAt.Format(time.RFC3339),
		"expires_at":    s.ExpiresAt.Format(time.RFC3339),
		"last_activity": s.LastActivity.Format(time.RFC3339),
		"ip_address":    s.IPAddress,
		"is_active":     s.IsActive,
		"is_valid":      s.IsValid(),
		"time_remaining": s.GetTimeRemaining().String(),
	}
}

// LoginAttempt tracks login attempts for rate limiting.
type LoginAttempt struct {
	Username      string    `json:"username"`
	IPAddress     string    `json:"ip_address"`
	Timestamp     time.Time `json:"timestamp"`
	Success       bool      `json:"success"`
	FailureReason string    `json:"failure_reason,omitempty"`
}

// LoginAttemptTracker tracks login attempts.
type LoginAttemptTracker struct {
	attempts map[string][]LoginAttempt
	mu       sync.RWMutex
	maxAttempts int
	windowDuration time.Duration
	lockoutDuration time.Duration
}

// NewLoginAttemptTracker creates a new login attempt tracker.
func NewLoginAttemptTracker(maxAttempts int, windowDuration, lockoutDuration time.Duration) *LoginAttemptTracker {
	return &LoginAttemptTracker{
		attempts:        make(map[string][]LoginAttempt),
		maxAttempts:     maxAttempts,
		windowDuration:  windowDuration,
		lockoutDuration: lockoutDuration,
	}
}

// RecordAttempt records a login attempt.
func (t *LoginAttemptTracker) RecordAttempt(username, ipAddress string, success bool, failureReason string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	key := username + ":" + ipAddress
	attempt := LoginAttempt{
		Username:      username,
		IPAddress:     ipAddress,
		Timestamp:     time.Now().UTC(),
		Success:       success,
		FailureReason: failureReason,
	}

	t.attempts[key] = append(t.attempts[key], attempt)

	// Clean old attempts
	t.cleanOldAttempts(key)
}

// IsLocked checks if the user/IP is locked out.
func (t *LoginAttemptTracker) IsLocked(username, ipAddress string) bool {
	t.mu.RLock()
	defer t.mu.RUnlock()

	key := username + ":" + ipAddress
	attempts := t.getRecentFailedAttempts(key)

	return len(attempts) >= t.maxAttempts
}

// GetLockoutRemaining returns the remaining lockout time.
func (t *LoginAttemptTracker) GetLockoutRemaining(username, ipAddress string) time.Duration {
	t.mu.RLock()
	defer t.mu.RUnlock()

	key := username + ":" + ipAddress
	attempts := t.getRecentFailedAttempts(key)

	if len(attempts) < t.maxAttempts {
		return 0
	}

	// Find the oldest attempt in the window
	oldest := attempts[0].Timestamp
	for _, a := range attempts {
		if a.Timestamp.Before(oldest) {
			oldest = a.Timestamp
		}
	}

	lockoutEnd := oldest.Add(t.lockoutDuration)
	remaining := lockoutEnd.Sub(time.Now().UTC())
	if remaining < 0 {
		return 0
	}
	return remaining
}

// ClearAttempts clears all attempts for a user/IP (after successful login).
func (t *LoginAttemptTracker) ClearAttempts(username, ipAddress string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	key := username + ":" + ipAddress
	delete(t.attempts, key)
}

func (t *LoginAttemptTracker) getRecentFailedAttempts(key string) []LoginAttempt {
	cutoff := time.Now().UTC().Add(-t.windowDuration)
	var recent []LoginAttempt

	for _, a := range t.attempts[key] {
		if !a.Success && a.Timestamp.After(cutoff) {
			recent = append(recent, a)
		}
	}

	return recent
}

func (t *LoginAttemptTracker) cleanOldAttempts(key string) {
	cutoff := time.Now().UTC().Add(-t.lockoutDuration)
	var cleaned []LoginAttempt

	for _, a := range t.attempts[key] {
		if a.Timestamp.After(cutoff) {
			cleaned = append(cleaned, a)
		}
	}

	t.attempts[key] = cleaned
}

// SessionStore manages sessions in memory.
type SessionStore struct {
	sessions map[string]*Session
	byUser   map[string][]string // userID -> []sessionID
	mu       sync.RWMutex
}

// NewSessionStore creates a new session store.
func NewSessionStore() *SessionStore {
	return &SessionStore{
		sessions: make(map[string]*Session),
		byUser:   make(map[string][]string),
	}
}

// Add adds a session to the store.
func (s *SessionStore) Add(session *Session) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.sessions[session.SessionID] = session
	s.byUser[session.UserID] = append(s.byUser[session.UserID], session.SessionID)
}

// Get retrieves a session by ID.
func (s *SessionStore) Get(sessionID string) (*Session, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	session, exists := s.sessions[sessionID]
	return session, exists
}

// GetByToken retrieves a session by access token.
func (s *SessionStore) GetByToken(token string) (*Session, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, session := range s.sessions {
		if session.AccessToken == token {
			return session, true
		}
	}
	return nil, false
}

// GetByUser retrieves all sessions for a user.
func (s *SessionStore) GetByUser(userID string) []*Session {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var sessions []*Session
	for _, sessionID := range s.byUser[userID] {
		if session, exists := s.sessions[sessionID]; exists {
			sessions = append(sessions, session)
		}
	}
	return sessions
}

// Remove removes a session from the store.
func (s *SessionStore) Remove(sessionID string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	session, exists := s.sessions[sessionID]
	if !exists {
		return
	}

	delete(s.sessions, sessionID)

	// Remove from user's sessions
	userSessions := s.byUser[session.UserID]
	for i, id := range userSessions {
		if id == sessionID {
			s.byUser[session.UserID] = append(userSessions[:i], userSessions[i+1:]...)
			break
		}
	}
}

// RemoveByUser removes all sessions for a user.
func (s *SessionStore) RemoveByUser(userID string) {
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, sessionID := range s.byUser[userID] {
		delete(s.sessions, sessionID)
	}
	delete(s.byUser, userID)
}

// CleanExpired removes expired sessions.
func (s *SessionStore) CleanExpired() int {
	s.mu.Lock()
	defer s.mu.Unlock()

	var expired []string
	for id, session := range s.sessions {
		if session.IsExpired() {
			expired = append(expired, id)
		}
	}

	for _, id := range expired {
		session := s.sessions[id]
		delete(s.sessions, id)

		// Remove from user's sessions
		userSessions := s.byUser[session.UserID]
		for i, sessionID := range userSessions {
			if sessionID == id {
				s.byUser[session.UserID] = append(userSessions[:i], userSessions[i+1:]...)
				break
			}
		}
	}

	return len(expired)
}

// Count returns the number of active sessions.
func (s *SessionStore) Count() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.sessions)
}

// GetAll returns all sessions.
func (s *SessionStore) GetAll() []*Session {
	s.mu.RLock()
	defer s.mu.RUnlock()

	sessions := make([]*Session, 0, len(s.sessions))
	for _, session := range s.sessions {
		sessions = append(sessions, session)
	}
	return sessions
}
