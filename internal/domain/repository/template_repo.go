// Package repository defines repository interfaces for TetraCore Hub.
package repository

import (
	"context"
	"errors"

	"github.com/tetra/core-hub/internal/domain/entity"
)

// Template repository errors.
var (
	ErrTemplateNotFound      = errors.New("template not found")
	ErrTemplateAlreadyExists = errors.New("template already exists")
)

// TemplateRepository defines the interface for task template data access.
type TemplateRepository interface {
	// Save stores a template.
	Save(ctx context.Context, template *entity.TaskTemplate) error

	// Get retrieves a template by ID.
	Get(ctx context.Context, id string) (*entity.TaskTemplate, error)

	// GetByName retrieves a template by name.
	GetByName(ctx context.Context, name string) (*entity.TaskTemplate, error)

	// GetAll retrieves all templates with optional pagination.
	GetAll(ctx context.Context, limit, offset int) ([]*entity.TaskTemplate, error)

	// GetByCreator retrieves templates created by a specific user.
	GetByCreator(ctx context.Context, createdBy string, limit int) ([]*entity.TaskTemplate, error)

	// GetPublic retrieves all public templates.
	GetPublic(ctx context.Context, limit, offset int) ([]*entity.TaskTemplate, error)

	// GetByTaskType retrieves templates by task type.
	GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.TaskTemplate, error)

	// GetByCategory retrieves templates by category.
	GetByCategory(ctx context.Context, category string, limit int) ([]*entity.TaskTemplate, error)

	// GetByTag retrieves templates by tag.
	GetByTag(ctx context.Context, tag string, limit int) ([]*entity.TaskTemplate, error)

	// Search searches templates by name or description.
	Search(ctx context.Context, query string, limit int) ([]*entity.TaskTemplate, error)

	// Update updates a template.
	Update(ctx context.Context, template *entity.TaskTemplate) error

	// Delete removes a template.
	Delete(ctx context.Context, id string) error

	// IncrementUsage increments the usage count for a template.
	IncrementUsage(ctx context.Context, id string) error

	// Count returns the total number of templates.
	Count(ctx context.Context) (int64, error)

	// CountByCreator returns the count of templates by creator.
	CountByCreator(ctx context.Context, createdBy string) (int64, error)

	// Exists checks if a template exists.
	Exists(ctx context.Context, id string) (bool, error)

	// ExistsByName checks if a template with the given name exists.
	ExistsByName(ctx context.Context, name string) (bool, error)
}
