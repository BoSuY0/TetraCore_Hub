// Package repository provides repository implementations for TetraCore Hub.
package repository

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	goredis "github.com/redis/go-redis/v9"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/logger"
)

const (
	templateKeyPrefix       = "template:"
	templateSetKey          = "templates"
	templateNameKey         = "templates:name:"
	templateCreatorSetKey   = "templates:creator:"
	templatePublicSetKey    = "templates:public"
	templateTaskTypeSetKey  = "templates:tasktype:"
	templateCategorySetKey  = "templates:category:"
	templateTagSetKey       = "templates:tag:"
)

// RedisTemplateRepository implements TemplateRepository using Redis.
type RedisTemplateRepository struct {
	client goredis.UniversalClient
	ttl    time.Duration
	log    logger.LogFields
}

// NewRedisTemplateRepository creates a new Redis template repository.
func NewRedisTemplateRepository(client goredis.UniversalClient) *RedisTemplateRepository {
	return &RedisTemplateRepository{
		client: client,
		ttl:    0, // No expiration for templates by default
		log:    logger.LogFields{"component": "redis-template-repo"},
	}
}

// Save stores a template.
func (r *RedisTemplateRepository) Save(ctx context.Context, template *entity.TaskTemplate) error {
	data, err := json.Marshal(template)
	if err != nil {
		return fmt.Errorf("failed to marshal template: %w", err)
	}

	key := templateKeyPrefix + template.ID

	pipe := r.client.Pipeline()
	pipe.Set(ctx, key, data, r.ttl)
	pipe.SAdd(ctx, templateSetKey, template.ID)
	pipe.Set(ctx, templateNameKey+template.Name, template.ID, r.ttl)
	pipe.SAdd(ctx, templateCreatorSetKey+template.CreatedBy, template.ID)
	pipe.SAdd(ctx, templateTaskTypeSetKey+string(template.TaskType), template.ID)

	if template.IsPublic {
		pipe.SAdd(ctx, templatePublicSetKey, template.ID)
	} else {
		pipe.SRem(ctx, templatePublicSetKey, template.ID)
	}

	if template.Category != "" {
		pipe.SAdd(ctx, templateCategorySetKey+template.Category, template.ID)
	}

	for _, tag := range template.Tags {
		pipe.SAdd(ctx, templateTagSetKey+tag, template.ID)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// Get retrieves a template by ID.
func (r *RedisTemplateRepository) Get(ctx context.Context, id string) (*entity.TaskTemplate, error) {
	key := templateKeyPrefix + id
	data, err := r.client.Get(ctx, key).Result()
	if err != nil {
		return nil, repository.ErrTemplateNotFound
	}

	var template entity.TaskTemplate
	if err := json.Unmarshal([]byte(data), &template); err != nil {
		return nil, fmt.Errorf("failed to unmarshal template: %w", err)
	}

	return &template, nil
}

// GetByName retrieves a template by name.
func (r *RedisTemplateRepository) GetByName(ctx context.Context, name string) (*entity.TaskTemplate, error) {
	templateID, err := r.client.Get(ctx, templateNameKey+name).Result()
	if err != nil {
		return nil, repository.ErrTemplateNotFound
	}

	return r.Get(ctx, templateID)
}

// GetAll retrieves all templates with optional pagination.
func (r *RedisTemplateRepository) GetAll(ctx context.Context, limit, offset int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templateSetKey).Result()
	if err != nil {
		return nil, err
	}

	// Apply pagination
	start := offset
	end := offset + limit
	if start > len(templateIDs) {
		return []*entity.TaskTemplate{}, nil
	}
	if end > len(templateIDs) || limit == 0 {
		end = len(templateIDs)
	}

	templates := make([]*entity.TaskTemplate, 0, end-start)
	for i := start; i < end; i++ {
		template, err := r.Get(ctx, templateIDs[i])
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// GetByCreator retrieves templates created by a specific user.
func (r *RedisTemplateRepository) GetByCreator(ctx context.Context, createdBy string, limit int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templateCreatorSetKey+createdBy).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(templateIDs) {
		templateIDs = templateIDs[:limit]
	}

	templates := make([]*entity.TaskTemplate, 0, len(templateIDs))
	for _, id := range templateIDs {
		template, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// GetPublic retrieves all public templates.
func (r *RedisTemplateRepository) GetPublic(ctx context.Context, limit, offset int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templatePublicSetKey).Result()
	if err != nil {
		return nil, err
	}

	// Apply pagination
	start := offset
	end := offset + limit
	if start > len(templateIDs) {
		return []*entity.TaskTemplate{}, nil
	}
	if end > len(templateIDs) || limit == 0 {
		end = len(templateIDs)
	}

	templates := make([]*entity.TaskTemplate, 0, end-start)
	for i := start; i < end; i++ {
		template, err := r.Get(ctx, templateIDs[i])
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// GetByTaskType retrieves templates by task type.
func (r *RedisTemplateRepository) GetByTaskType(ctx context.Context, taskType entity.TaskType, limit int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templateTaskTypeSetKey+string(taskType)).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(templateIDs) {
		templateIDs = templateIDs[:limit]
	}

	templates := make([]*entity.TaskTemplate, 0, len(templateIDs))
	for _, id := range templateIDs {
		template, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// GetByCategory retrieves templates by category.
func (r *RedisTemplateRepository) GetByCategory(ctx context.Context, category string, limit int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templateCategorySetKey+category).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(templateIDs) {
		templateIDs = templateIDs[:limit]
	}

	templates := make([]*entity.TaskTemplate, 0, len(templateIDs))
	for _, id := range templateIDs {
		template, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// GetByTag retrieves templates by tag.
func (r *RedisTemplateRepository) GetByTag(ctx context.Context, tag string, limit int) ([]*entity.TaskTemplate, error) {
	templateIDs, err := r.client.SMembers(ctx, templateTagSetKey+tag).Result()
	if err != nil {
		return nil, err
	}

	if limit > 0 && limit < len(templateIDs) {
		templateIDs = templateIDs[:limit]
	}

	templates := make([]*entity.TaskTemplate, 0, len(templateIDs))
	for _, id := range templateIDs {
		template, err := r.Get(ctx, id)
		if err != nil {
			continue
		}
		templates = append(templates, template)
	}

	return templates, nil
}

// Search searches templates by name or description.
func (r *RedisTemplateRepository) Search(ctx context.Context, query string, limit int) ([]*entity.TaskTemplate, error) {
	query = strings.ToLower(query)

	templateIDs, err := r.client.SMembers(ctx, templateSetKey).Result()
	if err != nil {
		return nil, err
	}

	templates := make([]*entity.TaskTemplate, 0)
	for _, id := range templateIDs {
		template, err := r.Get(ctx, id)
		if err != nil {
			continue
		}

		// Search in name and description
		if strings.Contains(strings.ToLower(template.Name), query) ||
			strings.Contains(strings.ToLower(template.Description), query) {
			templates = append(templates, template)
			if limit > 0 && len(templates) >= limit {
				break
			}
		}
	}

	return templates, nil
}

// Update updates a template.
func (r *RedisTemplateRepository) Update(ctx context.Context, template *entity.TaskTemplate) error {
	// Get existing template to clean up old indices
	existing, err := r.Get(ctx, template.ID)
	if err == nil && existing != nil {
		// Remove old name mapping if changed
		if existing.Name != template.Name {
			r.client.Del(ctx, templateNameKey+existing.Name)
		}
		// Remove old category if changed
		if existing.Category != template.Category && existing.Category != "" {
			r.client.SRem(ctx, templateCategorySetKey+existing.Category, template.ID)
		}
		// Remove old tags
		for _, tag := range existing.Tags {
			r.client.SRem(ctx, templateTagSetKey+tag, template.ID)
		}
	}

	template.UpdatedAt = time.Now().UTC()
	return r.Save(ctx, template)
}

// Delete removes a template.
func (r *RedisTemplateRepository) Delete(ctx context.Context, id string) error {
	template, err := r.Get(ctx, id)
	if err != nil {
		return nil // Template doesn't exist, nothing to delete
	}

	pipe := r.client.Pipeline()
	pipe.Del(ctx, templateKeyPrefix+id)
	pipe.SRem(ctx, templateSetKey, id)
	pipe.Del(ctx, templateNameKey+template.Name)
	pipe.SRem(ctx, templateCreatorSetKey+template.CreatedBy, id)
	pipe.SRem(ctx, templateTaskTypeSetKey+string(template.TaskType), id)
	pipe.SRem(ctx, templatePublicSetKey, id)

	if template.Category != "" {
		pipe.SRem(ctx, templateCategorySetKey+template.Category, id)
	}

	for _, tag := range template.Tags {
		pipe.SRem(ctx, templateTagSetKey+tag, id)
	}

	_, err = pipe.Exec(ctx)
	return err
}

// IncrementUsage increments the usage count for a template.
func (r *RedisTemplateRepository) IncrementUsage(ctx context.Context, id string) error {
	template, err := r.Get(ctx, id)
	if err != nil {
		return err
	}

	template.UsageCount++
	now := time.Now().UTC()
	template.LastUsedAt = &now
	template.UpdatedAt = now

	return r.Save(ctx, template)
}

// Count returns the total number of templates.
func (r *RedisTemplateRepository) Count(ctx context.Context) (int64, error) {
	return r.client.SCard(ctx, templateSetKey).Result()
}

// CountByCreator returns the count of templates by creator.
func (r *RedisTemplateRepository) CountByCreator(ctx context.Context, createdBy string) (int64, error) {
	return r.client.SCard(ctx, templateCreatorSetKey+createdBy).Result()
}

// Exists checks if a template exists.
func (r *RedisTemplateRepository) Exists(ctx context.Context, id string) (bool, error) {
	exists, err := r.client.Exists(ctx, templateKeyPrefix+id).Result()
	return exists > 0, err
}

// ExistsByName checks if a template with the given name exists.
func (r *RedisTemplateRepository) ExistsByName(ctx context.Context, name string) (bool, error) {
	exists, err := r.client.Exists(ctx, templateNameKey+name).Result()
	return exists > 0, err
}

// Ensure interface compliance
var _ repository.TemplateRepository = (*RedisTemplateRepository)(nil)
