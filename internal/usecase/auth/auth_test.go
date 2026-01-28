// Package auth provides authentication use cases for TetraCore Hub.
package auth

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/infrastructure/security"
)

// ============================================================
// Mock Repositories
// ============================================================

type mockSessionRepo struct {
	mu       sync.RWMutex
	sessions map[string]*entity.Session
}

func newMockSessionRepo() *mockSessionRepo {
	return &mockSessionRepo{
		sessions: make(map[string]*entity.Session),
	}
}

func (r *mockSessionRepo) Save(ctx context.Context, session *entity.Session) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sessions[session.SessionID] = session
	return nil
}

func (r *mockSessionRepo) Get(ctx context.Context, sessionID string) (*entity.Session, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	if s, ok := r.sessions[sessionID]; ok {
		return s, nil
	}
	return nil, errors.New("session not found")
}

func (r *mockSessionRepo) GetByToken(ctx context.Context, token string) (*entity.Session, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, s := range r.sessions {
		if s.AccessToken == token {
			return s, nil
		}
	}
	return nil, errors.New("session not found")
}

func (r *mockSessionRepo) GetByRefreshToken(ctx context.Context, token string) (*entity.Session, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, s := range r.sessions {
		if s.RefreshToken == token {
			return s, nil
		}
	}
	return nil, errors.New("session not found")
}

func (r *mockSessionRepo) GetByUser(ctx context.Context, userID string) ([]*entity.Session, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var result []*entity.Session
	for _, s := range r.sessions {
		if s.UserID == userID {
			result = append(result, s)
		}
	}
	return result, nil
}

func (r *mockSessionRepo) GetAll(ctx context.Context) ([]*entity.Session, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make([]*entity.Session, 0, len(r.sessions))
	for _, s := range r.sessions {
		result = append(result, s)
	}
	return result, nil
}

func (r *mockSessionRepo) Delete(ctx context.Context, sessionID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.sessions, sessionID)
	return nil
}

func (r *mockSessionRepo) DeleteByUser(ctx context.Context, userID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	for id, s := range r.sessions {
		if s.UserID == userID {
			delete(r.sessions, id)
		}
	}
	return nil
}

func (r *mockSessionRepo) DeleteExpired(ctx context.Context) (int64, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var count int64
	for id, s := range r.sessions {
		if s.IsExpired() {
			delete(r.sessions, id)
			count++
		}
	}
	return count, nil
}

func (r *mockSessionRepo) Touch(ctx context.Context, sessionID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if s, ok := r.sessions[sessionID]; ok {
		s.Touch()
	}
	return nil
}

func (r *mockSessionRepo) Extend(ctx context.Context, sessionID string, duration time.Duration) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if s, ok := r.sessions[sessionID]; ok {
		s.ExpiresAt = time.Now().Add(duration)
	}
	return nil
}

func (r *mockSessionRepo) Invalidate(ctx context.Context, sessionID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if s, ok := r.sessions[sessionID]; ok {
		s.IsActive = false
	}
	return nil
}

func (r *mockSessionRepo) RefreshTokens(ctx context.Context, sessionID string) (*entity.Session, error) {
	return r.Get(ctx, sessionID)
}

func (r *mockSessionRepo) Count(ctx context.Context) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return int64(len(r.sessions)), nil
}

func (r *mockSessionRepo) CountByUser(ctx context.Context, userID string) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	var count int64
	for _, s := range r.sessions {
		if s.UserID == userID {
			count++
		}
	}
	return count, nil
}

func (r *mockSessionRepo) Exists(ctx context.Context, sessionID string) (bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.sessions[sessionID]
	return ok, nil
}

type mockLoginAttemptRepo struct {
	attempts map[string]int
	locked   map[string]time.Time
	mu       sync.RWMutex
}

func newMockLoginAttemptRepo() *mockLoginAttemptRepo {
	return &mockLoginAttemptRepo{
		attempts: make(map[string]int),
		locked:   make(map[string]time.Time),
	}
}

func (r *mockLoginAttemptRepo) Record(ctx context.Context, username, ipAddress string, success bool, failureReason string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := username + ":" + ipAddress
	if !success {
		r.attempts[key]++
		if r.attempts[key] >= 5 {
			r.locked[key] = time.Now().Add(15 * time.Minute)
		}
	} else {
		delete(r.attempts, key)
		delete(r.locked, key)
	}
	return nil
}

func (r *mockLoginAttemptRepo) GetRecentAttempts(ctx context.Context, username, ipAddress string, window time.Duration) ([]entity.LoginAttempt, error) {
	return nil, nil
}

