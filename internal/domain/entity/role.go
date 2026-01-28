// Package entity defines core domain entities for TetraCore Hub.
package entity

import "time"

// RoleID represents a role identifier.
type RoleID string

// Pre-defined roles
const (
	RoleAdmin    RoleID = "admin"    // Full access to everything
	RoleOperator RoleID = "operator" // Manage tasks, clients, schedules
	RoleViewer   RoleID = "viewer"   // Read-only access
)

// Role represents a user role with associated permissions.
type Role struct {
	ID          RoleID       `json:"id"`
	Name        string       `json:"name"`
	Description string       `json:"description"`
	Permissions []Permission `json:"permissions"`
	IsSystem    bool         `json:"is_system"` // System roles cannot be deleted
	CreatedAt   time.Time    `json:"created_at"`
	UpdatedAt   time.Time    `json:"updated_at"`
}

// NewRole creates a new Role.
func NewRole(id RoleID, name, description string, permissions []Permission) *Role {
	now := time.Now().UTC()
	return &Role{
		ID:          id,
		Name:        name,
		Description: description,
		Permissions: permissions,
		IsSystem:    false,
		CreatedAt:   now,
		UpdatedAt:   now,
	}
}

// HasPermission checks if the role has a specific permission.
func (r *Role) HasPermission(perm Permission) bool {
	ps := NewPermissionSet(r.Permissions)
	return ps.Has(perm)
}

// HasAnyPermission checks if the role has any of the given permissions.
func (r *Role) HasAnyPermission(perms ...Permission) bool {
	ps := NewPermissionSet(r.Permissions)
	return ps.HasAny(perms...)
}

// DefaultRoles returns the default system roles.
func DefaultRoles() []*Role {
	now := time.Now().UTC()
	return []*Role{
		{
			ID:          RoleAdmin,
			Name:        "Administrator",
			Description: "Full access to all system features",
			Permissions: []Permission{PermAll},
			IsSystem:    true,
			CreatedAt:   now,
			UpdatedAt:   now,
		},
		{
			ID:          RoleOperator,
			Name:        "Operator",
			Description: "Manage tasks, clients, schedules, and webhooks",
			Permissions: []Permission{
				// Tasks
				PermTasksRead, PermTasksWrite, PermTasksDelete, PermTasksExecute,
				// Clients
				PermClientsRead, PermClientsDisconnect,
				// Sessions (own)
				PermSessionsRead,
				// Schedules
				PermSchedulesRead, PermSchedulesWrite, PermSchedulesDelete,
				// Webhooks
				PermWebhooksRead, PermWebhooksWrite, PermWebhooksDelete,
				// Templates
				PermTemplatesRead, PermTemplatesWrite,
				// DLQ
				PermDLQRead, PermDLQWrite,
				// Audit (read only)
				PermAuditRead,
			},
			IsSystem:  true,
			CreatedAt: now,
			UpdatedAt: now,
		},
		{
			ID:          RoleViewer,
			Name:        "Viewer",
			Description: "Read-only access to system information",
			Permissions: []Permission{
				PermTasksRead,
				PermClientsRead,
				PermSessionsRead,
				PermSchedulesRead,
				PermWebhooksRead,
				PermTemplatesRead,
				PermDLQRead,
				PermAuditRead,
			},
			IsSystem:  true,
			CreatedAt: now,
			UpdatedAt: now,
		},
	}
}

// GetDefaultRole returns a default role by ID.
func GetDefaultRole(id RoleID) *Role {
	for _, role := range DefaultRoles() {
		if role.ID == id {
			return role
		}
	}
	return nil
}
