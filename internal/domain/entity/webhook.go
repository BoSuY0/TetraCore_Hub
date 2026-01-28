// Package entity defines domain entities for TetraCore Hub.
package entity

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"time"

	"github.com/google/uuid"
)

// WebhookEvent represents types of webhook events.
type WebhookEvent string

const (
	WebhookEventTaskCreated    WebhookEvent = "task.created"
	WebhookEventTaskStarted    WebhookEvent = "task.started"
	WebhookEventTaskCompleted  WebhookEvent = "task.completed"
	WebhookEventTaskFailed     WebhookEvent = "task.failed"
	WebhookEventTaskCancelled  WebhookEvent = "task.cancelled"
	WebhookEventClientConnected    WebhookEvent = "client.connected"
	WebhookEventClientDisconnected WebhookEvent = "client.disconnected"
	WebhookEventWorkerIdle     WebhookEvent = "worker.idle"
	WebhookEventWorkerBusy     WebhookEvent = "worker.busy"
)

// Webhook represents a webhook subscription.
type Webhook struct {
	ID            string         `json:"id"`
	Name          string         `json:"name"`
	URL           string         `json:"url"`
	Secret        string         `json:"-"` // Not exposed in JSON
	Events        []WebhookEvent `json:"events"`
	Enabled       bool           `json:"enabled"`
	CreatedAt     time.Time      `json:"created_at"`
	UpdatedAt     time.Time      `json:"updated_at"`
	LastTriggered *time.Time     `json:"last_triggered,omitempty"`
	SuccessCount  int64          `json:"success_count"`
	FailureCount  int64          `json:"failure_count"`
}

// NewWebhook creates a new webhook.
func NewWebhook(name, url, secret string, events []WebhookEvent) *Webhook {
	now := time.Now().UTC()
	return &Webhook{
		ID:        uuid.New().String(),
		Name:      name,
		URL:       url,
		Secret:    secret,
		Events:    events,
		Enabled:   true,
		CreatedAt: now,
		UpdatedAt: now,
	}
}

// SubscribesToEvent returns true if the webhook subscribes to the given event.
func (w *Webhook) SubscribesToEvent(event WebhookEvent) bool {
	for _, e := range w.Events {
		if e == event {
			return true
		}
	}
	return false
}

// SignPayload signs a payload using the webhook's secret.
func (w *Webhook) SignPayload(payload []byte) string {
	if w.Secret == "" {
		return ""
	}
	h := hmac.New(sha256.New, []byte(w.Secret))
	h.Write(payload)
	return hex.EncodeToString(h.Sum(nil))
}

// RecordSuccess records a successful delivery.
func (w *Webhook) RecordSuccess() {
	now := time.Now()
	w.LastTriggered = &now
	w.SuccessCount++
	w.UpdatedAt = now
}

// RecordFailure records a failed delivery.
func (w *Webhook) RecordFailure() {
	now := time.Now()
	w.LastTriggered = &now
	w.FailureCount++
	w.UpdatedAt = now
}

// Enable enables the webhook.
func (w *Webhook) Enable() {
	w.Enabled = true
	w.UpdatedAt = time.Now()
}

// Disable disables the webhook.
func (w *Webhook) Disable() {
	w.Enabled = false
	w.UpdatedAt = time.Now()
}

// WebhookPayload represents the payload sent to webhooks.
type WebhookPayload struct {
	ID        string         `json:"id"`
	Event     WebhookEvent   `json:"event"`
	Timestamp time.Time      `json:"timestamp"`
	Data      map[string]any `json:"data"`
}

// NewWebhookPayload creates a new webhook payload.
func NewWebhookPayload(event WebhookEvent, data map[string]any) *WebhookPayload {
	return &WebhookPayload{
		ID:        uuid.New().String(),
		Event:     event,
		Timestamp: time.Now(),
		Data:      data,
	}
}
