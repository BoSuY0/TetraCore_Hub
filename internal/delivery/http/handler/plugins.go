// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/plugins"
	"github.com/tetra/core-hub/pkg/logger"
)

// PluginsHandler handles plugin-related HTTP requests.
type PluginsHandler struct {
	registry *plugins.Registry
	log      logger.LogFields
}

// NewPluginsHandler creates a new PluginsHandler.
func NewPluginsHandler(registry *plugins.Registry) *PluginsHandler {
	return &PluginsHandler{
		registry: registry,
		log:      logger.LogFields{"component": "plugins-handler"},
	}
}

// GetPlugins returns all loaded plugins.
func (h *PluginsHandler) GetPlugins(c *fiber.Ctx) error {
	pluginsList := h.registry.ListPlugins()

	return c.JSON(fiber.Map{
		"plugins": pluginsList,
		"count":   len(pluginsList),
	})
}

// GetPlugin returns a single plugin by ID.
func (h *PluginsHandler) GetPlugin(c *fiber.Ctx) error {
	id := c.Params("id")

	plugin, err := h.registry.GetPlugin(id)
	if err != nil {
		if err == plugins.ErrPluginNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Plugin not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to get plugin",
		})
	}

	return c.JSON(plugin)
}

// LoadPluginRequest represents a request to load a plugin.
type LoadPluginRequest struct {
	FilePath string `json:"file_path" validate:"required"`
}

// LoadPlugin loads a plugin from a file.
func (h *PluginsHandler) LoadPlugin(c *fiber.Ctx) error {
	var req LoadPluginRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
		})
	}

	plugin, err := h.registry.LoadPlugin(req.FilePath)
	if err != nil {
		if err == plugins.ErrPluginAlreadyLoaded {
			return c.Status(fiber.StatusConflict).JSON(fiber.Map{
				"error":   true,
				"message": "Plugin already loaded",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": err.Error(),
		})
	}

	return c.Status(fiber.StatusCreated).JSON(plugin)
}

// UnloadPlugin unloads a plugin.
func (h *PluginsHandler) UnloadPlugin(c *fiber.Ctx) error {
	id := c.Params("id")

	if err := h.registry.UnloadPlugin(id); err != nil {
		if err == plugins.ErrPluginNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Plugin not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to unload plugin",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Plugin unloaded",
	})
}

// EnablePlugin enables a plugin.
func (h *PluginsHandler) EnablePlugin(c *fiber.Ctx) error {
	id := c.Params("id")

	if err := h.registry.EnablePlugin(id); err != nil {
		if err == plugins.ErrPluginNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Plugin not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to enable plugin",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Plugin enabled",
	})
}

// DisablePlugin disables a plugin.
func (h *PluginsHandler) DisablePlugin(c *fiber.Ctx) error {
	id := c.Params("id")

	if err := h.registry.DisablePlugin(id); err != nil {
		if err == plugins.ErrPluginNotFound {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"error":   true,
				"message": "Plugin not found",
			})
		}
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to disable plugin",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Plugin disabled",
	})
}

// ReloadPlugins reloads all plugins from the plugins directory.
func (h *PluginsHandler) ReloadPlugins(c *fiber.Ctx) error {
	if err := h.registry.LoadAllPlugins(); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to reload plugins",
		})
	}

	return c.JSON(fiber.Map{
		"success": true,
		"message": "Plugins reloaded",
		"plugins": h.registry.ListPlugins(),
	})
}

// GetHooks returns all available hooks.
func (h *PluginsHandler) GetHooks(c *fiber.Ctx) error {
	hooks := plugins.AllHooks()

	hookInfo := make([]map[string]any, len(hooks))
	for i, hook := range hooks {
		hookPlugins := h.registry.GetHookPlugins(hook)
		hookInfo[i] = map[string]any{
			"hook":    string(hook),
			"plugins": len(hookPlugins),
		}
	}

	return c.JSON(fiber.Map{
		"hooks": hookInfo,
		"count": len(hooks),
	})
}

// GetHookPlugins returns plugins registered for a specific hook.
func (h *PluginsHandler) GetHookPlugins(c *fiber.Ctx) error {
	hookType := plugins.HookType(c.Params("hook"))

	pluginsList := h.registry.GetHookPlugins(hookType)

	return c.JSON(fiber.Map{
		"hook":    string(hookType),
		"plugins": pluginsList,
		"count":   len(pluginsList),
	})
}
