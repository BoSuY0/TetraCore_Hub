// Package webhook provides webhook management use cases for TetraCore Hub.
package webhook

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/tetra/core-hub/internal/delivery/http/handler"
	"github.com/tetra/core-hub/internal/domain/entity"
	"github.com/tetra/core-hub/internal/domain/repository"
	"github.com/tetra/core-hub/pkg/errors"
	"github.com/tetra/core-hub/pkg/logger"
)

// Config holds webhook configuration.
type Config struct {
	Timeout       time.Duration
	MaxRetries    int
	RetryDelay    time.Duration
	WorkerCount   int
}

// UseCase handles webhook management operations.
type UseCase struct {
	repo       repository.WebhookRepository
	config     Config
	log        logger.LogFields
	httpClient *http.Client
	queue      chan webhookDelivery
	stopCh     chan struct{}
	wg         sync.WaitGroup
}

type webhookDelivery struct {
	webhook *entity.Webhook
	event   entity.WebhookEvent
	payload map[string]any
}

// NewUseCase creates a new webhook use case.
func NewUseCase(repo repository.WebhookRepository, config Config) *UseCase {
	if config.Timeout == 0 {
		config.Timeout = 10 * time.Second
	}
	if config.MaxRetries == 0 {
		config.MaxRetries = 3
	}
	if config.RetryDelay == 0 {
		config.RetryDelay = 5 * time.Second
	}
	if config.WorkerCount == 0 {
		config.WorkerCount = 5
	}

	return &UseCase{
		repo:   repo,
		config: config,
		log:    logger.LogFields{"component": "webhook-usecase"},
		httpClient: &http.Client{
			Timeout: config.Timeout,
		},
		queue:  make(chan webhookDelivery, 1000),
		stopCh: make(chan struct{}),
	}
}

// Start starts the webhook delivery workers.
func (uc *UseCase) Start() {
	log := logger.WithFields(uc.log)
	log.Info().Int("workers", uc.config.WorkerCount).Msg("Starting webhook delivery workers")

	for i := 0; i < uc.config.WorkerCount; i++ {
		uc.wg.Add(1)
		go uc.deliveryWorker(i)
	}
}

// Stop stops the webhook delivery workers.
func (uc *UseCase) Stop() {
	log := logger.WithFields(uc.log)
	log.Info().Msg("Stopping webhook delivery workers")
	close(uc.stopCh)
	uc.wg.Wait()
}

// deliveryWorker processes webhook deliveries.
func (uc *UseCase) deliveryWorker(id int) {
	defer uc.wg.Done()
	log := logger.WithFields(uc.log).With("worker_id", id)

	for {
		select {
		case <-uc.stopCh:
			return
		case delivery := <-uc.queue:
			if err := uc.deliver(delivery); err != nil {
				log.Error().Err(err).
					Str("webhook_id", delivery.webhook.ID).
					Str("event", string(delivery.event)).
					Msg("Failed to deliver webhook")
			}
		}
	}
}

// deliver sends a webhook with retries.
func (uc *UseCase) deliver(delivery webhookDelivery) error {
	log := logger.WithFields(uc.log).With("webhook_id", delivery.webhook.ID)

	payload := map[string]any{
		"event":     delivery.event,
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"data":      delivery.payload,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("failed to marshal payload: %w", err)
	}

	signature := delivery.webhook.SignPayload(body)

	var lastErr error
	for attempt := 0; attempt <= uc.config.MaxRetries; attempt++ {
		if attempt > 0 {
			time.Sleep(uc.config.RetryDelay * time.Duration(attempt))
		}

		req, err := http.NewRequest(http.MethodPost, delivery.webhook.URL, bytes.NewReader(body))
		if err != nil {
			return fmt.Errorf("failed to create request: %w", err)
		}

		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Webhook-Signature", signature)
		req.Header.Set("X-Webhook-Event", string(delivery.event))
		req.Header.Set("User-Agent", "TetraCore-Hub/1.0")

		resp, err := uc.httpClient.Do(req)
		if err != nil {
			lastErr = err
			log.Warn().Err(err).Int("attempt", attempt+1).Msg("Webhook delivery failed")
			continue
		}
		resp.Body.Close()

		if resp.StatusCode >= 200 && resp.StatusCode < 300 {
			log.Debug().Str("event", string(delivery.event)).Msg("Webhook delivered successfully")
			return nil
		}

		lastErr = fmt.Errorf("unexpected status code: %d", resp.StatusCode)
		log.Warn().Int("status", resp.StatusCode).Int("attempt", attempt+1).Msg("Webhook delivery returned non-2xx")
	}

	return lastErr
}

