// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"context"
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
)

// TaskSubmitInput represents input for submitting a task.
type TaskSubmitInput struct {
	TaskType       entity.TaskType
	ExecutorType   entity.ExecutorType
	Priority       entity.TaskPriority
	Payload        map[string]any
	ClientID       string
	Timeout        time.Duration
	IdempotencyKey string
}

// TaskStatsResponse represents task statistics response.
type TaskStatsResponse struct {
	TotalTasks        int64            `json:"total_tasks"`
	PendingTasks      int64            `json:"pending_tasks"`
	ProcessingTasks   int64            `json:"processing_tasks"`
	CompletedTasks    int64            `json:"completed_tasks"`
	FailedTasks       int64            `json:"failed_tasks"`
	TasksByType       map[string]int64 `json:"tasks_by_type"`
	AvgProcessingTime float64          `json:"avg_processing_time_ms"`
}

// TaskService provides task management operations.
type TaskService interface {
	SubmitTask(ctx context.Context, input TaskSubmitInput) (*entity.Task, error)
	GetTask(ctx context.Context, taskID string) (*entity.Task, error)
	GetAllTasks(ctx context.Context, limit, offset int) ([]*entity.Task, error)
	GetTasksByStatus(ctx context.Context, status entity.TaskStatus, limit int) ([]*entity.Task, error)
	GetTasksByType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.Task, error)
	CancelTask(ctx context.Context, taskID string, reason string) error
	RetryTask(ctx context.Context, taskID string) error
	DeleteTask(ctx context.Context, taskID string) error
	GetStats(ctx context.Context) (*TaskStatsResponse, error)
}

// TaskHandler handles task management endpoints.
type TaskHandler struct {
	taskService TaskService
}

// NewTaskHandler creates a new task handler.
func NewTaskHandler(taskService TaskService) *TaskHandler {
	return &TaskHandler{
		taskService: taskService,
	}
}

// TaskResponse represents a task in API responses.
type TaskResponse struct {
	TaskID        string         `json:"task_id"`
	TaskType      string         `json:"task_type"`
	Status        string         `json:"status"`
	Priority      string         `json:"priority"`
	ExecutorType  string         `json:"executor_type"`
	WorkerID      string         `json:"worker_id,omitempty"`
	ClientID      string         `json:"client_id,omitempty"`
	CreatedAt     string         `json:"created_at"`
	StartedAt     string         `json:"started_at,omitempty"`
	CompletedAt   string         `json:"completed_at,omitempty"`
	ExecutionTime *float64       `json:"execution_time_ms,omitempty"`
	Timeout       int            `json:"timeout"`
	MaxRetries    int            `json:"max_retries"`
	Attempt       int            `json:"attempt"`
	CanRetry      bool           `json:"can_retry"`
	IsExpired     bool           `json:"is_expired"`
	Data          map[string]any `json:"data,omitempty"`
	Result        map[string]any `json:"result,omitempty"`
}

// SubmitTaskRequest represents a task submission request.
type SubmitTaskRequest struct {
	TaskType           string         `json:"task_type"`
	Data               map[string]any `json:"data"`
	Priority           string         `json:"priority,omitempty"`
	ExecutorType       string         `json:"executor_type,omitempty"`
	Timeout            int            `json:"timeout,omitempty"`
	MaxRetries         int            `json:"max_retries,omitempty"`
	WorkerRequirements []string       `json:"worker_requirements,omitempty"`
	IdempotencyKey     string         `json:"idempotency_key,omitempty"`
}

// taskToResponse converts a task entity to API response.
func taskToResponse(t *entity.Task) *TaskResponse {
	resp := &TaskResponse{
		TaskID:       t.TaskID,
		TaskType:     string(t.TaskType),
		Status:       string(t.Context.CurrentStatus),
		Priority:     string(t.Priority),
		ExecutorType: string(t.ExecutorType),
		WorkerID:     t.Context.WorkerID,
		ClientID:     t.Context.ClientID,
		CreatedAt:    t.Context.CreatedAt.Format("2006-01-02T15:04:05Z"),
		Timeout:      t.Timeout,
		MaxRetries:   t.MaxRetries,
		Attempt:      t.Context.CurrentAttempt,
		CanRetry:     t.CanRetry(),
		IsExpired:    t.Context.IsExpired(),
		Data:         t.Data,
		Result:       t.Context.Result,
	}

	if t.Context.StartedAt != nil {
		resp.StartedAt = t.Context.StartedAt.Format("2006-01-02T15:04:05Z")
	}

	if t.Context.CompletedAt != nil {
		resp.CompletedAt = t.Context.CompletedAt.Format("2006-01-02T15:04:05Z")
	}

	resp.ExecutionTime = t.Context.GetExecutionTime()

	return resp
}

