// Package eventbus provides an in-memory event bus for TetraCore Hub.
package eventbus

import "time"

// EventType represents the type of an event.
type EventType string

// Event types for the hub.
const (
	// Task events
	EventTaskCreated   EventType = "task.created"
	EventTaskAssigned  EventType = "task.assigned"
	EventTaskStarted   EventType = "task.started"
	EventTaskCompleted EventType = "task.completed"
	EventTaskFailed    EventType = "task.failed"
	EventTaskCancelled EventType = "task.cancelled"
	EventTaskTimeout   EventType = "task.timeout"
	EventTaskRetry     EventType = "task.retry"
	EventTaskDLQ       EventType = "task.dlq"

	// Client events
	EventClientConnected    EventType = "client.connected"
	EventClientDisconnected EventType = "client.disconnected"
	EventClientHeartbeat    EventType = "client.heartbeat"

	// Worker events
	EventWorkerIdle EventType = "worker.idle"
	EventWorkerBusy EventType = "worker.busy"

	// Auth events
	EventAuthLogin       EventType = "auth.login"
	EventAuthLoginFailed EventType = "auth.login_failed"
	EventAuthLogout      EventType = "auth.logout"
	EventAuth2FASetup    EventType = "auth.2fa_setup"
	EventAuth2FADisabled EventType = "auth.2fa_disabled"

	// Schedule events
	EventScheduleCreated EventType = "schedule.created"
	EventScheduleRun     EventType = "schedule.run"
	EventScheduleDeleted EventType = "schedule.deleted"

	// Webhook events
	EventWebhookCreated   EventType = "webhook.created"
	EventWebhookTriggered EventType = "webhook.triggered"
	EventWebhookFailed    EventType = "webhook.failed"

	// System events
	EventSystemStartup  EventType = "system.startup"
	EventSystemShutdown EventType = "system.shutdown"
	EventConfigReloaded EventType = "config.reloaded"

	// Plugin events
	EventPluginLoaded   EventType = "plugin.loaded"
	EventPluginUnloaded EventType = "plugin.unloaded"
	EventPluginError    EventType = "plugin.error"
)

// Event represents an event in the system.
type Event struct {
	ID        string         `json:"id"`
	Type      EventType      `json:"type"`
	Source    string         `json:"source"`
	Payload   map[string]any `json:"payload"`
	Timestamp time.Time      `json:"timestamp"`
	Metadata  EventMetadata  `json:"metadata,omitempty"`
}

// EventMetadata contains additional event context.
type EventMetadata struct {
	UserID       string `json:"user_id,omitempty"`
	SessionID    string `json:"session_id,omitempty"`
	RequestID    string `json:"request_id,omitempty"`
	CorrelationID string `json:"correlation_id,omitempty"`
	IPAddress    string `json:"ip_address,omitempty"`
}

// EventHandler is a function that handles an event.
type EventHandler func(event Event)

// EventFilter filters events before they reach handlers.
type EventFilter func(event Event) bool

// Subscription represents an event subscription.
type Subscription struct {
	ID        string
	EventType EventType
	Handler   EventHandler
	Filter    EventFilter
}
