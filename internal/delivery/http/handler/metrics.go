// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"fmt"
	"runtime"
	"sync/atomic"
	"time"

	"github.com/gofiber/fiber/v2"
)

// MetricsCollector collects application metrics.
type MetricsCollector struct {
	startTime       time.Time
	requestCount    atomic.Int64
	errorCount      atomic.Int64
	wsConnections   atomic.Int64
	activeRequests  atomic.Int64
	totalLatencyMs  atomic.Int64
}

// NewMetricsCollector creates a new metrics collector.
func NewMetricsCollector() *MetricsCollector {
	return &MetricsCollector{
		startTime: time.Now(),
	}
}

// IncrementRequests increments request counter.
func (m *MetricsCollector) IncrementRequests() {
	m.requestCount.Add(1)
}

// IncrementErrors increments error counter.
func (m *MetricsCollector) IncrementErrors() {
	m.errorCount.Add(1)
}

// SetWSConnections sets WebSocket connection count.
func (m *MetricsCollector) SetWSConnections(count int64) {
	m.wsConnections.Store(count)
}

// AddLatency adds request latency in milliseconds.
func (m *MetricsCollector) AddLatency(ms int64) {
	m.totalLatencyMs.Add(ms)
}

// IncrementActiveRequests increments active request counter.
func (m *MetricsCollector) IncrementActiveRequests() {
	m.activeRequests.Add(1)
}

// DecrementActiveRequests decrements active request counter.
func (m *MetricsCollector) DecrementActiveRequests() {
	m.activeRequests.Add(-1)
}

// MetricsHandler handles Prometheus metrics endpoint.
type MetricsHandler struct {
	collector *MetricsCollector
}

// NewMetricsHandler creates a new metrics handler.
func NewMetricsHandler(collector *MetricsCollector) *MetricsHandler {
	return &MetricsHandler{collector: collector}
}

// PrometheusMetrics returns metrics in Prometheus format.
// @Summary Get Prometheus metrics
// @Description Returns application metrics in Prometheus text format
// @Tags metrics
// @Produce text/plain
// @Success 200 {string} string "Prometheus metrics"
// @Router /metrics [get]
func (h *MetricsHandler) PrometheusMetrics(c *fiber.Ctx) error {
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)

	uptime := time.Since(h.collector.startTime).Seconds()
	requestCount := h.collector.requestCount.Load()
	errorCount := h.collector.errorCount.Load()
	wsConnections := h.collector.wsConnections.Load()
	activeRequests := h.collector.activeRequests.Load()
	totalLatency := h.collector.totalLatencyMs.Load()

	avgLatency := float64(0)
	if requestCount > 0 {
		avgLatency = float64(totalLatency) / float64(requestCount)
	}

	c.Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")

	return c.SendString(formatPrometheusMetrics(
		uptime,
		requestCount,
		errorCount,
		wsConnections,
		activeRequests,
		avgLatency,
		&mem,
	))
}

func formatPrometheusMetrics(
	uptime float64,
	requestCount, errorCount, wsConnections, activeRequests int64,
	avgLatency float64,
	mem *runtime.MemStats,
) string {
	return `# HELP tetracore_uptime_seconds Time since server start in seconds
# TYPE tetracore_uptime_seconds gauge
tetracore_uptime_seconds ` + formatFloat(uptime) + `

# HELP tetracore_http_requests_total Total number of HTTP requests
# TYPE tetracore_http_requests_total counter
tetracore_http_requests_total ` + formatInt(requestCount) + `

# HELP tetracore_http_errors_total Total number of HTTP errors
# TYPE tetracore_http_errors_total counter
tetracore_http_errors_total ` + formatInt(errorCount) + `

# HELP tetracore_http_requests_active Current number of active HTTP requests
# TYPE tetracore_http_requests_active gauge
tetracore_http_requests_active ` + formatInt(activeRequests) + `

# HELP tetracore_http_request_latency_avg_ms Average request latency in milliseconds
# TYPE tetracore_http_request_latency_avg_ms gauge
tetracore_http_request_latency_avg_ms ` + formatFloat(avgLatency) + `

# HELP tetracore_websocket_connections Current number of WebSocket connections
# TYPE tetracore_websocket_connections gauge
tetracore_websocket_connections ` + formatInt(wsConnections) + `

# HELP tetracore_go_goroutines Current number of goroutines
# TYPE tetracore_go_goroutines gauge
tetracore_go_goroutines ` + formatInt(int64(runtime.NumGoroutine())) + `

# HELP tetracore_go_threads Current number of OS threads
# TYPE tetracore_go_threads gauge
tetracore_go_threads ` + formatInt(int64(runtime.GOMAXPROCS(0))) + `

# HELP tetracore_memory_alloc_bytes Current memory allocation in bytes
# TYPE tetracore_memory_alloc_bytes gauge
tetracore_memory_alloc_bytes ` + formatUint(mem.Alloc) + `

# HELP tetracore_memory_total_alloc_bytes Total memory allocated in bytes
# TYPE tetracore_memory_total_alloc_bytes counter
tetracore_memory_total_alloc_bytes ` + formatUint(mem.TotalAlloc) + `

# HELP tetracore_memory_sys_bytes Memory obtained from system in bytes
# TYPE tetracore_memory_sys_bytes gauge
tetracore_memory_sys_bytes ` + formatUint(mem.Sys) + `

# HELP tetracore_memory_heap_alloc_bytes Heap memory allocation in bytes
# TYPE tetracore_memory_heap_alloc_bytes gauge
tetracore_memory_heap_alloc_bytes ` + formatUint(mem.HeapAlloc) + `

# HELP tetracore_memory_heap_objects Number of allocated heap objects
# TYPE tetracore_memory_heap_objects gauge
tetracore_memory_heap_objects ` + formatUint(mem.HeapObjects) + `

# HELP tetracore_gc_runs_total Total number of GC runs
# TYPE tetracore_gc_runs_total counter
tetracore_gc_runs_total ` + formatUint(uint64(mem.NumGC)) + `

# HELP tetracore_gc_pause_total_ns Total GC pause time in nanoseconds
# TYPE tetracore_gc_pause_total_ns counter
tetracore_gc_pause_total_ns ` + formatUint(mem.PauseTotalNs) + `
`
}

func formatFloat(f float64) string {
	return fmt.Sprintf("%.6f", f)
}

func formatInt(i int64) string {
	return fmt.Sprintf("%d", i)
}

func formatUint(u uint64) string {
	return fmt.Sprintf("%d", u)
}
