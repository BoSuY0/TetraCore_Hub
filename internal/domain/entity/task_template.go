// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"time"

	"github.com/google/uuid"
)

// VariableType represents the type of a template variable.
type VariableType string

const (
	VariableTypeString  VariableType = "string"
	VariableTypeNumber  VariableType = "number"
	VariableTypeBoolean VariableType = "boolean"
	VariableTypeArray   VariableType = "array"
	VariableTypeObject  VariableType = "object"
)

// TemplateVariable represents a variable in a task template.
type TemplateVariable struct {
	Name         string       `json:"name"`
	Type         VariableType `json:"type"`
	Description  string       `json:"description,omitempty"`
	Required     bool         `json:"required"`
	DefaultValue any          `json:"default_value,omitempty"`
	Validation   string       `json:"validation,omitempty"` // Regex pattern for validation
}

// TaskTemplate represents a reusable task template.
type TaskTemplate struct {
	ID             string             `json:"id"`
	Name           string             `json:"name"`
	Description    string             `json:"description,omitempty"`
	TaskType       TaskType           `json:"task_type"`
	TaskDataSchema map[string]any     `json:"task_data_schema"` // JSON Schema for validation
	DefaultData    map[string]any     `json:"default_data"`
	Variables      []TemplateVariable `json:"variables"`
	Priority       TaskPriority       `json:"priority"`
	ExecutorType   ExecutorType       `json:"executor_type"`
	Timeout        int                `json:"timeout"`
	MaxRetries     int                `json:"max_retries"`
	RetryDelay     int                `json:"retry_delay"`
	IsPublic       bool               `json:"is_public"`
	CreatedBy      string             `json:"created_by"`
	CreatedAt      time.Time          `json:"created_at"`
	UpdatedAt      time.Time          `json:"updated_at"`
	UsageCount     int                `json:"usage_count"`
	LastUsedAt     *time.Time         `json:"last_used_at,omitempty"`
	Tags           []string           `json:"tags"`
	Category       string             `json:"category,omitempty"`
	Metadata       map[string]any     `json:"metadata"`
}

// NewTaskTemplate creates a new task template.
func NewTaskTemplate(name string, taskType TaskType, createdBy string) *TaskTemplate {
	now := time.Now().UTC()
	return &TaskTemplate{
		ID:           uuid.New().String(),
		Name:         name,
		TaskType:     taskType,
		DefaultData:  make(map[string]any),
		Variables:    []TemplateVariable{},
		Priority:     TaskPriorityNormal,
		ExecutorType: ExecutorTypeWorker,
		Timeout:      300,
		MaxRetries:   3,
		RetryDelay:   5,
		IsPublic:     false,
		CreatedBy:    createdBy,
		CreatedAt:    now,
		UpdatedAt:    now,
		Tags:         []string{},
		Metadata:     make(map[string]any),
	}
}

// AddVariable adds a variable to the template.
func (t *TaskTemplate) AddVariable(variable TemplateVariable) {
	t.Variables = append(t.Variables, variable)
	t.UpdatedAt = time.Now().UTC()
}

// RemoveVariable removes a variable from the template.
func (t *TaskTemplate) RemoveVariable(name string) bool {
	for i, v := range t.Variables {
		if v.Name == name {
			t.Variables = append(t.Variables[:i], t.Variables[i+1:]...)
			t.UpdatedAt = time.Now().UTC()
			return true
		}
	}
	return false
}

// GetVariable returns a variable by name.
func (t *TaskTemplate) GetVariable(name string) *TemplateVariable {
	for i := range t.Variables {
		if t.Variables[i].Name == name {
			return &t.Variables[i]
		}
	}
	return nil
}

// ValidateInput validates input data against the template variables.
func (t *TaskTemplate) ValidateInput(input map[string]any) []string {
	var errors []string

	// Check required variables
	for _, v := range t.Variables {
		if v.Required {
			if _, exists := input[v.Name]; !exists {
				errors = append(errors, "missing required variable: "+v.Name)
			}
		}
	}

	// TODO: Add type validation and regex validation

	return errors
}

