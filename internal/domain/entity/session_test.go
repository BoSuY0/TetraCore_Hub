// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"testing"
	"time"
)

func TestNewSession(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Hour)

	if session.SessionID == "" {
		t.Error("SessionID should not be empty")
	}

	if session.UserID != "user-1" {
		t.Errorf("Expected UserID 'user-1', got '%s'", session.UserID)
	}

	if session.Username != "testuser" {
		t.Errorf("Expected Username 'testuser', got '%s'", session.Username)
	}

	if session.Role != "admin" {
		t.Errorf("Expected Role 'admin', got '%s'", session.Role)
	}

	if session.AccessToken == "" {
		t.Error("AccessToken should not be empty")
	}

	if session.RefreshToken == "" {
		t.Error("RefreshToken should not be empty")
	}

	if !session.IsActive {
		t.Error("New session should be active")
	}

	// Check expiration is approximately 1 hour from now
	expectedExpiry := time.Now().Add(time.Hour)
	diff := session.ExpiresAt.Sub(expectedExpiry)
	if diff < -time.Second || diff > time.Second {
		t.Errorf("Expiration time is not approximately 1 hour from now")
	}
}

func TestSession_IsExpired(t *testing.T) {
	// Test non-expired session
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	if session.IsExpired() {
		t.Error("Session should not be expired")
	}

	// Test expired session
	expiredSession := NewSession("user-2", "testuser2", "user", time.Millisecond)
	time.Sleep(10 * time.Millisecond)
	if !expiredSession.IsExpired() {
		t.Error("Session should be expired")
	}
}

func TestSession_IsValid(t *testing.T) {
	// Test valid session
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	if !session.IsValid() {
		t.Error("Session should be valid")
	}

	// Test inactive session
	session.Invalidate()
	if session.IsValid() {
		t.Error("Inactive session should not be valid")
	}

	// Test expired session
	expiredSession := NewSession("user-2", "testuser2", "user", time.Millisecond)
	time.Sleep(10 * time.Millisecond)
	if expiredSession.IsValid() {
		t.Error("Expired session should not be valid")
	}
}

func TestSession_Touch(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	initialActivity := session.LastActivity

	time.Sleep(10 * time.Millisecond)
	session.Touch()

	if !session.LastActivity.After(initialActivity) {
		t.Error("LastActivity should be updated after Touch()")
	}
}

func TestSession_Extend(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Minute)
	originalExpiry := session.ExpiresAt

	session.Extend(time.Hour)

	if !session.ExpiresAt.After(originalExpiry) {
		t.Error("ExpiresAt should be extended")
	}

	// Check new expiration is approximately 1 hour from now
	expectedExpiry := time.Now().Add(time.Hour)
	diff := session.ExpiresAt.Sub(expectedExpiry)
	if diff < -time.Second || diff > time.Second {
		t.Errorf("Expiration time is not approximately 1 hour from now")
	}
}

func TestSession_Invalidate(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Hour)

	if !session.IsActive {
		t.Error("Session should be active initially")
	}

	session.Invalidate()

	if session.IsActive {
		t.Error("Session should be inactive after Invalidate()")
	}
}

func TestSession_RefreshTokens(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	originalAccessToken := session.AccessToken
	originalRefreshToken := session.RefreshToken

	session.RefreshTokens()

	if session.AccessToken == originalAccessToken {
		t.Error("AccessToken should be different after RefreshTokens()")
	}

	if session.RefreshToken == originalRefreshToken {
		t.Error("RefreshToken should be different after RefreshTokens()")
	}

	if session.AccessToken == "" {
		t.Error("AccessToken should not be empty")
	}

	if session.RefreshToken == "" {
		t.Error("RefreshToken should not be empty")
	}
}

func TestSession_HasPermission(t *testing.T) {
	// Admin role has all permissions
	adminSession := NewSession("admin-1", "admin", "admin", time.Hour)
	if !adminSession.HasPermission("any_permission") {
		t.Error("Admin should have all permissions")
	}

	// Regular user with specific permissions
	userSession := NewSession("user-1", "testuser", "user", time.Hour)
	userSession.SetPermissions([]string{"read", "write"})

	if !userSession.HasPermission("read") {
		t.Error("User should have 'read' permission")
	}

	if !userSession.HasPermission("write") {
		t.Error("User should have 'write' permission")
	}

	if userSession.HasPermission("delete") {
		t.Error("User should not have 'delete' permission")
	}

	// User with wildcard permission
	wildcardSession := NewSession("user-2", "poweruser", "user", time.Hour)
	wildcardSession.SetPermissions([]string{"*"})

	if !wildcardSession.HasPermission("any_permission") {
		t.Error("User with wildcard should have all permissions")
	}
}