func (r *mockLoginAttemptRepo) IsLocked(ctx context.Context, username, ipAddress string) (bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	key := username + ":" + ipAddress
	if lockUntil, ok := r.locked[key]; ok {
		return time.Now().Before(lockUntil), nil
	}
	return false, nil
}

func (r *mockLoginAttemptRepo) GetLockoutRemaining(ctx context.Context, username, ipAddress string) (time.Duration, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	key := username + ":" + ipAddress
	if lockUntil, ok := r.locked[key]; ok {
		return time.Until(lockUntil), nil
	}
	return 0, nil
}

func (r *mockLoginAttemptRepo) ClearAttempts(ctx context.Context, username, ipAddress string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	key := username + ":" + ipAddress
	delete(r.attempts, key)
	delete(r.locked, key)
	return nil
}

func (r *mockLoginAttemptRepo) CleanOld(ctx context.Context, olderThan time.Duration) error {
	return nil
}

type mockTokenBlacklistRepo struct {
	tokens map[string]time.Time
	mu     sync.RWMutex
}

func newMockTokenBlacklistRepo() *mockTokenBlacklistRepo {
	return &mockTokenBlacklistRepo{
		tokens: make(map[string]time.Time),
	}
}

func (r *mockTokenBlacklistRepo) Add(ctx context.Context, token string, expiresAt time.Time) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.tokens[token] = expiresAt
	return nil
}

func (r *mockTokenBlacklistRepo) IsBlacklisted(ctx context.Context, token string) (bool, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	if expiresAt, ok := r.tokens[token]; ok {
		return time.Now().Before(expiresAt), nil
	}
	return false, nil
}

func (r *mockTokenBlacklistRepo) Remove(ctx context.Context, token string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.tokens, token)
	return nil
}

func (r *mockTokenBlacklistRepo) CleanExpired(ctx context.Context) (int64, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	var count int64
	for token, expiresAt := range r.tokens {
		if time.Now().After(expiresAt) {
			delete(r.tokens, token)
			count++
		}
	}
	return count, nil
}

func (r *mockTokenBlacklistRepo) Count(ctx context.Context) (int64, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return int64(len(r.tokens)), nil
}

// ============================================================
// Test Helpers
// ============================================================

func setupAuthUseCase(t *testing.T) (*UseCase, *mockSessionRepo, *mockLoginAttemptRepo, *mockTokenBlacklistRepo) {
	t.Helper()

	sessionRepo := newMockSessionRepo()
	attemptRepo := newMockLoginAttemptRepo()
	blacklistRepo := newMockTokenBlacklistRepo()

	jwtManager := security.NewJWTManagerSimple("test-secret-key-for-testing-only", "test-issuer")
	hasher := security.NewBCryptHasher(4) // Low cost for tests

	// Hash test password
	passwordHash, err := hasher.Hash("testpassword123")
	if err != nil {
		t.Fatalf("Failed to hash test password: %v", err)
	}

	config := Config{
		AdminUsername:         "admin",
		AdminPasswordHash:     passwordHash,
		SessionDuration:       time.Hour,
		TokenRefreshThreshold: 15 * time.Minute,
		MaxLoginAttempts:      5,
		LockoutDuration:       15 * time.Minute,
	}

	uc := NewUseCase(sessionRepo, attemptRepo, blacklistRepo, jwtManager, hasher, config)
	return uc, sessionRepo, attemptRepo, blacklistRepo
}

// ============================================================
// Tests
// ============================================================

func TestLogin_Success(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
		UserAgent: "test-agent",
	}

	output, err := uc.Login(ctx, input)
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}

	if output.Session == nil {
		t.Fatal("Session should not be nil")
	}

	if output.AccessToken == "" {
		t.Error("Access token should not be empty")
	}

	if output.RefreshToken == "" {
		t.Error("Refresh token should not be empty")
	}

	if output.ExpiresAt.Before(time.Now()) {
		t.Error("Expiration time should be in the future")
	}
}

func TestLogin_InvalidUsername(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	input := LoginInput{
		Username:  "wronguser",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	_, err := uc.Login(ctx, input)
	if err == nil {
		t.Fatal("Login should fail with invalid username")
	}
}

func TestLogin_InvalidPassword(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	input := LoginInput{
		Username:  "admin",
		Password:  "wrongpassword",
		IPAddress: "127.0.0.1",
	}

	_, err := uc.Login(ctx, input)
	if err == nil {
		t.Fatal("Login should fail with invalid password")
	}
}

func TestLogout_Success(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// First login
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	output, err := uc.Login(ctx, input)
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}

	// Then logout
	err = uc.Logout(ctx, output.Session.SessionID)
	if err != nil {
		t.Fatalf("Logout failed: %v", err)
	}

	// Try to get session
	_, err = uc.GetSession(ctx, output.Session.SessionID)
	if err == nil {
		t.Error("Session should not exist after logout")
	}
}

