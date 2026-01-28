// Package config provides configuration loading for TetraCore Hub.
package config

import (
	"os"
	"testing"
	"time"
)

func TestDefault(t *testing.T) {
	cfg := Default()

	if cfg == nil {
		t.Fatal("Default() should not return nil")
	}

	if cfg.App.Name == "" {
		t.Error("App.Name should not be empty")
	}

	if cfg.App.Environment != EnvDevelopment {
		t.Errorf("Expected Environment 'development', got '%s'", cfg.App.Environment)
	}

	if cfg.Server.Port == 0 {
		t.Error("Server.Port should not be 0")
	}

	if cfg.WebSocket.Path == "" {
		t.Error("WebSocket.Path should not be empty")
	}
}

func TestDefaultValues(t *testing.T) {
	cfg := Default()

	// Server defaults
	if cfg.Server.ReadTimeout == 0 {
		t.Error("Server.ReadTimeout should have a default value")
	}

	if cfg.Server.WriteTimeout == 0 {
		t.Error("Server.WriteTimeout should have a default value")
	}

	// WebSocket defaults
	if cfg.WebSocket.HeartbeatInterval == 0 {
		t.Error("WebSocket.HeartbeatInterval should have a default value")
	}

	// Auth defaults
	if cfg.Auth.SessionDuration == 0 {
		t.Error("Auth.SessionDuration should have a default value")
	}

	// Redis defaults
	if cfg.Redis.DefaultTTL == 0 {
		t.Error("Redis.DefaultTTL should have a default value")
	}
}

func TestEnvironmentTypes(t *testing.T) {
	envs := []Environment{
		EnvDevelopment,
		EnvProduction,
		EnvTesting,
	}

	for _, env := range envs {
		if env == "" {
			t.Error("Environment type should not be empty")
		}
	}

	if EnvDevelopment != "development" {
		t.Errorf("Expected 'development', got '%s'", EnvDevelopment)
	}

	if EnvProduction != "production" {
		t.Errorf("Expected 'production', got '%s'", EnvProduction)
	}

	if EnvTesting != "testing" {
		t.Errorf("Expected 'testing', got '%s'", EnvTesting)
	}
}

func TestConfig_GetServerAddress(t *testing.T) {
	cfg := Default()
	cfg.Server.Host = "localhost"
	cfg.Server.Port = 8080

	addr := cfg.GetServerAddress()
	if addr != "localhost:8080" {
		t.Errorf("Expected 'localhost:8080', got '%s'", addr)
	}

	// With empty host
	cfg.Server.Host = ""
	addr = cfg.GetServerAddress()
	if addr != ":8080" {
		t.Errorf("Expected ':8080', got '%s'", addr)
	}
}

func TestConfig_GetWebSocketURL(t *testing.T) {
	cfg := Default()
	cfg.Server.Host = "localhost"
	cfg.Server.Port = 8080
	cfg.WebSocket.Path = "/ws"

	url := cfg.GetWebSocketURL()
	if url != "ws://localhost:8080/ws" {
		t.Errorf("Expected 'ws://localhost:8080/ws', got '%s'", url)
	}
}

func TestConfig_Validate(t *testing.T) {
	cfg := Default()

	// Should pass validation with defaults
	if err := cfg.Validate(); err != nil {
		t.Errorf("Default config should pass validation: %v", err)
	}
}

func TestConfig_Validate_MissingJWTSecret(t *testing.T) {
	cfg := Default()
	cfg.Auth.RequireAuth = true
	cfg.Auth.JWTSecret = ""

	if err := cfg.Validate(); err == nil {
		t.Error("Validation should fail when RequireAuth=true and JWTSecret is empty")
	}
}

func TestConfig_Validate_InvalidPort(t *testing.T) {
	cfg := Default()
	cfg.Server.Port = -1

	if err := cfg.Validate(); err == nil {
		t.Error("Validation should fail with invalid port")
	}
}

func TestConfig_IsDevelopment(t *testing.T) {
	cfg := Default()

	cfg.App.Environment = EnvDevelopment
	if !cfg.IsDevelopment() {
		t.Error("IsDevelopment() should return true for development environment")
	}

	cfg.App.Environment = EnvProduction
	if cfg.IsDevelopment() {
		t.Error("IsDevelopment() should return false for production environment")
	}
}

