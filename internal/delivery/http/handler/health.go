// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"runtime"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/infrastructure/redis"
)

// StatsProvider provides hub statistics.
type StatsProvider interface {
	GetHubStats(ctx context.Context) (*HubStats, error)
}

// HubStats represents hub statistics.
type HubStats struct {
	Clients      any           `json:"clients"`
	Tasks        any           `json:"tasks"`
	Sessions     int64         `json:"sessions"`
	Connections  int64         `json:"connections"`
	MessageCount int64         `json:"message_count"`
	Uptime       time.Duration `json:"uptime"`
}

// HealthHandler handles health check endpoints.
type HealthHandler struct {
	startTime     time.Time
	redisClient   *redis.Client
	statsProvider StatsProvider
}

// NewHealthHandler creates a new health handler.
func NewHealthHandler(redisClient *redis.Client, statsProvider StatsProvider) *HealthHandler {
	return &HealthHandler{
		startTime:     time.Now(),
		redisClient:   redisClient,
		statsProvider: statsProvider,
	}
}

// HealthResponse represents the health check response.
type HealthResponse struct {
	Status      string            `json:"status"`
	Uptime      string            `json:"uptime"`
	Timestamp   string            `json:"timestamp"`
	Checks      map[string]string `json:"checks,omitempty"`
	System      *SystemInfo       `json:"system,omitempty"`
}

// SystemInfo represents system information.
type SystemInfo struct {
	GoVersion    string `json:"go_version"`
	NumGoroutine int    `json:"num_goroutine"`
	NumCPU       int    `json:"num_cpu"`
	MemAlloc     uint64 `json:"mem_alloc_mb"`
	MemTotal     uint64 `json:"mem_total_mb"`
}

// HealthCheck handles the /health endpoint.
func (h *HealthHandler) HealthCheck(c *fiber.Ctx) error {
	status := "healthy"
	checks := make(map[string]string)

	// Redis check
	if h.redisClient != nil {
		if err := h.redisClient.Ping(c.Context()); err == nil {
			checks["redis"] = "healthy"
		} else {
			checks["redis"] = "unhealthy"
			status = "degraded"
		}
	}

	// Get system info
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	response := HealthResponse{
		Status:    status,
		Uptime:    time.Since(h.startTime).String(),
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Checks:    checks,
		System: &SystemInfo{
			GoVersion:    runtime.Version(),
			NumGoroutine: runtime.NumGoroutine(),
			NumCPU:       runtime.NumCPU(),
			MemAlloc:     memStats.Alloc / 1024 / 1024,
			MemTotal:     memStats.TotalAlloc / 1024 / 1024,
		},
	}

	statusCode := fiber.StatusOK
	if status != "healthy" {
		statusCode = fiber.StatusServiceUnavailable
	}

	return c.Status(statusCode).JSON(response)
}

// ReadyCheck handles the /ready endpoint.
// Returns 200 if the service is ready to receive traffic.
func (h *HealthHandler) ReadyCheck(c *fiber.Ctx) error {
	// Check critical dependencies
	if h.redisClient != nil {
		if err := h.redisClient.Ping(c.Context()); err != nil {
			return c.Status(fiber.StatusServiceUnavailable).JSON(fiber.Map{
				"status":  "not_ready",
				"message": "Redis not available",
			})
		}
	}

	return c.JSON(fiber.Map{
		"status": "ready",
	})
}

// LiveCheck handles the /live endpoint.
// Returns 200 if the service is alive (basic liveness check).
func (h *HealthHandler) LiveCheck(c *fiber.Ctx) error {
	return c.JSON(fiber.Map{
		"status": "alive",
	})
}

// Stats handles the /stats endpoint.
func (h *HealthHandler) Stats(c *fiber.Ctx) error {
	// Get system info
	var memStats runtime.MemStats
	runtime.ReadMemStats(&memStats)

	response := StatsResponse{
		Uptime: time.Since(h.startTime).Seconds(),
		Memory: MemoryMetrics{
			Alloc:      memStats.Alloc / 1024 / 1024,
			TotalAlloc: memStats.TotalAlloc / 1024 / 1024,
			Sys:        memStats.Sys / 1024 / 1024,
			NumGC:      memStats.NumGC,
		},
		Runtime: RuntimeMetrics{
			GoVersion:    runtime.Version(),
			NumGoroutine: runtime.NumGoroutine(),
			NumCPU:       runtime.NumCPU(),
		},
	}

	// Get hub stats if available
	if h.statsProvider != nil {
		hubStats, err := h.statsProvider.GetHubStats(c.Context())
		if err == nil && hubStats != nil {
			response.Hub = hubStats
		}
	}

	return c.JSON(response)
}

// StatsResponse represents the stats endpoint response.
type StatsResponse struct {
	Uptime  float64         `json:"uptime_seconds"`
	Memory  MemoryMetrics   `json:"memory"`
	Runtime RuntimeMetrics  `json:"runtime"`
	Hub     *HubStats       `json:"hub,omitempty"`
}

// MemoryMetrics represents memory metrics.
type MemoryMetrics struct {
	Alloc      uint64 `json:"alloc_mb"`
	TotalAlloc uint64 `json:"total_alloc_mb"`
	Sys        uint64 `json:"sys_mb"`
	NumGC      uint32 `json:"num_gc"`
}

// RuntimeMetrics represents runtime metrics.
type RuntimeMetrics struct {
	GoVersion    string `json:"go_version"`
	NumGoroutine int    `json:"num_goroutine"`
	NumCPU       int    `json:"num_cpu"`
}
