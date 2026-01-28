// Package redis provides Redis client infrastructure for TetraCore Hub.
package redis

import (
	"context"
	"fmt"
	"regexp"
	"sync"
	"time"

	"github.com/tetra/core-hub/pkg/logger"
)

// CleanupPattern defines a pattern for key cleanup with retention period.
type CleanupPattern struct {
	Pattern   string
	Retention time.Duration
}

// MonitorConfig holds configuration for Redis memory monitor.
type MonitorConfig struct {
	CheckInterval     time.Duration
	MemoryThreshold   float64 // Percentage (0.0-1.0)
	CleanupPatterns   []CleanupPattern
	DefaultTTL        time.Duration
	PeriodicCleanup   time.Duration
	EnableAutoCleanup bool
}

// DefaultMonitorConfig returns default monitor configuration.
func DefaultMonitorConfig() MonitorConfig {
	return MonitorConfig{
		CheckInterval:   2 * time.Minute,
		MemoryThreshold: 0.80, // 80%
		CleanupPatterns: []CleanupPattern{
			{Pattern: "tasks:*", Retention: 7 * 24 * time.Hour},      // 7 days
			{Pattern: "results:*", Retention: 3 * 24 * time.Hour},    // 3 days
			{Pattern: "metrics:*", Retention: 24 * time.Hour},        // 1 day
			{Pattern: "temp:*", Retention: 6 * time.Hour},            // 6 hours
			{Pattern: "sessions:*", Retention: 30 * 24 * time.Hour},  // 30 days
		},
		DefaultTTL:        24 * time.Hour,
		PeriodicCleanup:   1 * time.Hour,
		EnableAutoCleanup: true,
	}
}

// MonitorStats holds monitoring statistics.
type MonitorStats struct {
	CleanupRuns     int64
	KeysDeleted     int64
	LastCleanup     time.Time
	MemoryUsedBytes int64
	MemoryMaxBytes  int64
	MemoryPercent   float64
	mu              sync.RWMutex
}

// Update updates the stats atomically.
func (s *MonitorStats) Update(deleted int64, memUsed, memMax int64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.CleanupRuns++
	s.KeysDeleted += deleted
	s.LastCleanup = time.Now().UTC()
	s.MemoryUsedBytes = memUsed
	s.MemoryMaxBytes = memMax
	if memMax > 0 {
		s.MemoryPercent = float64(memUsed) / float64(memMax)
	}
}

// GetStats returns a copy of stats.
func (s *MonitorStats) GetStats() MonitorStats {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return MonitorStats{
		CleanupRuns:     s.CleanupRuns,
		KeysDeleted:     s.KeysDeleted,
		LastCleanup:     s.LastCleanup,
		MemoryUsedBytes: s.MemoryUsedBytes,
		MemoryMaxBytes:  s.MemoryMaxBytes,
		MemoryPercent:   s.MemoryPercent,
	}
}

// Monitor manages Redis memory and performs automatic cleanup.
type Monitor struct {
	client          *Client
	config          MonitorConfig
	stats           *MonitorStats
	log             logger.LogFields
	ctx             context.Context
	cancel          context.CancelFunc
	wg              sync.WaitGroup
	running         bool
	mu              sync.RWMutex
}

// NewMonitor creates a new Redis memory monitor.
func NewMonitor(client *Client, config MonitorConfig) *Monitor {
	ctx, cancel := context.WithCancel(context.Background())
	return &Monitor{
		client: client,
		config: config,
		stats:  &MonitorStats{},
		log:    logger.LogFields{"component": "redis-monitor"},
		ctx:    ctx,
		cancel: cancel,
	}
}

// Start starts the monitoring loop.
func (m *Monitor) Start() error {
	m.mu.Lock()
	if m.running {
		m.mu.Unlock()
		return nil
	}
	m.running = true
	m.mu.Unlock()

	log := logger.WithFields(m.log)
	log.Info().Msg("Starting Redis memory monitor")

	// Start memory check loop
	m.wg.Add(1)
	go m.memoryCheckLoop()

	// Start periodic cleanup loop
	if m.config.EnableAutoCleanup {
		m.wg.Add(1)
		go m.periodicCleanupLoop()
	}

	return nil
}

// Stop stops the monitoring loop.
func (m *Monitor) Stop() error {
	m.mu.Lock()
	if !m.running {
		m.mu.Unlock()
		return nil
	}
	m.running = false
	m.mu.Unlock()

	log := logger.WithFields(m.log)
	log.Info().Msg("Stopping Redis memory monitor")

	m.cancel()
	m.wg.Wait()

	log.Info().Msg("Redis memory monitor stopped")
	return nil
}

// IsRunning returns whether the monitor is running.
func (m *Monitor) IsRunning() bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.running
}

// GetStats returns current monitoring statistics.
func (m *Monitor) GetStats() MonitorStats {
	return m.stats.GetStats()
}

func (m *Monitor) memoryCheckLoop() {
	defer m.wg.Done()
	log := logger.WithFields(m.log)

	ticker := time.NewTicker(m.config.CheckInterval)
	defer ticker.Stop()

	for {
		select {
		case <-m.ctx.Done():
			return
		case <-ticker.C:
			if err := m.checkMemory(); err != nil {
				log.Warn().Err(err).Msg("Memory check failed")
			}
		}
	}
}

