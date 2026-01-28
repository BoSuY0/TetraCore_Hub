// Package security provides security infrastructure for TetraCore Hub.
package security

import (
	"context"
	"testing"
	"time"
)

// Password Manager Tests

func TestNewPasswordManager(t *testing.T) {
	cfg := DefaultPasswordConfig()
	pm := NewPasswordManager(cfg)

	if pm == nil {
		t.Fatal("Expected non-nil PasswordManager")
	}

	if pm.GetCost() != 10 {
		t.Errorf("Expected default cost 10, got %d", pm.GetCost())
	}
}

func TestPasswordManager_HashPassword(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4}) // Use low cost for tests

	hash, err := pm.HashPassword("testpassword123")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if hash == "" {
		t.Error("Hash should not be empty")
	}

	if hash == "testpassword123" {
		t.Error("Hash should be different from password")
	}
}

func TestPasswordManager_HashPassword_Empty(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})

	_, err := pm.HashPassword("")
	if err == nil {
		t.Error("Expected error for empty password")
	}
}

func TestPasswordManager_HashPassword_LongPassword(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})

	// Password longer than 72 bytes
	longPassword := "a" + string(make([]byte, 100))
	hash, err := pm.HashPassword(longPassword)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if hash == "" {
		t.Error("Hash should not be empty")
	}
}

func TestPasswordManager_VerifyPassword(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})

	password := "testpassword123"
	hash, err := pm.HashPassword(password)
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if !pm.VerifyPassword(password, hash) {
		t.Error("Password verification failed")
	}

	if pm.VerifyPassword("wrongpassword", hash) {
		t.Error("Wrong password should not verify")
	}
}

func TestPasswordManager_VerifyPassword_Empty(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})

	hash, _ := pm.HashPassword("testpassword")

	if pm.VerifyPassword("", hash) {
		t.Error("Empty password should not verify")
	}

	if pm.VerifyPassword("testpassword", "") {
		t.Error("Empty hash should not verify")
	}
}

func TestPasswordManager_NeedsRehash(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})
	hash, _ := pm.HashPassword("testpassword")

	// Same cost - no rehash needed
	if pm.NeedsRehash(hash) {
		t.Error("Should not need rehash with same cost")
	}

	// Different cost - rehash needed
	pm.SetCost(5)
	if !pm.NeedsRehash(hash) {
		t.Error("Should need rehash with different cost")
	}
}

func TestPasswordManager_SetCost(t *testing.T) {
	pm := NewPasswordManager(PasswordConfig{Cost: 4})

	pm.SetCost(6)
	if pm.GetCost() != 6 {
		t.Errorf("Expected cost 6, got %d", pm.GetCost())
	}

	// Try to set invalid cost
	pm.SetCost(1) // Below minimum
	if pm.GetCost() != 6 {
		t.Error("Cost should not change with invalid value")
	}

	pm.SetCost(100) // Above maximum
	if pm.GetCost() != 6 {
		t.Error("Cost should not change with invalid value")
	}
}

func TestValidatePasswordStrength(t *testing.T) {
	tests := []struct {
		password         string
		minLength        int
		requireUppercase bool
		requireLowercase bool
		requireDigit     bool
		requireSpecial   bool
		wantErr          bool
	}{
		{"Password1!", 8, true, true, true, true, false},
		{"short", 8, false, false, false, false, true},      // Too short
		{"lowercase1!", 8, true, true, true, true, true},    // Missing uppercase
		{"UPPERCASE1!", 8, true, true, true, true, true},    // Missing lowercase
		{"Password!", 8, true, true, true, true, true},      // Missing digit
		{"Password1", 8, true, true, true, true, true},      // Missing special
		{"password", 4, false, true, false, false, false},   // Only lowercase required
	}

	for _, tt := range tests {
		err := ValidatePasswordStrength(tt.password, tt.minLength, tt.requireUppercase, tt.requireLowercase, tt.requireDigit, tt.requireSpecial)
		if (err != nil) != tt.wantErr {
			t.Errorf("ValidatePasswordStrength(%q) error = %v, wantErr = %v", tt.password, err, tt.wantErr)
		}
	}
}

func TestHashPasswordWithSalt(t *testing.T) {
	hash, err := HashPasswordWithSalt("testpassword")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if hash == "" {
		t.Error("Hash should not be empty")
	}
}

func TestVerifyPasswordWithSalt(t *testing.T) {
	password := "testpassword"
	hash, _ := HashPasswordWithSalt(password)

	if !VerifyPasswordWithSalt(password, hash) {
		t.Error("Password verification failed")
	}

	if VerifyPasswordWithSalt("wrongpassword", hash) {
		t.Error("Wrong password should not verify")
	}
}

// Rate Limiter Tests

func TestDefaultRateLimitConfig(t *testing.T) {
	cfg := DefaultRateLimitConfig()

	if cfg.Requests != 1000 {
		t.Errorf("Expected Requests 1000, got %d", cfg.Requests)
	}

	if cfg.Window != time.Minute {
		t.Errorf("Expected Window 1 minute, got %v", cfg.Window)
	}

	if cfg.BurstSize != 10 {
		t.Errorf("Expected BurstSize 10, got %d", cfg.BurstSize)
	}
}

func TestNewInMemoryRateLimiter(t *testing.T) {
	cfg := RateLimitConfig{Requests: 100, Window: time.Minute, BurstSize: 5}
	limiter := NewInMemoryRateLimiter(cfg)

	if limiter == nil {
		t.Fatal("Expected non-nil rate limiter")
	}

	if limiter.config.Requests != 100 {
		t.Errorf("Expected Requests 100, got %d", limiter.config.Requests)
	}
}

