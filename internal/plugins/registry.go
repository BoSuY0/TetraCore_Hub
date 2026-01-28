// Package plugins provides a Lua-based plugin system for TetraCore Hub.
package plugins

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/tetra/core-hub/pkg/logger"
)

// Plugin represents a loaded plugin.
type Plugin struct {
	ID          string     `json:"id"`
	Name        string     `json:"name"`
	Version     string     `json:"version"`
	Author      string     `json:"author"`
	Description string     `json:"description"`
	FilePath    string     `json:"file_path"`
	Hooks       []HookType `json:"hooks"`
	IsEnabled   bool       `json:"is_enabled"`
	LoadedAt    time.Time  `json:"loaded_at"`
	LastError   string     `json:"last_error,omitempty"`
}

// Plugin errors
var (
	ErrPluginNotFound      = errors.New("plugin not found")
	ErrPluginAlreadyLoaded = errors.New("plugin already loaded")
	ErrPluginLoadFailed    = errors.New("failed to load plugin")
	ErrPluginDisabled      = errors.New("plugin is disabled")
)

// Registry manages loaded plugins.
type Registry struct {
	plugins    map[string]*Plugin
	vmPool     *VMPool
	hooks      map[HookType][]string // hookType -> plugin IDs
	pluginsDir string
	mu         sync.RWMutex
	log        logger.LogFields
}

// RegistryConfig holds registry configuration.
type RegistryConfig struct {
	PluginsDir  string
	PoolSize    int
	MaxExecTime time.Duration
	MaxMemory   int64
}

// DefaultRegistryConfig returns default configuration.
func DefaultRegistryConfig() RegistryConfig {
	return RegistryConfig{
		PluginsDir:  "./plugins",
		PoolSize:    4,
		MaxExecTime: 5 * time.Second,
		MaxMemory:   64 * 1024 * 1024, // 64MB
	}
}

// NewRegistry creates a new plugin registry.
func NewRegistry(cfg RegistryConfig) (*Registry, error) {
	vmPool, err := NewVMPool(cfg.PoolSize, cfg.MaxExecTime, cfg.MaxMemory)
	if err != nil {
		return nil, fmt.Errorf("failed to create VM pool: %w", err)
	}

	r := &Registry{
		plugins:    make(map[string]*Plugin),
		vmPool:     vmPool,
		hooks:      make(map[HookType][]string),
		pluginsDir: cfg.PluginsDir,
		log:        logger.LogFields{"component": "plugin-registry"},
	}

	// Initialize hooks map
	for _, hook := range AllHooks() {
		r.hooks[hook] = []string{}
	}

	return r, nil
}

// LoadPlugin loads a plugin from a file.
func (r *Registry) LoadPlugin(filePath string) (*Plugin, error) {
	log := logger.WithFields(r.log)

	// Read plugin file
	content, err := os.ReadFile(filePath)
	if err != nil {
		return nil, fmt.Errorf("failed to read plugin file: %w", err)
	}

	// Parse plugin metadata from Lua
	vm := r.vmPool.Get()
	defer r.vmPool.Put(vm)

	metadata, err := vm.ParsePluginMetadata(string(content))
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrPluginLoadFailed, err)
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	// Check if already loaded
	if _, exists := r.plugins[metadata.ID]; exists {
		return nil, ErrPluginAlreadyLoaded
	}

	plugin := &Plugin{
		ID:          metadata.ID,
		Name:        metadata.Name,
		Version:     metadata.Version,
		Author:      metadata.Author,
		Description: metadata.Description,
		FilePath:    filePath,
		Hooks:       convertHooks(metadata.Hooks),
		IsEnabled:   true,
		LoadedAt:    time.Now().UTC(),
	}

	// Register plugin
	r.plugins[plugin.ID] = plugin

	// Register hooks
	for _, hook := range plugin.Hooks {
		r.hooks[hook] = append(r.hooks[hook], plugin.ID)
	}

	log.Info().
		Str("plugin_id", plugin.ID).
		Str("name", plugin.Name).
		Str("version", plugin.Version).
		Msg("Plugin loaded")

	return plugin, nil
}

// LoadAllPlugins loads all plugins from the plugins directory.
func (r *Registry) LoadAllPlugins() error {
	log := logger.WithFields(r.log)

	// Create plugins directory if it doesn't exist
	if err := os.MkdirAll(r.pluginsDir, 0755); err != nil {
		return fmt.Errorf("failed to create plugins directory: %w", err)
	}

	// Find all .lua files
	matches, err := filepath.Glob(filepath.Join(r.pluginsDir, "*.lua"))
	if err != nil {
		return fmt.Errorf("failed to scan plugins directory: %w", err)
	}

	loaded := 0
	for _, path := range matches {
		if _, err := r.LoadPlugin(path); err != nil {
			log.Warn().Err(err).Str("path", path).Msg("Failed to load plugin")
			continue
		}
		loaded++
	}

	log.Info().Int("loaded", loaded).Int("total", len(matches)).Msg("Plugins loaded")
	return nil
}