func TestSession_SetPermissions(t *testing.T) {
	session := NewSession("user-1", "testuser", "user", time.Hour)

	if len(session.Permissions) != 0 {
		t.Error("Initial permissions should be empty")
	}

	permissions := []string{"read", "write", "execute"}
	session.SetPermissions(permissions)

	if len(session.Permissions) != 3 {
		t.Errorf("Expected 3 permissions, got %d", len(session.Permissions))
	}

	for i, p := range permissions {
		if session.Permissions[i] != p {
			t.Errorf("Expected permission '%s' at index %d, got '%s'", p, i, session.Permissions[i])
		}
	}
}

func TestSession_GetTimeRemaining(t *testing.T) {
	// Test session with time remaining
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	remaining := session.GetTimeRemaining()

	if remaining < 59*time.Minute || remaining > time.Hour {
		t.Errorf("Expected time remaining around 1 hour, got %v", remaining)
	}

	// Test expired session
	expiredSession := NewSession("user-2", "testuser2", "user", time.Millisecond)
	time.Sleep(10 * time.Millisecond)
	remaining = expiredSession.GetTimeRemaining()

	if remaining != 0 {
		t.Errorf("Expected 0 time remaining for expired session, got %v", remaining)
	}
}

func TestSession_NeedsRefresh(t *testing.T) {
	// Session with plenty of time left
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	if session.NeedsRefresh(30 * time.Minute) {
		t.Error("Session should not need refresh with 1 hour remaining")
	}

	// Session with little time left
	shortSession := NewSession("user-2", "testuser2", "user", 10*time.Minute)
	if !shortSession.NeedsRefresh(30 * time.Minute) {
		t.Error("Session should need refresh with only 10 minutes remaining")
	}
}

func TestSession_ToMap(t *testing.T) {
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	session.IPAddress = "192.168.1.1"

	m := session.ToMap()

	if m["session_id"] != session.SessionID {
		t.Errorf("Expected session_id '%s', got '%v'", session.SessionID, m["session_id"])
	}

	if m["user_id"] != "user-1" {
		t.Errorf("Expected user_id 'user-1', got '%v'", m["user_id"])
	}

	if m["username"] != "testuser" {
		t.Errorf("Expected username 'testuser', got '%v'", m["username"])
	}

	if m["role"] != "admin" {
		t.Errorf("Expected role 'admin', got '%v'", m["role"])
	}

	if m["ip_address"] != "192.168.1.1" {
		t.Errorf("Expected ip_address '192.168.1.1', got '%v'", m["ip_address"])
	}

	if m["is_active"] != true {
		t.Errorf("Expected is_active true, got '%v'", m["is_active"])
	}
}

func TestNewLoginAttemptTracker(t *testing.T) {
	tracker := NewLoginAttemptTracker(5, 15*time.Minute, 30*time.Minute)

	if tracker == nil {
		t.Fatal("Expected non-nil tracker")
	}

	if tracker.maxAttempts != 5 {
		t.Errorf("Expected maxAttempts 5, got %d", tracker.maxAttempts)
	}

	if tracker.windowDuration != 15*time.Minute {
		t.Errorf("Expected windowDuration 15m, got %v", tracker.windowDuration)
	}

	if tracker.lockoutDuration != 30*time.Minute {
		t.Errorf("Expected lockoutDuration 30m, got %v", tracker.lockoutDuration)
	}
}

func TestLoginAttemptTracker_RecordAttempt(t *testing.T) {
	tracker := NewLoginAttemptTracker(3, time.Minute, 5*time.Minute)

	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")

	if tracker.IsLocked("testuser", "192.168.1.1") {
		t.Error("Should not be locked after 1 failed attempt")
	}

	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")
	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")

	if !tracker.IsLocked("testuser", "192.168.1.1") {
		t.Error("Should be locked after 3 failed attempts")
	}
}

func TestLoginAttemptTracker_ClearAttempts(t *testing.T) {
	tracker := NewLoginAttemptTracker(3, time.Minute, 5*time.Minute)

	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")
	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")

	tracker.ClearAttempts("testuser", "192.168.1.1")

	if tracker.IsLocked("testuser", "192.168.1.1") {
		t.Error("Should not be locked after clearing attempts")
	}
}

func TestLoginAttemptTracker_GetLockoutRemaining(t *testing.T) {
	tracker := NewLoginAttemptTracker(2, time.Minute, 5*time.Minute)

	// Not locked yet
	remaining := tracker.GetLockoutRemaining("testuser", "192.168.1.1")
	if remaining != 0 {
		t.Errorf("Expected 0 remaining for unlocked user, got %v", remaining)
	}

	// Lock the user
	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")
	tracker.RecordAttempt("testuser", "192.168.1.1", false, "invalid_password")

	remaining = tracker.GetLockoutRemaining("testuser", "192.168.1.1")
	if remaining <= 0 || remaining > 5*time.Minute {
		t.Errorf("Expected lockout remaining between 0 and 5 minutes, got %v", remaining)
	}
}

