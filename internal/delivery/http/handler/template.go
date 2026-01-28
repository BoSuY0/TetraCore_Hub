// Package handler provides HTTP handlers for TetraCore Hub.
package handler

import (
	"strconv"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
)

// TemplateHandler handles template management endpoints.
type TemplateHandler struct {
	templateRepo repository.TemplateRepository
}

// NewTemplateHandler creates a new template handler.
func NewTemplateHandler(templateRepo repository.TemplateRepository) *TemplateHandler {
	return &TemplateHandler{
		templateRepo: templateRepo,
	}
}

// TemplateResponse represents a template in API responses.
type TemplateResponse struct {
	ID           string                     `json:"id"`
	Name         string                     `json:"name"`
	Description  string                     `json:"description,omitempty"`
	TaskType     string                     `json:"task_type"`
	Priority     string                     `json:"priority"`
	ExecutorType string                     `json:"executor_type"`
	Timeout      int                        `json:"timeout"`
	MaxRetries   int                        `json:"max_retries"`
	Variables    []entity.TemplateVariable  `json:"variables"`
	DefaultData  map[string]any             `json:"default_data,omitempty"`
	IsPublic     bool                       `json:"is_public"`
	CreatedBy    string                     `json:"created_by"`
	CreatedAt    string                     `json:"created_at"`
	UpdatedAt    string                     `json:"updated_at"`
	UsageCount   int                        `json:"usage_count"`
	LastUsedAt   string                     `json:"last_used_at,omitempty"`
	Tags         []string                   `json:"tags"`
	Category     string                     `json:"category,omitempty"`
}

// CreateTemplateRequest represents a template creation request.
type CreateTemplateRequest struct {
	Name         string                    `json:"name"`
	Description  string                    `json:"description,omitempty"`
	TaskType     string                    `json:"task_type"`
	Priority     string                    `json:"priority,omitempty"`
	ExecutorType string                    `json:"executor_type,omitempty"`
	Timeout      int                       `json:"timeout,omitempty"`
	MaxRetries   int                       `json:"max_retries,omitempty"`
	Variables    []entity.TemplateVariable `json:"variables,omitempty"`
	DefaultData  map[string]any            `json:"default_data,omitempty"`
	IsPublic     bool                      `json:"is_public,omitempty"`
	Tags         []string                  `json:"tags,omitempty"`
	Category     string                    `json:"category,omitempty"`
}

// ExecuteTemplateRequest represents a template execution request.
type ExecuteTemplateRequest struct {
	Input map[string]any `json:"input"`
}

// templateToResponse converts a template to API response.
func templateToResponse(t *entity.TaskTemplate) *TemplateResponse {
	resp := &TemplateResponse{
		ID:           t.ID,
		Name:         t.Name,
		Description:  t.Description,
		TaskType:     string(t.TaskType),
		Priority:     string(t.Priority),
		ExecutorType: string(t.ExecutorType),
		Timeout:      t.Timeout,
		MaxRetries:   t.MaxRetries,
		Variables:    t.Variables,
		DefaultData:  t.DefaultData,
		IsPublic:     t.IsPublic,
		CreatedBy:    t.CreatedBy,
		CreatedAt:    t.CreatedAt.Format(time.RFC3339),
		UpdatedAt:    t.UpdatedAt.Format(time.RFC3339),
		UsageCount:   t.UsageCount,
		Tags:         t.Tags,
		Category:     t.Category,
	}

	if t.LastUsedAt != nil {
		resp.LastUsedAt = t.LastUsedAt.Format(time.RFC3339)
	}

	return resp
}

// GetTemplates handles GET /api/v1/templates
func (h *TemplateHandler) GetTemplates(c *fiber.Ctx) error {
	limitStr := c.Query("limit", "100")
	offsetStr := c.Query("offset", "0")
	category := c.Query("category")
	tag := c.Query("tag")
	taskType := c.Query("task_type")
	publicOnly := c.Query("public") == "true"

	limit, _ := strconv.Atoi(limitStr)
	offset, _ := strconv.Atoi(offsetStr)

	var templates []*entity.TaskTemplate
	var err error

	if publicOnly {
		templates, err = h.templateRepo.GetPublic(c.Context(), limit, offset)
	} else if category != "" {
		templates, err = h.templateRepo.GetByCategory(c.Context(), category, limit)
	} else if tag != "" {
		templates, err = h.templateRepo.GetByTag(c.Context(), tag, limit)
	} else if taskType != "" {
		templates, err = h.templateRepo.GetByTaskType(c.Context(), entity.TaskType(taskType), limit)
	} else {
		templates, err = h.templateRepo.GetAll(c.Context(), limit, offset)
	}

	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve templates",
			"code":    "INTERNAL_ERROR",
		})
	}

	response := make([]*TemplateResponse, len(templates))
	for i, t := range templates {
		response[i] = templateToResponse(t)
	}

	return c.JSON(fiber.Map{
		"templates": response,
		"total":     len(response),
	})
}

// GetMyTemplates handles GET /api/v1/templates/my
func (h *TemplateHandler) GetMyTemplates(c *fiber.Ctx) error {
	// Get user ID from context (set by auth middleware)
	userID := c.Locals("user_id")
	if userID == nil {
		return c.Status(fiber.StatusUnauthorized).JSON(fiber.Map{
			"error":   true,
			"message": "Authentication required",
			"code":    "UNAUTHORIZED",
		})
	}

	templates, err := h.templateRepo.GetByCreator(c.Context(), userID.(string), 0)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to retrieve templates",
			"code":    "INTERNAL_ERROR",
		})
	}

	response := make([]*TemplateResponse, len(templates))
	for i, t := range templates {
		response[i] = templateToResponse(t)
	}

	return c.JSON(fiber.Map{
		"templates": response,
		"total":     len(response),
	})
}

