// Package audit provides audit log use cases for TetraCore Hub.
package audit

import (
	"context"
	"time"

	"github.com/tetra/core-hub/internal/delivery/http/handler"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds audit configuration.
type Config struct {
	RetentionDays int
	MaxEntries    int64
}

// UseCase handles audit log operations.
type UseCase struct {
	repo   repository.AuditRepository
	config Config
	log    logger.LogFields
}

// NewUseCase creates a new audit use case.
func NewUseCase(repo repository.AuditRepository, config Config) *UseCase {
	if config.RetentionDays == 0 {
		config.RetentionDays = 90 // Default 90 days retention
	}

	return &UseCase{
		repo:   repo,
		config: config,
		log:    logger.LogFields{"component": "audit-usecase"},
	}
}

// Log records an audit entry.
func (uc *UseCase) Log(ctx context.Context, entry *entity.AuditEntry) error {
	log := logger.WithFields(uc.log).With("action", entry.Action)

	if entry.ID == "" {
		entry.ID = entity.GenerateID()
	}
	if entry.Timestamp.IsZero() {
		entry.Timestamp = time.Now().UTC()
	}

	if err := uc.repo.Save(ctx, entry); err != nil {
		log.Error().Err(err).Msg("Failed to save audit entry")
		return errors.ErrInternalServer.Wrap(err, "failed to save audit entry")
	}

	log.Debug().Str("entry_id", entry.ID).Msg("Audit entry recorded")
	return nil
}

// LogAction is a convenience method to log an audit action.
func (uc *UseCase) LogAction(ctx context.Context, action entity.AuditAction, userID, resource, resourceID, ipAddress string, success bool, details map[string]any) error {
	entry := &entity.AuditEntry{
		ID:         entity.GenerateID(),
		Timestamp:  time.Now().UTC(),
		Action:     action,
		UserID:     userID,
		Resource:   resource,
		ResourceID: resourceID,
		IPAddress:  ipAddress,
		Success:    success,
		Details:    details,
	}
	return uc.Log(ctx, entry)
}

// Query retrieves audit entries based on filter.
func (uc *UseCase) Query(ctx context.Context, filter entity.AuditFilter) ([]*entity.AuditEntry, error) {
	// Apply defaults
	if filter.Limit == 0 {
		filter.Limit = 100
	}
	if filter.Limit > 1000 {
		filter.Limit = 1000
	}

	return uc.repo.Query(ctx, filter)
}

// Count returns the count of audit entries matching the filter.
func (uc *UseCase) Count(ctx context.Context, filter entity.AuditFilter) (int64, error) {
	return uc.repo.Count(ctx, filter)
}

// GetByID retrieves an audit entry by ID.
func (uc *UseCase) GetByID(ctx context.Context, id string) (*entity.AuditEntry, error) {
	entry, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return nil, errors.ErrNotFound.With("audit entry not found")
	}
	return entry, nil
}

// GetByUser retrieves audit entries for a user.
func (uc *UseCase) GetByUser(ctx context.Context, userID string, limit int) ([]*entity.AuditEntry, error) {
	if limit == 0 {
		limit = 100
	}

	filter := entity.AuditFilter{
		UserID: userID,
		Limit:  limit,
	}

	return uc.repo.Query(ctx, filter)
}

// GetByResource retrieves audit entries for a resource.
func (uc *UseCase) GetByResource(ctx context.Context, resource, resourceID string, limit int) ([]*entity.AuditEntry, error) {
	if limit == 0 {
		limit = 100
	}

	filter := entity.AuditFilter{
		Resource:   resource,
		ResourceID: resourceID,
		Limit:      limit,
	}

	return uc.repo.Query(ctx, filter)
}

// GetRecent retrieves recent audit entries.
func (uc *UseCase) GetRecent(ctx context.Context, limit int) ([]*entity.AuditEntry, error) {
	if limit == 0 {
		limit = 100
	}

	filter := entity.AuditFilter{
		Limit: limit,
	}

	return uc.repo.Query(ctx, filter)
}

// Cleanup removes old audit entries.
func (uc *UseCase) Cleanup(ctx context.Context) (int64, error) {
	log := logger.WithFields(uc.log)

	cutoff := time.Now().UTC().AddDate(0, 0, -uc.config.RetentionDays)
	deleted, err := uc.repo.DeleteBefore(ctx, cutoff)
	if err != nil {
		log.Error().Err(err).Msg("Failed to cleanup old audit entries")
		return 0, err
	}

	if deleted > 0 {
		log.Info().Int64("count", deleted).Msg("Cleaned up old audit entries")
	}

	return deleted, nil
}

// GetStats returns audit statistics.
func (uc *UseCase) GetStats(ctx context.Context) (*AuditStats, error) {
	total, _ := uc.repo.Count(ctx, entity.AuditFilter{})

	// Count by success
	successFilter := true
	successCount, _ := uc.repo.Count(ctx, entity.AuditFilter{Success: &successFilter})
	failedFilter := false
	failedCount, _ := uc.repo.Count(ctx, entity.AuditFilter{Success: &failedFilter})

	// Get last 24 hours count
	last24h := time.Now().UTC().Add(-24 * time.Hour)
	last24hCount, _ := uc.repo.Count(ctx, entity.AuditFilter{StartTime: &last24h})

	return &AuditStats{
		Total:       total,
		Successful:  successCount,
		Failed:      failedCount,
		Last24Hours: last24hCount,
	}, nil
}

// AuditStats holds aggregated audit statistics.
type AuditStats struct {
	Total       int64 `json:"total"`
	Successful  int64 `json:"successful"`
	Failed      int64 `json:"failed"`
	Last24Hours int64 `json:"last_24_hours"`
}

// Ensure interface compliance
var _ handler.AuditService = (*UseCase)(nil)
