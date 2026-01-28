// Package entity defines domain entities for TetraCore Hub.
package entity

import (
	"time"

	"github.com/google/uuid"
)

// AuditAction represents types of auditable actions.
type AuditAction string

const (
	// Auth actions
	AuditActionLogin         AuditAction = "auth.login"
	AuditActionLoginFailed   AuditAction = "auth.login_failed"
	AuditActionLogout        AuditAction = "auth.logout"
	AuditActionTokenRefresh  AuditAction = "auth.token_refresh"
	AuditAction2FASetup      AuditAction = "auth.2fa_setup"
	AuditAction2FADisabled   AuditAction = "auth.2fa_disabled"

	// Task actions
	AuditActionTaskCreate    AuditAction = "task.create"
	AuditActionTaskStart     AuditAction = "task.start"
	AuditActionTaskComplete  AuditAction = "task.complete"
	AuditActionTaskFail      AuditAction = "task.fail"
	AuditActionTaskCancel    AuditAction = "task.cancel"

	// Client actions
	AuditActionClientConnect    AuditAction = "client.connect"
	AuditActionClientDisconnect AuditAction = "client.disconnect"
	AuditActionClientDelete     AuditAction = "client.delete"

	// Session actions
	AuditActionSessionCreate AuditAction = "session.create"
	AuditActionSessionDelete AuditAction = "session.delete"

	// Schedule actions
	AuditActionScheduleCreate  AuditAction = "schedule.create"
	AuditActionScheduleUpdate  AuditAction = "schedule.update"
	AuditActionScheduleDelete  AuditAction = "schedule.delete"
	AuditActionScheduleEnable  AuditAction = "schedule.enable"
	AuditActionScheduleDisable AuditAction = "schedule.disable"

	// Webhook actions
	AuditActionWebhookCreate  AuditAction = "webhook.create"
	AuditActionWebhookUpdate  AuditAction = "webhook.update"
	AuditActionWebhookDelete  AuditAction = "webhook.delete"
	AuditActionWebhookEnable  AuditAction = "webhook.enable"
	AuditActionWebhookDisable AuditAction = "webhook.disable"

	// Admin actions
	AuditActionSettingsUpdate AuditAction = "settings.update"
)

// AuditEntry represents an audit log entry.
type AuditEntry struct {
	ID         string         `json:"id"`
	Timestamp  time.Time      `json:"timestamp"`
	Action     AuditAction    `json:"action"`
	UserID     string         `json:"user_id,omitempty"`
	Username   string         `json:"username,omitempty"`
	ResourceID string         `json:"resource_id,omitempty"`
	Resource   string         `json:"resource,omitempty"`
	Details    map[string]any `json:"details,omitempty"`
	IPAddress  string         `json:"ip_address,omitempty"`
	UserAgent  string         `json:"user_agent,omitempty"`
	Success    bool           `json:"success"`
	Error      string         `json:"error,omitempty"`
}

// NewAuditEntry creates a new audit entry.
func NewAuditEntry(action AuditAction, userID, username string) *AuditEntry {
	return &AuditEntry{
		ID:        uuid.New().String(),
		Timestamp: time.Now(),
		Action:    action,
		UserID:    userID,
		Username:  username,
		Success:   true,
	}
}

// WithResource sets the resource being acted upon.
func (e *AuditEntry) WithResource(resourceType, resourceID string) *AuditEntry {
	e.Resource = resourceType
	e.ResourceID = resourceID
	return e
}

// WithDetails adds details to the audit entry.
func (e *AuditEntry) WithDetails(details map[string]any) *AuditEntry {
	e.Details = details
	return e
}

// WithRequest adds request info to the audit entry.
func (e *AuditEntry) WithRequest(ip, userAgent string) *AuditEntry {
	e.IPAddress = ip
	e.UserAgent = userAgent
	return e
}

// WithError marks the entry as failed with an error.
func (e *AuditEntry) WithError(err string) *AuditEntry {
	e.Success = false
	e.Error = err
	return e
}

// AuditFilter represents filters for querying audit logs.
type AuditFilter struct {
	UserID     string
	Action     AuditAction
	Resource   string
	ResourceID string
	StartTime  *time.Time
	EndTime    *time.Time
	Success    *bool
	Limit      int
	Offset     int
}