// GetTemplate handles GET /api/v1/templates/:id
func (h *TemplateHandler) GetTemplate(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Template ID is required",
			"code":    "MISSING_ID",
		})
	}

	template, err := h.templateRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Template not found",
			"code":    "NOT_FOUND",
		})
	}

	return c.JSON(templateToResponse(template))
}

// CreateTemplate handles POST /api/v1/templates
func (h *TemplateHandler) CreateTemplate(c *fiber.Ctx) error {
	var req CreateTemplateRequest
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
			"message": "Template name is required",
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

	// Check if name already exists
	exists, _ := h.templateRepo.ExistsByName(c.Context(), req.Name)
	if exists {
		return c.Status(fiber.StatusConflict).JSON(fiber.Map{
			"error":   true,
			"message": "Template with this name already exists",
			"code":    "NAME_EXISTS",
		})
	}

	// Get creator from context
	createdBy := "system"
	if userID := c.Locals("user_id"); userID != nil {
		createdBy = userID.(string)
	}

	template := entity.NewTaskTemplate(req.Name, entity.TaskType(req.TaskType), createdBy)
	template.Description = req.Description
	template.IsPublic = req.IsPublic
	template.Category = req.Category

	if req.Priority != "" {
		template.Priority = entity.TaskPriority(req.Priority)
	}

	if req.ExecutorType != "" {
		template.ExecutorType = entity.ExecutorType(req.ExecutorType)
	}

	if req.Timeout > 0 {
		template.Timeout = req.Timeout
	}

	if req.MaxRetries > 0 {
		template.MaxRetries = req.MaxRetries
	}

	if len(req.Variables) > 0 {
		template.Variables = req.Variables
	}

	if req.DefaultData != nil {
		template.DefaultData = req.DefaultData
	}

	if len(req.Tags) > 0 {
		template.Tags = req.Tags
	}

	if err := h.templateRepo.Save(c.Context(), template); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to create template",
			"code":    "CREATE_FAILED",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(templateToResponse(template))
}

// UpdateTemplate handles PUT /api/v1/templates/:id
func (h *TemplateHandler) UpdateTemplate(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Template ID is required",
			"code":    "MISSING_ID",
		})
	}

	template, err := h.templateRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Template not found",
			"code":    "NOT_FOUND",
		})
	}

	var req CreateTemplateRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	// Update fields
	if req.Name != "" && req.Name != template.Name {
		exists, _ := h.templateRepo.ExistsByName(c.Context(), req.Name)
		if exists {
			return c.Status(fiber.StatusConflict).JSON(fiber.Map{
				"error":   true,
				"message": "Template with this name already exists",
				"code":    "NAME_EXISTS",
			})
		}
		template.Name = req.Name
	}

	if req.Description != "" {
		template.Description = req.Description
	}

	if req.TaskType != "" {
		template.TaskType = entity.TaskType(req.TaskType)
	}

	if req.Priority != "" {
		template.Priority = entity.TaskPriority(req.Priority)
	}

	if req.ExecutorType != "" {
		template.ExecutorType = entity.ExecutorType(req.ExecutorType)
	}

	if req.Timeout > 0 {
		template.Timeout = req.Timeout
	}

	if req.MaxRetries > 0 {
		template.MaxRetries = req.MaxRetries
	}

	if len(req.Variables) > 0 {
		template.Variables = req.Variables
	}

	if req.DefaultData != nil {
		template.DefaultData = req.DefaultData
	}

	if len(req.Tags) > 0 {
		template.Tags = req.Tags
	}

	if req.Category != "" {
		template.Category = req.Category
	}

	template.IsPublic = req.IsPublic

	if err := h.templateRepo.Update(c.Context(), template); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to update template",
			"code":    "UPDATE_FAILED",
		})
	}

	return c.JSON(templateToResponse(template))
}

// DeleteTemplate handles DELETE /api/v1/templates/:id
func (h *TemplateHandler) DeleteTemplate(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Template ID is required",
			"code":    "MISSING_ID",
		})
	}

	if err := h.templateRepo.Delete(c.Context(), id); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error":   true,
			"message": "Failed to delete template",
			"code":    "DELETE_FAILED",
		})
	}

	return c.JSON(fiber.Map{
		"template_id": id,
		"message":     "Template deleted successfully",
	})
}

// ExecuteTemplate handles POST /api/v1/templates/:id/execute
func (h *TemplateHandler) ExecuteTemplate(c *fiber.Ctx) error {
	id := c.Params("id")
	if id == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Template ID is required",
			"code":    "MISSING_ID",
		})
	}

	template, err := h.templateRepo.Get(c.Context(), id)
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"error":   true,
			"message": "Template not found",
			"code":    "NOT_FOUND",
		})
	}

	var req ExecuteTemplateRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":   true,
			"message": "Invalid request body",
			"code":    "INVALID_REQUEST",
		})
	}

	if req.Input == nil {
		req.Input = make(map[string]any)
	}

	// Create task from template
	task, validationErrors := template.CreateTask(req.Input)
	if len(validationErrors) > 0 {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error":            true,
			"message":          "Validation failed",
			"code":             "VALIDATION_FAILED",
			"validation_errors": validationErrors,
		})
	}

	// Increment usage counter
	h.templateRepo.IncrementUsage(c.Context(), id)

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"task_id":     task.TaskID,
		"template_id": id,
		"status":      string(task.Context.CurrentStatus),
		"message":     "Task created from template",
	})
}
