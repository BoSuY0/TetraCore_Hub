// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
)

// ScheduleHandler handles schedule management endpoints.
type ScheduleHandler struct {
	scheduleRepo repository.ScheduleRepository
}

// NewScheduleHandler creates a new schedule handler.
func NewScheduleHandler(scheduleRepo repository.ScheduleRepository) *ScheduleHandler {
	return &ScheduleHandler{
		scheduleRepo: scheduleRepo,
	}
}

// ScheduleResponse represents a schedule in API responses.
type ScheduleResponse struct {
	ID             string `json:"id"`
	Name           string `json:"name"`
	Description    string `json:"description,omitempty"`
	TaskType       string `json:"task_type"`
	Priority       string `json:"priority"`
	ExecutorType   string `json:"executor_type"`
	Timeout        int    `json:"timeout"`
	MaxRetries     int    `json:"max_retries"`
	Frequency      string `json:"frequency"`
	CronExpression string `json:"cron_expression,omitempty"`
	Interval       int    `json:"interval,omitempty"`
	Status         string `json:"status"`
	CreatedBy      string `json:"created_by"`
	CreatedAt      string `json:"created_at"`
	UpdatedAt      string `json:"updated_at"`
	NextRunAt      string `json:"next_run_at,omitempty"`
	LastRunAt      string `json:"last_run_at,omitempty"`
	LastRunStatus  string `json:"last_run_status,omitempty"`
	LastRunTaskID  string `json:"last_run_task_id,omitempty"`
	RunCount       int    `json:"run_count"`
	SuccessCount   int    `json:"success_count"`
	FailureCount   int    `json:"failure_count"`
	MaxRuns        int    `json:"max_runs,omitempty"`
	ExpiresAt      string `json:"expires_at,omitempty"`
	IsActive       bool   `json:"is_active"`
	Tags           []string `json:"tags"`
}

// CreateScheduleRequest represents a schedule creation request.
type CreateScheduleRequest struct {
	Name           string         `json:"name"`
	Description    string         `json:"description,omitempty"`
	TaskType       string         `json:"task_type"`
	TaskData       map[string]any `json:"task_data"`
	Priority       string         `json:"priority,omitempty"`
	ExecutorType   string         `json:"executor_type,omitempty"`
	Timeout        int            `json:"timeout,omitempty"`
	MaxRetries     int            `json:"max_retries,omitempty"`
	Frequency      string         `json:"frequency"`
	CronExpression string         `json:"cron_expression,omitempty"`
	Interval       int            `json:"interval,omitempty"`
	MaxRuns        int            `json:"max_runs,omitempty"`
	ExpiresIn      int            `json:"expires_in_hours,omitempty"`
	Tags           []string       `json:"tags,omitempty"`
}

// scheduleToResponse converts a schedule to API response.
func scheduleToResponse(s *entity.Schedule) *ScheduleResponse {
	resp := &ScheduleResponse{
		ID:           s.ID,
		Name:         s.Name,
		Description:  s.Description,
		TaskType:     string(s.TaskType),
		Priority:     string(s.Priority),
		ExecutorType: string(s.ExecutorType),
		Timeout:      s.Timeout,
		MaxRetries:   s.MaxRetries,
		Frequency:    string(s.Frequency),
		CronExpression: s.CronExpression,
		Interval:    s.Interval,
		Status:      string(s.Status),
		CreatedBy:   s.CreatedBy,
		CreatedAt:   s.CreatedAt.Format(time.RFC3339),
		UpdatedAt:   s.UpdatedAt.Format(time.RFC3339),
		RunCount:    s.RunCount,
		SuccessCount: s.SuccessCount,
		FailureCount: s.FailureCount,
		MaxRuns:     s.MaxRuns,
		IsActive:    s.IsActive(),
		Tags:        s.Tags,
	}

	if s.NextRunAt != nil {
		resp.NextRunAt = s.NextRunAt.Format(time.RFC3339)
	}

	if s.LastRunAt != nil {
		resp.LastRunAt = s.LastRunAt.Format(time.RFC3339)
	}

	if s.LastRunStatus != nil {
		resp.LastRunStatus = string(*s.LastRunStatus)
	}

	resp.LastRunTaskID = s.LastRunTaskID

	if s.ExpiresAt != nil {
		resp.ExpiresAt = s.ExpiresAt.Format(time.RFC3339)
	}

	return resp
}