func TestInMemoryRateLimiter_Allow(t *testing.T) {
	cfg := RateLimitConfig{Requests: 3, Window: time.Second, BurstSize: 0}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// First 3 requests should be allowed
	for i := 0; i < 3; i++ {
		result, err := limiter.Allow(ctx, "test-key")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if !result.Allowed {
			t.Errorf("Request %d should be allowed", i+1)
		}
	}

	// 4th request should be denied
	result, err := limiter.Allow(ctx, "test-key")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if result.Allowed {
		t.Error("Request 4 should be denied")
	}
	if result.RetryAfter <= 0 {
		t.Error("RetryAfter should be positive")
	}
}

func TestInMemoryRateLimiter_AllowWithBurst(t *testing.T) {
	cfg := RateLimitConfig{Requests: 2, Window: time.Second, BurstSize: 2}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Should allow Requests + BurstSize = 4 requests
	for i := 0; i < 4; i++ {
		result, err := limiter.Allow(ctx, "test-key")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if !result.Allowed {
			t.Errorf("Request %d should be allowed (burst)", i+1)
		}
	}

	// 5th request should be denied
	result, _ := limiter.Allow(ctx, "test-key")
	if result.Allowed {
		t.Error("Request 5 should be denied")
	}
}

func TestInMemoryRateLimiter_Reset(t *testing.T) {
	cfg := RateLimitConfig{Requests: 2, Window: time.Second, BurstSize: 0}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Use up all requests
	limiter.Allow(ctx, "test-key")
	limiter.Allow(ctx, "test-key")

	result, _ := limiter.Allow(ctx, "test-key")
	if result.Allowed {
		t.Error("Should be rate limited")
	}

	// Reset
	err := limiter.Reset(ctx, "test-key")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	// Should be allowed again
	result, _ = limiter.Allow(ctx, "test-key")
	if !result.Allowed {
		t.Error("Should be allowed after reset")
	}
}

func TestInMemoryRateLimiter_GetStatus(t *testing.T) {
	cfg := RateLimitConfig{Requests: 5, Window: time.Second, BurstSize: 2}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Check status for non-existent key
	result, err := limiter.GetStatus(ctx, "new-key")
	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}
	if !result.Allowed {
		t.Error("New key should be allowed")
	}
	if result.Remaining != 7 { // Requests + BurstSize
		t.Errorf("Expected remaining 7, got %d", result.Remaining)
	}

	// Use some requests
	limiter.Allow(ctx, "test-key")
	limiter.Allow(ctx, "test-key")

	result, _ = limiter.GetStatus(ctx, "test-key")
	if result.Remaining != 5 { // 7 - 2
		t.Errorf("Expected remaining 5, got %d", result.Remaining)
	}
}

func TestInMemoryRateLimiter_Cleanup(t *testing.T) {
	cfg := RateLimitConfig{Requests: 5, Window: 10 * time.Millisecond, BurstSize: 0}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Create some buckets
	limiter.Allow(ctx, "key1")
	limiter.Allow(ctx, "key2")

	if len(limiter.buckets) != 2 {
		t.Errorf("Expected 2 buckets, got %d", len(limiter.buckets))
	}

	// Wait for window to expire (2x window)
	time.Sleep(25 * time.Millisecond)

	// Cleanup
	removed := limiter.Cleanup()
	if removed != 2 {
		t.Errorf("Expected 2 removed, got %d", removed)
	}

	if len(limiter.buckets) != 0 {
		t.Errorf("Expected 0 buckets after cleanup, got %d", len(limiter.buckets))
	}
}

func TestInMemoryRateLimiter_WindowReset(t *testing.T) {
	cfg := RateLimitConfig{Requests: 2, Window: 20 * time.Millisecond, BurstSize: 0}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Use up all requests
	limiter.Allow(ctx, "test-key")
	limiter.Allow(ctx, "test-key")

	result, _ := limiter.Allow(ctx, "test-key")
	if result.Allowed {
		t.Error("Should be rate limited")
	}

	// Wait for window to reset
	time.Sleep(25 * time.Millisecond)

	// Should be allowed after window reset
	result, _ = limiter.Allow(ctx, "test-key")
	if !result.Allowed {
		t.Error("Should be allowed after window reset")
	}
}

func TestRateLimitResult(t *testing.T) {
	now := time.Now()
	result := &RateLimitResult{
		Allowed:    true,
		Remaining:  5,
		ResetAt:    now.Add(time.Minute),
		RetryAfter: 0,
	}

	if !result.Allowed {
		t.Error("Expected Allowed true")
	}

	if result.Remaining != 5 {
		t.Errorf("Expected Remaining 5, got %d", result.Remaining)
	}

	if result.ResetAt.Before(now) {
		t.Error("ResetAt should be in the future")
	}
}

func TestInMemoryRateLimiter_DifferentKeys(t *testing.T) {
	cfg := RateLimitConfig{Requests: 2, Window: time.Second, BurstSize: 0}
	limiter := NewInMemoryRateLimiter(cfg)
	ctx := context.Background()

	// Use up requests for key1
	limiter.Allow(ctx, "key1")
	limiter.Allow(ctx, "key1")

	result1, _ := limiter.Allow(ctx, "key1")
	if result1.Allowed {
		t.Error("key1 should be rate limited")
	}

	// key2 should still have quota
	result2, _ := limiter.Allow(ctx, "key2")
	if !result2.Allowed {
		t.Error("key2 should be allowed")
	}
}