func (m *Monitor) periodicCleanupLoop() {
	defer m.wg.Done()
	log := logger.WithFields(m.log)

	ticker := time.NewTicker(m.config.PeriodicCleanup)
	defer ticker.Stop()

	for {
		select {
		case <-m.ctx.Done():
			return
		case <-ticker.C:
			deleted, err := m.runCleanup()
			if err != nil {
				log.Warn().Err(err).Msg("Periodic cleanup failed")
			} else if deleted > 0 {
				log.Info().Int64("deleted", deleted).Msg("Periodic cleanup completed")
			}
		}
	}
}

func (m *Monitor) checkMemory() error {
	log := logger.WithFields(m.log)

	// Get memory info
	info, err := m.client.GetInfo(m.ctx, "memory")
	if err != nil {
		return fmt.Errorf("failed to get memory info: %w", err)
	}

	memUsed, memMax := parseMemoryInfo(info)

	var memPercent float64
	if memMax > 0 {
		memPercent = float64(memUsed) / float64(memMax)
	}

	log.Debug().
		Int64("used_bytes", memUsed).
		Int64("max_bytes", memMax).
		Float64("percent", memPercent*100).
		Msg("Memory check")

	// Check threshold
	if memPercent >= m.config.MemoryThreshold {
		log.Warn().
			Float64("threshold", m.config.MemoryThreshold*100).
			Float64("current", memPercent*100).
			Msg("Memory threshold exceeded, triggering cleanup")

		deleted, err := m.runCleanup()
		if err != nil {
			return fmt.Errorf("cleanup failed: %w", err)
		}

		log.Info().Int64("deleted", deleted).Msg("Threshold cleanup completed")
	}

	return nil
}

func (m *Monitor) runCleanup() (int64, error) {
	log := logger.WithFields(m.log)
	var totalDeleted int64

	for _, pattern := range m.config.CleanupPatterns {
		deleted, err := m.cleanupPattern(pattern)
		if err != nil {
			log.Warn().
				Err(err).
				Str("pattern", pattern.Pattern).
				Msg("Pattern cleanup failed")
			continue
		}
		totalDeleted += deleted
	}

	// Apply default TTL to keys without expiration
	applied, err := m.applyDefaultTTL()
	if err != nil {
		log.Warn().Err(err).Msg("Failed to apply default TTL")
	} else if applied > 0 {
		log.Debug().Int64("keys", applied).Msg("Applied default TTL")
	}

	// Update stats
	info, _ := m.client.GetInfo(m.ctx, "memory")
	memUsed, memMax := parseMemoryInfo(info)
	m.stats.Update(totalDeleted, memUsed, memMax)

	return totalDeleted, nil
}

func (m *Monitor) cleanupPattern(pattern CleanupPattern) (int64, error) {
	log := logger.WithFields(m.log)
	var deleted int64

	// Scan keys matching pattern
	keys, err := m.client.ScanAll(m.ctx, pattern.Pattern)
	if err != nil {
		return 0, fmt.Errorf("scan failed: %w", err)
	}

	cutoff := time.Now().UTC().Add(-pattern.Retention)

	for _, key := range keys {
		// Check key age using TTL or OBJECT IDLETIME
		ttl, err := m.client.TTL(m.ctx, key)
		if err != nil {
			continue
		}

		// If key has no TTL (-1) or is expired, check if we should delete
		if ttl == -1 {
			// Key has no expiration, check idle time via OBJECT command
			// For simplicity, we'll set TTL based on retention
			if err := m.client.Expire(m.ctx, key, pattern.Retention); err == nil {
				continue
			}
		} else if ttl < 0 {
			// Key doesn't exist or error
			continue
		}

		// For keys with very short TTL remaining that match old patterns
		if ttl > 0 && ttl < time.Minute {
			// Let Redis handle naturally
			continue
		}

		// Check if key should be deleted based on pattern retention
		// This is a simplified approach - in production you might track creation time
		if shouldDelete(key, cutoff) {
			if err := m.client.Del(m.ctx, key); err == nil {
				deleted++
			}
		}
	}

	if deleted > 0 {
		log.Debug().
			Str("pattern", pattern.Pattern).
			Int64("deleted", deleted).
			Msg("Pattern cleanup")
	}

	return deleted, nil
}

func (m *Monitor) applyDefaultTTL() (int64, error) {
	var applied int64

	// Get all keys without TTL
	keys, err := m.client.ScanAll(m.ctx, "*")
	if err != nil {
		return 0, err
	}

	for _, key := range keys {
		ttl, err := m.client.TTL(m.ctx, key)
		if err != nil {
			continue
		}

		// If key has no TTL (-1), apply default
		if ttl == -1 {
			if err := m.client.Expire(m.ctx, key, m.config.DefaultTTL); err == nil {
				applied++
			}
		}
	}

	return applied, nil
}

// ForceCleanup triggers an immediate cleanup.
func (m *Monitor) ForceCleanup() (int64, error) {
	return m.runCleanup()
}

// Helper functions

func parseMemoryInfo(info string) (used, max int64) {
	// Parse Redis INFO memory output
	// Format: used_memory:12345\r\nmaxmemory:67890\r\n
	usedRe := regexp.MustCompile(`used_memory:(\d+)`)
	maxRe := regexp.MustCompile(`maxmemory:(\d+)`)

	if matches := usedRe.FindStringSubmatch(info); len(matches) > 1 {
		fmt.Sscanf(matches[1], "%d", &used)
	}
	if matches := maxRe.FindStringSubmatch(info); len(matches) > 1 {
		fmt.Sscanf(matches[1], "%d", &max)
	}

	return used, max
}

func shouldDelete(key string, cutoff time.Time) bool {
	// Simplified check - in production, you might embed timestamps in keys
	// or use a separate metadata store
	// For now, return false to be conservative
	return false
}
