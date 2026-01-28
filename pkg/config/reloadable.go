// Package config provides configuration loading and hot-reload for TetraCore Hub.
package config

import (
	"sync"
	"sync/atomic"

	"github.com/tetra/core-hub/pkg/logger"
)

// ReloadableConfig provides thread-safe access to configuration with hot-reload support.
type ReloadableConfig struct {
	config    atomic.Pointer[Config]
	listeners []ConfigChangeListener
	mu        sync.RWMutex
	log       logger.LogFields
}

// ConfigChangeListener is notified when specific config sections change.
type ConfigChangeListener interface {
	OnConfigChange(old, new *Config)
}

// ConfigChangeFunc is a function adapter for ConfigChangeListener.
type ConfigChangeFunc func(old, new *Config)

// OnConfigChange implements ConfigChangeListener.
func (f ConfigChangeFunc) OnConfigChange(old, new *Config) {
	f(old, new)
}

// NewReloadableConfig creates a new ReloadableConfig with initial configuration.
func NewReloadableConfig(initial *Config) *ReloadableConfig {
	rc := &ReloadableConfig{
		listeners: make([]ConfigChangeListener, 0),
		log:       logger.LogFields{"component": "reloadable-config"},
	}
	rc.config.Store(initial)
	return rc
}

// Get returns the current configuration.
func (rc *ReloadableConfig) Get() *Config {
	return rc.config.Load()
}

// Update atomically updates the configuration and notifies listeners.
func (rc *ReloadableConfig) Update(newConfig *Config) {
	oldConfig := rc.config.Swap(newConfig)

	// Notify listeners
	rc.mu.RLock()
	listeners := make([]ConfigChangeListener, len(rc.listeners))
	copy(listeners, rc.listeners)
	rc.mu.RUnlock()

	log := logger.WithFields(rc.log)
	for _, listener := range listeners {
		func() {
			defer func() {
				if r := recover(); r != nil {
					log.Error().Interface("panic", r).Msg("Config change listener panic recovered")
				}
			}()
			listener.OnConfigChange(oldConfig, newConfig)
		}()
	}
}

// AddListener adds a configuration change listener.
func (rc *ReloadableConfig) AddListener(listener ConfigChangeListener) {
	rc.mu.Lock()
	defer rc.mu.Unlock()
	rc.listeners = append(rc.listeners, listener)
}

// AddListenerFunc adds a function as a configuration change listener.
func (rc *ReloadableConfig) AddListenerFunc(fn func(old, new *Config)) {
	rc.AddListener(ConfigChangeFunc(fn))
}

// ReloadHandler creates a ReloadCallback for use with ConfigWatcher.
func (rc *ReloadableConfig) ReloadHandler() ReloadCallback {
	return func(newConfig *Config) error {
		rc.Update(newConfig)
		return nil
	}
}

// Section-specific getters for convenience and type safety

// App returns the current app configuration.
func (rc *ReloadableConfig) App() AppConfig {
	return rc.Get().App
}

// Server returns the current server configuration.
func (rc *ReloadableConfig) Server() ServerConfig {
	return rc.Get().Server
}

// WebSocket returns the current WebSocket configuration.
func (rc *ReloadableConfig) WebSocket() WebSocketConfig {
	return rc.Get().WebSocket
}

// Auth returns the current auth configuration.
func (rc *ReloadableConfig) Auth() AuthConfig {
	return rc.Get().Auth
}

// Redis returns the current Redis configuration.
func (rc *ReloadableConfig) Redis() RedisConfig {
	return rc.Get().Redis
}

// Security returns the current security configuration.
func (rc *ReloadableConfig) Security() SecurityConfig {
	return rc.Get().Security
}

// Metrics returns the current metrics configuration.
func (rc *ReloadableConfig) Metrics() MetricsConfig {
	return rc.Get().Metrics
}

// Logging returns the current logging configuration.
func (rc *ReloadableConfig) Logging() logger.Config {
	return rc.Get().Logging
}

// ConfigDiff represents changes between two configurations.
type ConfigDiff struct {
	AppChanged       bool
	ServerChanged    bool
	WebSocketChanged bool
	AuthChanged      bool
	RedisChanged     bool
	SecurityChanged  bool
	MetricsChanged   bool
	LoggingChanged   bool
}

// Diff compares two configurations and returns what changed.
func Diff(old, new *Config) ConfigDiff {
	return ConfigDiff{
		AppChanged:       old.App != new.App,
		ServerChanged:    old.Server != new.Server,
		WebSocketChanged: old.WebSocket != new.WebSocket,
		AuthChanged:      !authConfigEqual(old.Auth, new.Auth),
		RedisChanged:     !redisConfigEqual(old.Redis, new.Redis),
		SecurityChanged:  !securityConfigEqual(old.Security, new.Security),
		MetricsChanged:   old.Metrics != new.Metrics,
		LoggingChanged:   old.Logging != new.Logging,
	}
}

// HasChanges returns true if any section changed.
func (d ConfigDiff) HasChanges() bool {
	return d.AppChanged || d.ServerChanged || d.WebSocketChanged ||
		d.AuthChanged || d.RedisChanged || d.SecurityChanged ||
		d.MetricsChanged || d.LoggingChanged
}

// Helper functions for comparing slices

func authConfigEqual(a, b AuthConfig) bool {
	return a.RequireAuth == b.RequireAuth &&
		a.AdminUsername == b.AdminUsername &&
		a.AdminPassword == b.AdminPassword &&
		a.AdminPasswordHash == b.AdminPasswordHash &&
		a.JWTSecret == b.JWTSecret &&
		a.JWTIssuer == b.JWTIssuer &&
		a.SessionDuration == b.SessionDuration &&
		a.TokenRefreshThreshold == b.TokenRefreshThreshold &&
		a.MaxLoginAttempts == b.MaxLoginAttempts &&
		a.LockoutDuration == b.LockoutDuration &&
		a.CleanupInterval == b.CleanupInterval
}

func redisConfigEqual(a, b RedisConfig) bool {
	if a.URL != b.URL || a.TLSEnabled != b.TLSEnabled ||
		a.MaxConnections != b.MaxConnections || a.MinIdleConns != b.MinIdleConns {
		return false
	}
	if !stringSliceEqual(a.SentinelURLs, b.SentinelURLs) {
		return false
	}
	if !stringSliceEqual(a.ClusterNodes, b.ClusterNodes) {
		return false
	}
	return true
}

func securityConfigEqual(a, b SecurityConfig) bool {
	if !stringSliceEqual(a.AllowedOrigins, b.AllowedOrigins) {
		return false
	}
	return a.AuthToken == b.AuthToken &&
		a.AuthTokenActive == b.AuthTokenActive &&
		a.AuthTokenNext == b.AuthTokenNext &&
		a.EnableTokenRotation == b.EnableTokenRotation &&
		a.TokenRotationInterval == b.TokenRotationInterval &&
		a.RateLimitRequests == b.RateLimitRequests &&
		a.RateLimitWindow == b.RateLimitWindow &&
		a.EnableCompression == b.EnableCompression
}

func stringSliceEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
