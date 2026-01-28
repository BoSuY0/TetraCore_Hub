// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
)

// DLQHandler handles DLQ management endpoints.
type DLQHandler struct {
	dlqRepo repository.DLQRepository
}

// NewDLQHandler creates a new DLQ handler.
func NewDLQHandler(dlqRepo repository.DLQRepository) *DLQHandler {
	return &DLQHandler{
		dlqRepo: dlqRepo,
	}
}

// DLQEntryResponse represents a DLQ entry in API responses.
type DLQEntryResponse struct {
	ID            string `json:"id"`
	TaskID        string `json:"task_id"`
	TaskType      string `json:"task_type"`
	Priority      string `json:"priority"`
	ExecutorType  string `json:"executor_type"`
	Reason        string `json:"reason"`
	ErrorMessage  string `json:"error_message"`
	ErrorTrace    string `json:"error_trace,omitempty"`
	RetryCount    int    `json:"retry_count"`
	MaxRetries    int    `json:"max_retries"`
	LastWorkerID  string `json:"last_worker_id,omitempty"`
	ClientID      string `json:"client_id,omitempty"`
	CreatedAt     string `json:"created_at"`
	FailedAt      string `json:"failed_at"`
	ExpiresAt     string `json:"expires_at,omitempty"`
	IsExpired     bool   `json:"is_expired"`
	IsRetryable   bool   `json:"is_retryable"`
}

// dlqEntryToResponse converts a DLQ entry to API response.
func dlqEntryToResponse(e *entity.DLQEntry) *DLQEntryResponse {
	resp := &DLQEntryResponse{
		ID:           e.ID,
		TaskID:       e.TaskID,
		TaskType:     string(e.TaskType),
		Priority:     string(e.Priority),
		ExecutorType: string(e.ExecutorType),
		Reason:       string(e.Reason),
		ErrorMessage: e.ErrorMessage,
		ErrorTrace:   e.ErrorTrace,
		RetryCount:   e.RetryCount,
		MaxRetries:   e.MaxRetries,
		LastWorkerID: e.LastWorkerID,
		ClientID:     e.ClientID,
		CreatedAt:    e.CreatedAt.Format(time.RFC3339),
		FailedAt:     e.FailedAt.Format(time.RFC3339),
		IsExpired:    e.IsExpired(),
	}

	if e.ExpiresAt != nil {
		resp.ExpiresAt = e.ExpiresAt.Format(time.RFC3339)
	}

	// Check if retryable
	resp.IsRetryable = !e.IsExpired() &&
		e.Reason != entity.DLQReasonFatalError &&
		e.Reason != entity.DLQReasonInvalidData

	return resp
}

// GetDLQEntries handles GET /api/v1/dlq
func (h *DLQHandler) GetDLQEntries(c *fiber.Ctx) error {
	limitStr := c.Query("limit", "100")
	offsetStr := c.Query("offset", "0")
	reason := c.Query("reason")
	taskType := c.Query("task_type")

	limit, _ := strconv.Atoi(limitStr)
	offset, _ := strconv.Atoi(offsetStr)

	var entries []*entity.DLQEntry
	var err error

	if reason != "" {
		entries, err = h.dlqRepo.GetByReason(c.Context(), entity.DLQReason(reason), limit)
	} else if taskType != "" {
		entries, err = h.dlqRepo.GetByTaskType(c.Context(), entity.TaskType(taskType), limit)
	} else {
		entries, err = h.dlqRepo.GetAll(c.Context(), limit, offset)
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve DLQ entries",
			"code":    "INTERNAL_ERROR",
		})
	}

	response := make([]*DLQEntryResponse, len(entries))
	for i, entry := range entries {
		response[i] = dlqEntryToResponse(entry)
	}

	return c.JSON(fiber.Map{
		"entries": response,
		"total":   len(response),
	})
}

// GetDLQEntry handles GET /api/v1/dlq/:id
func (h *DLQHandler) GetDLQEntry(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry ID is required",
			"code":    "MISSING_ID",
		})
	}

	entry, err := h.dlqRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry not found",
			"code":    "NOT_FOUND",
		})
	}

	return c.JSON(dlqEntryToResponse(entry))
}