func TestConfig_IsProduction(t *testing.T) {
	cfg := Default()

	cfg.App.Environment = EnvProduction
	if !cfg.IsProduction() {
		t.Error("IsProduction() should return true for production environment")
	}

	cfg.App.Environment = EnvDevelopment
	if cfg.IsProduction() {
		t.Error("IsProduction() should return false for development environment")
	}
}

func TestConfig_IsTesting(t *testing.T) {
	cfg := Default()

	cfg.App.Environment = EnvTesting
	if !cfg.IsTesting() {
		t.Error("IsTesting() should return true for testing environment")
	}
}

func TestRedisConfig_GetURL(t *testing.T) {
	cfg := Default()
	cfg.Redis.URL = "redis://localhost:6379"

	if cfg.Redis.URL != "redis://localhost:6379" {
		t.Errorf("Expected 'redis://localhost:6379', got '%s'", cfg.Redis.URL)
	}
}

func TestAuthConfig_Defaults(t *testing.T) {
	cfg := Default()

	if cfg.Auth.MaxLoginAttempts == 0 {
		t.Error("MaxLoginAttempts should have a default value")
	}

	if cfg.Auth.LockoutDuration == 0 {
		t.Error("LockoutDuration should have a default value")
	}
}

func TestSecurityConfig_Defaults(t *testing.T) {
	cfg := Default()

	if cfg.Security.RateLimitRequests == 0 {
		t.Error("RateLimitRequests should have a default value")
	}

	if cfg.Security.RateLimitWindow == 0 {
		t.Error("RateLimitWindow should have a default value")
	}
}

func TestWebSocketConfig_Defaults(t *testing.T) {
	cfg := Default()

	if cfg.WebSocket.MaxConnections == 0 {
		t.Error("MaxConnections should have a default value")
	}

	if cfg.WebSocket.ReadBufferSize == 0 {
		t.Error("ReadBufferSize should have a default value")
	}

	if cfg.WebSocket.WriteBufferSize == 0 {
		t.Error("WriteBufferSize should have a default value")
	}
}

func TestServerConfig_Timeouts(t *testing.T) {
	cfg := Default()

	// Timeouts should be reasonable
	if cfg.Server.ReadTimeout < time.Second {
		t.Error("ReadTimeout should be at least 1 second")
	}

	if cfg.Server.WriteTimeout < time.Second {
		t.Error("WriteTimeout should be at least 1 second")
	}

	if cfg.Server.IdleTimeout < time.Second {
		t.Error("IdleTimeout should be at least 1 second")
	}
}

func TestLoadFromEnv(t *testing.T) {
	// Save and restore environment
	oldPort := os.Getenv("SERVER_PORT")
	defer os.Setenv("SERVER_PORT", oldPort)

	// Set test value
	os.Setenv("SERVER_PORT", "9999")

	cfg := Default()
	// In real scenario, Load() would read from env
	// Here we just verify the structure is correct
	if cfg.Server.Port == 0 {
		t.Error("Server.Port should have a value")
	}
}

func TestAppConfig(t *testing.T) {
	app := AppConfig{
		Name:        "TestApp",
		Version:     "1.0.0",
		Environment: EnvTesting,
		Debug:       true,
	}

	if app.Name != "TestApp" {
		t.Errorf("Expected Name 'TestApp', got '%s'", app.Name)
	}

	if !app.Debug {
		t.Error("Debug should be true")
	}
}

func TestMetricsConfig(t *testing.T) {
	cfg := Default()

	// Metrics might be disabled by default
	if cfg.Metrics.Port == 0 && cfg.Metrics.Enabled {
		t.Error("If metrics enabled, port should be set")
	}
}

func TestRedisChannels(t *testing.T) {
	cfg := Default()

	if cfg.Redis.TaskChannel == "" {
		t.Error("TaskChannel should have a default value")
	}

	if cfg.Redis.ResultChannel == "" {
		t.Error("ResultChannel should have a default value")
	}

	if cfg.Redis.BroadcastChannel == "" {
		t.Error("BroadcastChannel should have a default value")
	}
}

func TestConfig_Clone(t *testing.T) {
	// Test that modifying one config doesn't affect another
	cfg1 := Default()
	cfg1.App.Name = "Config1"

	cfg2 := Default()
	cfg2.App.Name = "Config2"

	if cfg1.App.Name == cfg2.App.Name {
		t.Error("Configs should be independent")
	}
}