// GetSchedules handles GET /api/v1/schedules
func (h *ScheduleHandler) GetSchedules(c *fiber.Ctx) error {
	limitStr := c.Query("limit", "100")
	offsetStr := c.Query("offset", "0")
	status := c.Query("status")
	taskType := c.Query("task_type")
	activeOnly := c.Query("active") == "true"

	limit, _ := strconv.Atoi(limitStr)
	offset, _ := strconv.Atoi(offsetStr)

	var schedules []*entity.Schedule
	var err error

	if activeOnly {
		schedules, err = h.scheduleRepo.GetActive(c.Context())
	} else if status != "" {
		schedules, err = h.scheduleRepo.GetByStatus(c.Context(), entity.ScheduleStatus(status), limit)
	} else if taskType != "" {
		schedules, err = h.scheduleRepo.GetByTaskType(c.Context(), entity.TaskType(taskType), limit)
	} else {
		schedules, err = h.scheduleRepo.GetAll(c.Context(), limit, offset)
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve schedules",
			"code":    "INTERNAL_ERROR",
		})
	}

	response := make([]*ScheduleResponse, len(schedules))
	for i, s := range schedules {
		response[i] = scheduleToResponse(s)
	}

	return c.JSON(fiber.Map{
		"schedules": response,
		"total":     len(response),
	})
}

// GetSchedule handles GET /api/v1/schedules/:id
func (h *ScheduleHandler) GetSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	schedule, err := h.scheduleRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule not found",
			"code":    "NOT_FOUND",
		})
	}

	return c.JSON(scheduleToResponse(schedule))
}

// CreateSchedule handles POST /api/v1/schedules
func (h *ScheduleHandler) CreateSchedule(c *fiber.Ctx) error {
	var req CreateScheduleRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	if req.Name == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule name is required",
			"code":    "MISSING_NAME",
		})
	}

	if req.TaskType == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Task type is required",
			"code":    "MISSING_TASK_TYPE",
		})
	}

	if req.Frequency == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Frequency is required",
			"code":    "MISSING_FREQUENCY",
		})
	}

	// Check if name already exists
	exists, _ := h.scheduleRepo.ExistsByName(c.Context(), req.Name)
	if exists {
		return c.Status(fiber.StatusConflict).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule with this name already exists",
			"code":    "NAME_EXISTS",
		})
	}

	// Get creator from context
	createdBy := "system"
	if userID := c.Locals("user_id"); userID != nil {
		createdBy = userID.(string)
	}

	if req.TaskData == nil {
		req.TaskData = make(map[string]any)
	}

	schedule := entity.NewSchedule(req.Name, entity.TaskType(req.TaskType), req.TaskData, createdBy)
	schedule.Description = req.Description
	schedule.Frequency = entity.ScheduleFrequency(req.Frequency)
	schedule.CronExpression = req.CronExpression
	schedule.Interval = req.Interval
	schedule.MaxRuns = req.MaxRuns

	if req.Priority != "" {
		schedule.Priority = entity.TaskPriority(req.Priority)
	}

	if req.ExecutorType != "" {
		schedule.ExecutorType = entity.ExecutorType(req.ExecutorType)
	}

	if req.Timeout > 0 {
		schedule.Timeout = req.Timeout
	}

	if req.MaxRetries > 0 {
		schedule.MaxRetries = req.MaxRetries
	}

	if len(req.Tags) > 0 {
		schedule.Tags = req.Tags
	}

	if req.ExpiresIn > 0 {
		expiresAt := time.Now().UTC().Add(time.Duration(req.ExpiresIn) * time.Hour)
		schedule.ExpiresAt = &expiresAt
	}

	// Calculate first run time
	schedule.CalculateNextRun()

	if err := h.scheduleRepo.Save(c.Context(), schedule); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create schedule",
			"code":    "CREATE_FAILED",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(scheduleToResponse(schedule))
}