// GetTasks handles GET /api/v1/tasks
func (h *TaskHandler) GetTasks(c *fiber.Ctx) error {
	// Parse query parameters
	status := c.Query("status")
	taskType := c.Query("type")
	limitStr := c.Query("limit", "100")
	offsetStr := c.Query("offset", "0")

	limit, _ := strconv.Atoi(limitStr)
	offset, _ := strconv.Atoi(offsetStr)

	var tasks []*entity.Task
	var err error

	if status != "" {
		tasks, err = h.taskService.GetTasksByStatus(c.Context(), entity.TaskStatus(status), limit)
	} else if taskType != "" {
		tasks, err = h.taskService.GetTasksByType(c.Context(), entity.TaskType(taskType), limit)
	} else {
		tasks, err = h.taskService.GetAllTasks(c.Context(), limit, offset)
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve tasks",
			"code":    "INTERNAL_ERROR",
		})
	}

	// Convert to response format
	response := make([]*TaskResponse, len(tasks))
	for i, task := range tasks {
		response[i] = taskToResponse(task)
	}

	return c.JSON(fiber.Map{
		"tasks": response,
		"total": len(response),
	})
}

// GetTask handles GET /api/v1/tasks/:id
func (h *TaskHandler) GetTask(c *fiber.Ctx) error {
	taskID := c.Params("id")
	if taskID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task ID is required",
			"code":    "MISSING_TASK_ID",
		})
	}

	task, err := h.taskService.GetTask(c.Context(), taskID)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Task not found",
			"code":    "TASK_NOT_FOUND",
		})
	}

	return c.JSON(taskToResponse(task))
}

// SubmitTask handles POST /api/v1/tasks
func (h *TaskHandler) SubmitTask(c *fiber.Ctx) error {
	var req SubmitTaskRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	if req.TaskType == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task type is required",
			"code":    "MISSING_TASK_TYPE",
		})
	}

	if req.Data == nil {
		req.Data = make(map[string]any)
	}

	input := TaskSubmitInput{
		TaskType:       entity.TaskType(req.TaskType),
		Payload:        req.Data,
		IdempotencyKey: req.IdempotencyKey,
	}

	if req.Priority != "" {
		input.Priority = entity.TaskPriority(req.Priority)
	}

	if req.ExecutorType != "" {
		input.ExecutorType = entity.ExecutorType(req.ExecutorType)
	}

	if req.Timeout > 0 {
		input.Timeout = time.Duration(req.Timeout) * time.Second
	}

	task, err := h.taskService.SubmitTask(c.Context(), input)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to submit task",
			"code":    "SUBMIT_FAILED",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"task_id": task.TaskID,
		"status":  string(task.Context.CurrentStatus),
		"message": "Task submitted successfully",
	})
}

// CancelTask handles POST /api/v1/tasks/:id/cancel
func (h *TaskHandler) CancelTask(c *fiber.Ctx) error {
	taskID := c.Params("id")
	if taskID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task ID is required",
			"code":    "MISSING_TASK_ID",
		})
	}

	reason := c.Query("reason", "Cancelled via API")

	if err := h.taskService.CancelTask(c.Context(), taskID, reason); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to cancel task",
			"code":    "CANCEL_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"task_id": taskID,
		"message": "Task cancelled successfully",
	})
}

// RetryTask handles POST /api/v1/tasks/:id/retry
func (h *TaskHandler) RetryTask(c *fiber.Ctx) error {
	taskID := c.Params("id")
	if taskID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task ID is required",
			"code":    "MISSING_TASK_ID",
		})
	}

	if err := h.taskService.RetryTask(c.Context(), taskID); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retry task",
			"code":    "RETRY_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"task_id": taskID,
		"message": "Task retry scheduled",
	})
}

// DeleteTask handles DELETE /api/v1/tasks/:id
func (h *TaskHandler) DeleteTask(c *fiber.Ctx) error {
	taskID := c.Params("id")
	if taskID == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task ID is required",
			"code":    "MISSING_TASK_ID",
		})
	}

	if err := h.taskService.DeleteTask(c.Context(), taskID); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete task",
			"code":    "DELETE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"task_id": taskID,
		"message": "Task deleted successfully",
	})
}

// GetTaskStats handles GET /api/v1/tasks/stats
func (h *TaskHandler) GetTaskStats(c *fiber.Ctx) error {
	stats, err := h.taskService.GetStats(c.Context())
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve task statistics",
			"code":    "INTERNAL_ERROR",
		})
	}

	return c.JSON(stats)
}