// RetryDLQEntry handles POST /api/v1/dlq/:id/retry
func (h *DLQHandler) RetryDLQEntry(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry ID is required",
			"code":    "MISSING_ID",
		})
	}

	entry, err := h.dlqRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry not found",
			"code":    "NOT_FOUND",
		})
	}

	// Check if retryable
	if entry.IsExpired() {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry has expired",
			"code":    "ENTRY_EXPIRED",
		})
	}

	if entry.Reason == entity.DLQReasonFatalError || entry.Reason == entity.DLQReasonInvalidData {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "This entry cannot be retried",
			"code":    "NOT_RETRYABLE",
		})
	}

	// Convert DLQ entry back to task
	task := entry.ToTask()

	// Delete DLQ entry
	if err := h.dlqRepo.Delete(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to process retry",
			"code":    "RETRY_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"task_id":      task.TaskID,
		"dlq_entry_id": id,
		"message":      "Task retry scheduled",
	})
}

// ScheduleRetryDLQEntry handles POST /api/v1/dlq/:id/schedule
func (h *DLQHandler) ScheduleRetryDLQEntry(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry ID is required",
			"code":    "MISSING_ID",
		})
	}

	delayStr := c.Query("delay", "60") // Default 60 seconds
	delay, _ := strconv.Atoi(delayStr)

	entry, err := h.dlqRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry not found",
			"code":    "NOT_FOUND",
		})
	}

	// Set expiration to allow scheduled retry
	entry.SetExpiration(delay + 3600) // Extend expiration

	return c.JSON(fiber.Map{
		"dlq_entry_id":  id,
		"scheduled_for": time.Now().Add(time.Duration(delay) * time.Second).Format(time.RFC3339),
		"message":       "Retry scheduled",
	})
}

// DeleteDLQEntry handles DELETE /api/v1/dlq/:id
func (h *DLQHandler) DeleteDLQEntry(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "DLQ entry ID is required",
			"code":    "MISSING_ID",
		})
	}

	if err := h.dlqRepo.Delete(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete DLQ entry",
			"code":    "DELETE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"dlq_entry_id": id,
		"message":      "DLQ entry deleted successfully",
	})
}

// RetryAllDLQEntries handles POST /api/v1/dlq/retry-all
func (h *DLQHandler) RetryAllDLQEntries(c *fiber.Ctx) error {
	entries, err := h.dlqRepo.GetAll(c.Context(), 0, 0)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve DLQ entries",
			"code":    "INTERNAL_ERROR",
		})
	}

	var retried, skipped int
	for _, entry := range entries {
		if entry.IsExpired() || entry.Reason == entity.DLQReasonFatalError || entry.Reason == entity.DLQReasonInvalidData {
			skipped++
			continue
		}

		if err := h.dlqRepo.Delete(c.Context(), entry.ID); err == nil {
			retried++
		} else {
			skipped++
		}
	}

	return c.JSON(fiber.Map{
		"retried": retried,
		"skipped": skipped,
		"total":   len(entries),
		"message": "Bulk retry completed",
	})
}

// PurgeDLQ handles DELETE /api/v1/dlq/purge
func (h *DLQHandler) PurgeDLQ(c *fiber.Ctx) error {
	expiredOnly := c.Query("expired_only") == "true"

	var deleted int64
	var err error

	if expiredOnly {
		entries, _ := h.dlqRepo.GetExpired(c.Context(), 0)
		for _, entry := range entries {
			if err := h.dlqRepo.Delete(c.Context(), entry.ID); err == nil {
				deleted++
			}
		}
	} else {
		deleted, err = h.dlqRepo.Purge(c.Context())
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to purge DLQ",
			"code":    "PURGE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"deleted": deleted,
		"message": "DLQ purged successfully",
	})
}

// GetDLQStats handles GET /api/v1/dlq/stats
func (h *DLQHandler) GetDLQStats(c *fiber.Ctx) error {
	stats, err := h.dlqRepo.GetStats(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve DLQ statistics",
			"code":    "INTERNAL_ERROR",
		})
	}

	return c.JSON(stats)
}