// UpdateSchedule handles PUT /api/v1/schedules/:id
func (h *ScheduleHandler) UpdateSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	schedule, err := h.scheduleRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule not found",
			"code":    "NOT_FOUND",
		})
	}

	var req CreateScheduleRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	// Update fields
	if req.Name != "" && req.Name != schedule.Name {
		exists, _ := h.scheduleRepo.ExistsByName(c.Context(), req.Name)
		if exists {
			return c.Status(fiber.StatusConflict).JSON(fiber.Map{
				"error":   true,
				"message": "Schedule with this name already exists",
				"code":    "NAME_EXISTS",
			})
		}
		schedule.Name = req.Name
	}

	if req.Description != "" {
		schedule.Description = req.Description
	}

	if req.TaskType != "" {
		schedule.TaskType = entity.TaskType(req.TaskType)
	}

	if req.TaskData != nil {
		schedule.TaskData = req.TaskData
	}

	if req.Priority != "" {
		schedule.Priority = entity.TaskPriority(req.Priority)
	}

	if req.ExecutorType != "" {
		schedule.ExecutorType = entity.ExecutorType(req.ExecutorType)
	}

	if req.Timeout > 0 {
		schedule.Timeout = req.Timeout
	}

	if req.MaxRetries > 0 {
		schedule.MaxRetries = req.MaxRetries
	}

	if req.Frequency != "" {
		schedule.Frequency = entity.ScheduleFrequency(req.Frequency)
	}

	if req.CronExpression != "" {
		schedule.CronExpression = req.CronExpression
	}

	if req.Interval > 0 {
		schedule.Interval = req.Interval
	}

	if req.MaxRuns > 0 {
		schedule.MaxRuns = req.MaxRuns
	}

	if len(req.Tags) > 0 {
		schedule.Tags = req.Tags
	}

	if err := h.scheduleRepo.Update(c.Context(), schedule); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update schedule",
			"code":    "UPDATE_FAILED",
		})
	}

	return c.JSON(scheduleToResponse(schedule))
}

// DeleteSchedule handles DELETE /api/v1/schedules/:id
func (h *ScheduleHandler) DeleteSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	if err := h.scheduleRepo.Delete(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete schedule",
			"code":    "DELETE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"schedule_id": id,
		"message":     "Schedule deleted successfully",
	})
}

// PauseSchedule handles POST /api/v1/schedules/:id/pause
func (h *ScheduleHandler) PauseSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	if err := h.scheduleRepo.UpdateStatus(c.Context(), id, entity.ScheduleStatusPaused); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to pause schedule",
			"code":    "PAUSE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"schedule_id": id,
		"status":      string(entity.ScheduleStatusPaused),
		"message":     "Schedule paused successfully",
	})
}

// ResumeSchedule handles POST /api/v1/schedules/:id/resume
func (h *ScheduleHandler) ResumeSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	schedule, err := h.scheduleRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule not found",
			"code":    "NOT_FOUND",
		})
	}

	schedule.Resume()
	schedule.CalculateNextRun()

	if err := h.scheduleRepo.Update(c.Context(), schedule); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to resume schedule",
			"code":    "RESUME_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"schedule_id": id,
		"status":      string(entity.ScheduleStatusActive),
		"next_run_at": schedule.NextRunAt.Format(time.RFC3339),
		"message":     "Schedule resumed successfully",
	})
}

// TriggerSchedule handles POST /api/v1/schedules/:id/trigger
func (h *ScheduleHandler) TriggerSchedule(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule ID is required",
			"code":    "MISSING_ID",
		})
	}

	schedule, err := h.scheduleRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Schedule not found",
			"code":    "NOT_FOUND",
		})
	}

	// Create task from schedule
	task := schedule.CreateTask()

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"task_id":     task.TaskID,
		"schedule_id": id,
		"status":      string(task.Context.CurrentStatus),
		"message":     "Schedule triggered manually",
	})
}

// EnableSchedule handles POST /api/v1/schedules/:id/enable
func (h *ScheduleHandler) EnableSchedule(c *fiber.Ctx) error {
	return h.ResumeSchedule(c)
}

// DisableSchedule handles POST /api/v1/schedules/:id/disable
func (h *ScheduleHandler) DisableSchedule(c *fiber.Ctx) error {
	return h.PauseSchedule(c)
}