// Trigger triggers webhooks for an event.
func (uc *UseCase) Trigger(ctx context.Context, event entity.WebhookEvent, payload map[string]any) {
	log := logger.WithFields(uc.log).With("event", event)

	webhooks, err := uc.repo.GetByEvent(ctx, event)
	if err != nil {
		log.Error().Err(err).Msg("Failed to get webhooks for event")
		return
	}

	for _, webhook := range webhooks {
		if !webhook.Enabled {
			continue
		}

		select {
		case uc.queue <- webhookDelivery{
			webhook: webhook,
			event:   event,
			payload: payload,
		}:
		default:
			log.Warn().Str("webhook_id", webhook.ID).Msg("Webhook queue full, dropping delivery")
		}
	}
}

// Create creates a new webhook.
func (uc *UseCase) Create(ctx context.Context, input handler.CreateWebhookInput) (*entity.Webhook, error) {
	log := logger.WithFields(uc.log).With("name", input.Name)

	webhook := entity.NewWebhook(input.Name, input.URL, input.Secret, input.Events)

	if err := uc.repo.Save(ctx, webhook); err != nil {
		log.Error().Err(err).Msg("Failed to save webhook")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to save webhook")
	}

	log.Info().Str("webhook_id", webhook.ID).Msg("Webhook created")
	return webhook, nil
}

// GetByID retrieves a webhook by ID.
func (uc *UseCase) GetByID(ctx context.Context, id string) (*entity.Webhook, error) {
	webhook, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return nil, errors.ErrNotFound.With("webhook not found")
	}
	return webhook, nil
}

// GetAll retrieves all webhooks.
func (uc *UseCase) GetAll(ctx context.Context) ([]*entity.Webhook, error) {
	return uc.repo.GetAll(ctx)
}

// Update updates a webhook.
func (uc *UseCase) Update(ctx context.Context, id string, input handler.UpdateWebhookInput) (*entity.Webhook, error) {
	log := logger.WithFields(uc.log).With("webhook_id", id)

	webhook, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return nil, errors.ErrNotFound.With("webhook not found")
	}

	if input.Name != nil {
		webhook.Name = *input.Name
	}
	if input.URL != nil {
		webhook.URL = *input.URL
	}
	if input.Secret != nil {
		webhook.Secret = *input.Secret
	}
	if input.Events != nil {
		webhook.Events = *input.Events
	}

	webhook.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, webhook); err != nil {
		log.Error().Err(err).Msg("Failed to update webhook")
		return nil, errors.ErrInternalServer.Wrap(err, "failed to update webhook")
	}

	log.Info().Msg("Webhook updated")
	return webhook, nil
}

// Delete deletes a webhook.
func (uc *UseCase) Delete(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log).With("webhook_id", id)

	if err := uc.repo.Delete(ctx, id); err != nil {
		return errors.ErrNotFound.With("webhook not found")
	}

	log.Info().Msg("Webhook deleted")
	return nil
}

// Enable enables a webhook.
func (uc *UseCase) Enable(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log).With("webhook_id", id)

	webhook, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return errors.ErrNotFound.With("webhook not found")
	}

	webhook.Enabled = true
	webhook.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, webhook); err != nil {
		return errors.ErrInternalServer.Wrap(err, "failed to enable webhook")
	}

	log.Info().Msg("Webhook enabled")
	return nil
}

// Disable disables a webhook.
func (uc *UseCase) Disable(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log).With("webhook_id", id)

	webhook, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return errors.ErrNotFound.With("webhook not found")
	}

	webhook.Enabled = false
	webhook.UpdatedAt = time.Now().UTC()

	if err := uc.repo.Save(ctx, webhook); err != nil {
		return errors.ErrInternalServer.Wrap(err, "failed to disable webhook")
	}

	log.Info().Msg("Webhook disabled")
	return nil
}

// Test sends a test event to a webhook.
func (uc *UseCase) Test(ctx context.Context, id string) error {
	log := logger.WithFields(uc.log).With("webhook_id", id)

	webhook, err := uc.repo.GetByID(ctx, id)
	if err != nil {
		return errors.ErrNotFound.With("webhook not found")
	}

	payload := map[string]any{
		"message": "This is a test webhook delivery from TetraCore Hub",
		"webhook": map[string]any{
			"id":   webhook.ID,
			"name": webhook.Name,
		},
	}

	delivery := webhookDelivery{
		webhook: webhook,
		event:   "test",
		payload: payload,
	}

	if err := uc.deliver(delivery); err != nil {
		log.Error().Err(err).Msg("Test webhook delivery failed")
		return fmt.Errorf("test delivery failed: %w", err)
	}

	log.Info().Msg("Test webhook delivered successfully")
	return nil
}

// Ensure interface compliance
var _ handler.WebhookService = (*UseCase)(nil)