// UnloadPlugin unloads a plugin.
func (r *Registry) UnloadPlugin(pluginID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	plugin, exists := r.plugins[pluginID]
	if !exists {
		return ErrPluginNotFound
	}

	// Remove from hooks
	for _, hook := range plugin.Hooks {
		r.removeFromHook(hook, pluginID)
	}

	// Remove plugin
	delete(r.plugins, pluginID)

	log := logger.WithFields(r.log)
	log.Info().Str("plugin_id", pluginID).Msg("Plugin unloaded")

	return nil
}

// removeFromHook removes a plugin from a hook list.
func (r *Registry) removeFromHook(hook HookType, pluginID string) {
	ids := r.hooks[hook]
	for i, id := range ids {
		if id == pluginID {
			r.hooks[hook] = append(ids[:i], ids[i+1:]...)
			return
		}
	}
}

// EnablePlugin enables a plugin.
func (r *Registry) EnablePlugin(pluginID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	plugin, exists := r.plugins[pluginID]
	if !exists {
		return ErrPluginNotFound
	}

	plugin.IsEnabled = true
	return nil
}

// DisablePlugin disables a plugin.
func (r *Registry) DisablePlugin(pluginID string) error {
	r.mu.Lock()
	defer r.mu.Unlock()

	plugin, exists := r.plugins[pluginID]
	if !exists {
		return ErrPluginNotFound
	}

	plugin.IsEnabled = false
	return nil
}

// GetPlugin returns a plugin by ID.
func (r *Registry) GetPlugin(pluginID string) (*Plugin, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	plugin, exists := r.plugins[pluginID]
	if !exists {
		return nil, ErrPluginNotFound
	}

	return plugin, nil
}

// ListPlugins returns all loaded plugins.
func (r *Registry) ListPlugins() []*Plugin {
	r.mu.RLock()
	defer r.mu.RUnlock()

	plugins := make([]*Plugin, 0, len(r.plugins))
	for _, p := range r.plugins {
		plugins = append(plugins, p)
	}
	return plugins
}

// ExecuteHook executes all plugins registered for a hook.
func (r *Registry) ExecuteHook(ctx context.Context, hookCtx *HookContext) (*HookResult, error) {
	r.mu.RLock()
	pluginIDs := r.hooks[hookCtx.HookType]
	r.mu.RUnlock()

	if len(pluginIDs) == 0 {
		return &HookResult{Modified: false}, nil
	}

	log := logger.WithFields(r.log)
	result := &HookResult{Modified: false}

	for _, pluginID := range pluginIDs {
		r.mu.RLock()
		plugin, exists := r.plugins[pluginID]
		r.mu.RUnlock()

		if !exists || !plugin.IsEnabled {
			continue
		}

		// Read plugin source
		content, err := os.ReadFile(plugin.FilePath)
		if err != nil {
			log.Error().Err(err).Str("plugin_id", pluginID).Msg("Failed to read plugin")
			continue
		}

		// Execute hook
		vm := r.vmPool.Get()
		hookResult, err := executeHook(ctx, vm, string(content), hookCtx)
		r.vmPool.Put(vm)

		if err != nil {
			log.Error().Err(err).Str("plugin_id", pluginID).Str("hook", string(hookCtx.HookType)).Msg("Plugin hook failed")
			r.mu.Lock()
			plugin.LastError = err.Error()
			r.mu.Unlock()
			continue
		}

		// Merge results
		if hookResult.Modified {
			result.Modified = true
			if result.Data == nil {
				result.Data = make(map[string]any)
			}
			for k, v := range hookResult.Data {
				result.Data[k] = v
			}
		}

		// Check for abort
		if hookResult.Abort {
			result.Abort = true
			result.Error = hookResult.Error
			return result, nil
		}
	}

	return result, nil
}

// GetHookPlugins returns plugins registered for a specific hook.
func (r *Registry) GetHookPlugins(hook HookType) []*Plugin {
	r.mu.RLock()
	defer r.mu.RUnlock()

	pluginIDs := r.hooks[hook]
	plugins := make([]*Plugin, 0, len(pluginIDs))
	for _, id := range pluginIDs {
		if p, exists := r.plugins[id]; exists {
			plugins = append(plugins, p)
		}
	}
	return plugins
}

// Close closes the registry and releases resources.
func (r *Registry) Close() {
	r.vmPool.Close()
}
