// Package config provides configuration loading and hot-reload for TetraCore Hub.
package config

import (
	"context"
	"fmt"
	"path/filepath"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/tetra/core-hub/pkg/logger"
)

// ConfigWatcher watches config files for changes and triggers reloads.
type ConfigWatcher struct {
	watcher     *fsnotify.Watcher
	configPaths []string
	callbacks   []ReloadCallback
	mu          sync.RWMutex
	log         logger.LogFields
	debounce    time.Duration
	lastReload  time.Time
	closeCh     chan struct{}
	wg          sync.WaitGroup
}

// ReloadCallback is called when configuration changes.
type ReloadCallback func(newConfig *Config) error

// WatcherConfig holds configuration for the watcher.
type WatcherConfig struct {
	ConfigPaths []string      // Paths to watch
	Debounce    time.Duration // Minimum time between reloads
}

// DefaultWatcherConfig returns default watcher configuration.
func DefaultWatcherConfig() WatcherConfig {
	return WatcherConfig{
		ConfigPaths: []string{
			".",
			"./config",
			"/etc/tetracore/",
		},
		Debounce: 2 * time.Second,
	}
}

// NewWatcher creates a new ConfigWatcher.
func NewWatcher(cfg WatcherConfig) (*ConfigWatcher, error) {
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, fmt.Errorf("failed to create fsnotify watcher: %w", err)
	}

	cw := &ConfigWatcher{
		watcher:     watcher,
		configPaths: cfg.ConfigPaths,
		callbacks:   make([]ReloadCallback, 0),
		log:         logger.LogFields{"component": "config-watcher"},
		debounce:    cfg.Debounce,
		closeCh:     make(chan struct{}),
	}

	// Add watch paths
	for _, path := range cfg.ConfigPaths {
		if err := cw.addWatchPath(path); err != nil {
			// Log but don't fail - path might not exist
			log := logger.WithFields(cw.log)
			log.Debug().Err(err).Str("path", path).Msg("Could not watch path")
		}
	}

	return cw, nil
}

// addWatchPath adds a path to watch.
func (cw *ConfigWatcher) addWatchPath(path string) error {
	absPath, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	return cw.watcher.Add(absPath)
}

// OnReload registers a callback to be called when configuration reloads.
func (cw *ConfigWatcher) OnReload(callback ReloadCallback) {
	cw.mu.Lock()
	defer cw.mu.Unlock()
	cw.callbacks = append(cw.callbacks, callback)
}

// Start starts watching for configuration changes.
func (cw *ConfigWatcher) Start(ctx context.Context) {
	cw.wg.Add(1)
	go cw.watch(ctx)
}

// watch is the main watch loop.
func (cw *ConfigWatcher) watch(ctx context.Context) {
	defer cw.wg.Done()
	log := logger.WithFields(cw.log)
	log.Info().Msg("Config watcher started")

	for {
		select {
		case <-ctx.Done():
			log.Info().Msg("Config watcher stopped (context cancelled)")
			return
		case <-cw.closeCh:
			log.Info().Msg("Config watcher stopped")
			return
		case event, ok := <-cw.watcher.Events:
			if !ok {
				return
			}
			cw.handleEvent(event)
		case err, ok := <-cw.watcher.Errors:
			if !ok {
				return
			}
			log.Error().Err(err).Msg("Config watcher error")
		}
	}
}

// handleEvent handles a file system event.
func (cw *ConfigWatcher) handleEvent(event fsnotify.Event) {
	log := logger.WithFields(cw.log)

	// Only handle write and create events
	if event.Op&(fsnotify.Write|fsnotify.Create) == 0 {
		return
	}

	// Only handle config files
	filename := filepath.Base(event.Name)
	if !isConfigFile(filename) {
		return
	}

	log.Debug().Str("file", event.Name).Str("op", event.Op.String()).Msg("Config file event")

	// Debounce
	cw.mu.Lock()
	if time.Since(cw.lastReload) < cw.debounce {
		cw.mu.Unlock()
		return
	}
	cw.lastReload = time.Now()
	cw.mu.Unlock()

	// Trigger reload
	cw.triggerReload()
}

// triggerReload reloads configuration and notifies callbacks.
func (cw *ConfigWatcher) triggerReload() {
	log := logger.WithFields(cw.log)
	log.Info().Msg("Reloading configuration...")

	// Load new configuration
	newConfig, err := Load()
	if err != nil {
		log.Error().Err(err).Msg("Failed to load new configuration")
		return
	}

	// Validate configuration
	if err := newConfig.Validate(); err != nil {
		log.Error().Err(err).Msg("New configuration is invalid")
		return
	}

	// Notify callbacks
	cw.mu.RLock()
	callbacks := make([]ReloadCallback, len(cw.callbacks))
	copy(callbacks, cw.callbacks)
	cw.mu.RUnlock()

	for i, callback := range callbacks {
		if err := callback(newConfig); err != nil {
			log.Error().Err(err).Int("callback_index", i).Msg("Callback failed during config reload")
		}
	}

	log.Info().Msg("Configuration reloaded successfully")
}

// Stop stops the config watcher.
func (cw *ConfigWatcher) Stop() {
	close(cw.closeCh)
	cw.watcher.Close()
	cw.wg.Wait()
}

// isConfigFile checks if a filename is a config file.
func isConfigFile(filename string) bool {
	configFiles := []string{
		"config.yaml",
		"config.yml",
		"config.json",
		"config.toml",
		".env",
	}
	for _, cf := range configFiles {
		if filename == cf {
			return true
		}
	}
	return false
}