func TestValidateToken_Success(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// Login
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	output, err := uc.Login(ctx, input)
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}

	// Validate token
	session, err := uc.ValidateToken(ctx, output.AccessToken)
	if err != nil {
		t.Fatalf("Token validation failed: %v", err)
	}

	if session.SessionID != output.Session.SessionID {
		t.Error("Session ID mismatch")
	}
}

func TestValidateToken_BlacklistedToken(t *testing.T) {
	uc, _, _, blacklistRepo := setupAuthUseCase(t)
	ctx := context.Background()

	// Login
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	output, err := uc.Login(ctx, input)
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}

	// Blacklist the token
	blacklistRepo.Add(ctx, output.AccessToken, time.Now().Add(time.Hour))

	// Validate token should fail
	_, err = uc.ValidateToken(ctx, output.AccessToken)
	if err == nil {
		t.Error("Validation should fail for blacklisted token")
	}
}

func TestRefreshToken_Success(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// Login
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	output, err := uc.Login(ctx, input)
	if err != nil {
		t.Fatalf("Login failed: %v", err)
	}

	// Refresh token
	newOutput, err := uc.RefreshToken(ctx, output.RefreshToken)
	if err != nil {
		t.Fatalf("Token refresh failed: %v", err)
	}

	if newOutput.AccessToken == "" {
		t.Error("New access token should not be empty")
	}

	if newOutput.AccessToken == output.AccessToken {
		t.Error("New access token should be different")
	}
}

func TestLogoutAll_Success(t *testing.T) {
	uc, sessionRepo, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// Login multiple times
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	for i := 0; i < 3; i++ {
		_, err := uc.Login(ctx, input)
		if err != nil {
			t.Fatalf("Login %d failed: %v", i, err)
		}
	}

	// Count sessions
	count, _ := sessionRepo.Count(ctx)
	if count != 3 {
		t.Errorf("Expected 3 sessions, got %d", count)
	}

	// Logout all
	err := uc.LogoutAll(ctx, "admin")
	if err != nil {
		t.Fatalf("LogoutAll failed: %v", err)
	}

	// Count sessions after logout
	count, _ = sessionRepo.Count(ctx)
	if count != 0 {
		t.Errorf("Expected 0 sessions after logout, got %d", count)
	}
}

func TestHashPassword(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)

	password := "mySecurePassword123!"
	hash, err := uc.HashPassword(password)
	if err != nil {
		t.Fatalf("Hash failed: %v", err)
	}

	if hash == "" {
		t.Error("Hash should not be empty")
	}

	// Verify the hash
	if !uc.VerifyPassword(hash, password) {
		t.Error("Password verification should succeed")
	}

	// Verify with wrong password
	if uc.VerifyPassword(hash, "wrongpassword") {
		t.Error("Password verification should fail with wrong password")
	}
}

func TestCleanupExpiredSessions(t *testing.T) {
	uc, sessionRepo, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// Create expired session directly (use negative duration to make it already expired)
	expiredSession := entity.NewSession("testuser", "testuser", "admin", -time.Hour)
	sessionRepo.Save(ctx, expiredSession)

	// Create valid session
	validSession := entity.NewSession("testuser", "testuser", "admin", time.Hour)
	sessionRepo.Save(ctx, validSession)

	// Cleanup
	deleted, err := uc.CleanupExpiredSessions(ctx)
	if err != nil {
		t.Fatalf("Cleanup failed: %v", err)
	}

	if deleted != 1 {
		t.Errorf("Expected 1 deleted, got %d", deleted)
	}

	// Verify only valid session remains
	count, _ := sessionRepo.Count(ctx)
	if count != 1 {
		t.Errorf("Expected 1 session remaining, got %d", count)
	}
}

func TestGetSessionCount(t *testing.T) {
	uc, _, _, _ := setupAuthUseCase(t)
	ctx := context.Background()

	// Login multiple times
	input := LoginInput{
		Username:  "admin",
		Password:  "testpassword123",
		IPAddress: "127.0.0.1",
	}

	for i := 0; i < 5; i++ {
		_, err := uc.Login(ctx, input)
		if err != nil {
			t.Fatalf("Login %d failed: %v", i, err)
		}
	}

	count, err := uc.GetSessionCount(ctx)
	if err != nil {
		t.Fatalf("GetSessionCount failed: %v", err)
	}

	if count != 5 {
		t.Errorf("Expected 5 sessions, got %d", count)
	}
}