// CreateTask creates a task from this template with the given input.
func (t *TaskTemplate) CreateTask(input map[string]any) (*Task, []string) {
	// Validate input
	validationErrors := t.ValidateInput(input)
	if len(validationErrors) > 0 {
		return nil, validationErrors
	}

	// Merge default data with input
	taskData := make(map[string]any)
	for k, v := range t.DefaultData {
		taskData[k] = v
	}
	for k, v := range input {
		taskData[k] = v
	}

	// Apply variable defaults for missing values
	for _, v := range t.Variables {
		if _, exists := taskData[v.Name]; !exists && v.DefaultValue != nil {
			taskData[v.Name] = v.DefaultValue
		}
	}

	// Create task
	task := CreateTask(
		t.TaskType,
		taskData,
		WithPriority(t.Priority),
		WithExecutorType(t.ExecutorType),
		WithTimeout(t.Timeout),
		WithMaxRetries(t.MaxRetries),
		WithRetryDelay(t.RetryDelay),
	)
	task.Metadata.Source = "template"
	task.Metadata.CustomMetadata["template_id"] = t.ID
	task.Metadata.CustomMetadata["template_name"] = t.Name

	// Record usage
	t.UsageCount++
	now := time.Now().UTC()
	t.LastUsedAt = &now
	t.UpdatedAt = now

	return task, nil
}

// Clone creates a copy of the template with a new ID.
func (t *TaskTemplate) Clone(newName, createdBy string) *TaskTemplate {
	now := time.Now().UTC()
	clone := &TaskTemplate{
		ID:             uuid.New().String(),
		Name:           newName,
		Description:    t.Description,
		TaskType:       t.TaskType,
		TaskDataSchema: make(map[string]any),
		DefaultData:    make(map[string]any),
		Variables:      make([]TemplateVariable, len(t.Variables)),
		Priority:       t.Priority,
		ExecutorType:   t.ExecutorType,
		Timeout:        t.Timeout,
		MaxRetries:     t.MaxRetries,
		RetryDelay:     t.RetryDelay,
		IsPublic:       false,
		CreatedBy:      createdBy,
		CreatedAt:      now,
		UpdatedAt:      now,
		Tags:           make([]string, len(t.Tags)),
		Category:       t.Category,
		Metadata:       make(map[string]any),
	}

	// Deep copy maps and slices
	for k, v := range t.TaskDataSchema {
		clone.TaskDataSchema[k] = v
	}
	for k, v := range t.DefaultData {
		clone.DefaultData[k] = v
	}
	copy(clone.Variables, t.Variables)
	copy(clone.Tags, t.Tags)
	for k, v := range t.Metadata {
		clone.Metadata[k] = v
	}

	return clone
}

// MakePublic makes the template public.
func (t *TaskTemplate) MakePublic() {
	t.IsPublic = true
	t.UpdatedAt = time.Now().UTC()
}

// MakePrivate makes the template private.
func (t *TaskTemplate) MakePrivate() {
	t.IsPublic = false
	t.UpdatedAt = time.Now().UTC()
}

// ToMap converts the template to a map.
func (t *TaskTemplate) ToMap() map[string]any {
	var lastUsedAt *string
	if t.LastUsedAt != nil {
		s := t.LastUsedAt.Format(time.RFC3339)
		lastUsedAt = &s
	}

	return map[string]any{
		"id":               t.ID,
		"name":             t.Name,
		"description":      t.Description,
		"task_type":        string(t.TaskType),
		"task_data_schema": t.TaskDataSchema,
		"default_data":     t.DefaultData,
		"variables":        t.Variables,
		"priority":         string(t.Priority),
		"executor_type":    string(t.ExecutorType),
		"timeout":          t.Timeout,
		"max_retries":      t.MaxRetries,
		"retry_delay":      t.RetryDelay,
		"is_public":        t.IsPublic,
		"created_by":       t.CreatedBy,
		"created_at":       t.CreatedAt.Format(time.RFC3339),
		"updated_at":       t.UpdatedAt.Format(time.RFC3339),
		"usage_count":      t.UsageCount,
		"last_used_at":     lastUsedAt,
		"tags":             t.Tags,
		"category":         t.Category,
		"metadata":         t.Metadata,
	}
}