func TestNewSessionStore(t *testing.T) {
	store := NewSessionStore()

	if store == nil {
		t.Fatal("Expected non-nil store")
	}

	if store.Count() != 0 {
		t.Errorf("Expected empty store, got count %d", store.Count())
	}
}

func TestSessionStore_Add(t *testing.T) {
	store := NewSessionStore()
	session := NewSession("user-1", "testuser", "admin", time.Hour)

	store.Add(session)

	if store.Count() != 1 {
		t.Errorf("Expected count 1, got %d", store.Count())
	}

	retrieved, exists := store.Get(session.SessionID)
	if !exists {
		t.Error("Session should exist")
	}

	if retrieved.SessionID != session.SessionID {
		t.Error("Retrieved session should match")
	}
}

func TestSessionStore_GetByToken(t *testing.T) {
	store := NewSessionStore()
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	store.Add(session)

	retrieved, exists := store.GetByToken(session.AccessToken)
	if !exists {
		t.Error("Session should be found by token")
	}

	if retrieved.SessionID != session.SessionID {
		t.Error("Retrieved session should match")
	}

	// Test non-existent token
	_, exists = store.GetByToken("invalid-token")
	if exists {
		t.Error("Should not find session with invalid token")
	}
}

func TestSessionStore_GetByUser(t *testing.T) {
	store := NewSessionStore()
	session1 := NewSession("user-1", "testuser", "admin", time.Hour)
	session2 := NewSession("user-1", "testuser", "admin", time.Hour)
	session3 := NewSession("user-2", "otheruser", "user", time.Hour)

	store.Add(session1)
	store.Add(session2)
	store.Add(session3)

	user1Sessions := store.GetByUser("user-1")
	if len(user1Sessions) != 2 {
		t.Errorf("Expected 2 sessions for user-1, got %d", len(user1Sessions))
	}

	user2Sessions := store.GetByUser("user-2")
	if len(user2Sessions) != 1 {
		t.Errorf("Expected 1 session for user-2, got %d", len(user2Sessions))
	}
}

func TestSessionStore_Remove(t *testing.T) {
	store := NewSessionStore()
	session := NewSession("user-1", "testuser", "admin", time.Hour)
	store.Add(session)

	store.Remove(session.SessionID)

	if store.Count() != 0 {
		t.Errorf("Expected count 0 after remove, got %d", store.Count())
	}

	_, exists := store.Get(session.SessionID)
	if exists {
		t.Error("Session should not exist after remove")
	}
}

func TestSessionStore_RemoveByUser(t *testing.T) {
	store := NewSessionStore()
	session1 := NewSession("user-1", "testuser", "admin", time.Hour)
	session2 := NewSession("user-1", "testuser", "admin", time.Hour)
	session3 := NewSession("user-2", "otheruser", "user", time.Hour)

	store.Add(session1)
	store.Add(session2)
	store.Add(session3)

	store.RemoveByUser("user-1")

	if store.Count() != 1 {
		t.Errorf("Expected count 1 after removing user-1 sessions, got %d", store.Count())
	}

	user1Sessions := store.GetByUser("user-1")
	if len(user1Sessions) != 0 {
		t.Errorf("Expected 0 sessions for user-1, got %d", len(user1Sessions))
	}
}

func TestSessionStore_CleanExpired(t *testing.T) {
	store := NewSessionStore()
	validSession := NewSession("user-1", "testuser", "admin", time.Hour)
	expiredSession := NewSession("user-2", "otheruser", "user", time.Millisecond)

	store.Add(validSession)
	store.Add(expiredSession)

	time.Sleep(10 * time.Millisecond)

	cleaned := store.CleanExpired()
	if cleaned != 1 {
		t.Errorf("Expected 1 cleaned session, got %d", cleaned)
	}

	if store.Count() != 1 {
		t.Errorf("Expected count 1 after cleanup, got %d", store.Count())
	}

	_, exists := store.Get(validSession.SessionID)
	if !exists {
		t.Error("Valid session should still exist")
	}

	_, exists = store.Get(expiredSession.SessionID)
	if exists {
		t.Error("Expired session should be removed")
	}
}

func TestSessionStore_GetAll(t *testing.T) {
	store := NewSessionStore()
	session1 := NewSession("user-1", "testuser1", "admin", time.Hour)
	session2 := NewSession("user-2", "testuser2", "user", time.Hour)

	store.Add(session1)
	store.Add(session2)

	sessions := store.GetAll()
	if len(sessions) != 2 {
		t.Errorf("Expected 2 sessions, got %d", len(sessions))
	}
}

func TestGenerateToken(t *testing.T) {
	token1 := generateToken()
	token2 := generateToken()

	if token1 == "" {
		t.Error("Token should not be empty")
	}

	if len(token1) != 64 { // 32 bytes = 64 hex characters
		t.Errorf("Expected token length 64, got %d", len(token1))
	}

	if token1 == token2 {
		t.Error("Tokens should be unique")
	}
}
