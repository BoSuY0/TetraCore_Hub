// Package entity defines core domain entities for TetraCore Hub.
package entity

// Permission represents a specific action that can be performed on a resource.
type Permission string

// Resource types
const (
	ResourceUsers     = "users"
	ResourceRoles     = "roles"
	ResourceTasks     = "tasks"
	ResourceClients   = "clients"
	ResourceSessions  = "sessions"
	ResourceSchedules = "schedules"
	ResourceWebhooks  = "webhooks"
	ResourceAudit     = "audit"
	ResourceSettings  = "settings"
	ResourceAPIKeys   = "apikeys"
	ResourceSecrets   = "secrets"
	ResourceTemplates = "templates"
	ResourceDLQ       = "dlq"
	ResourcePlugins   = "plugins"
)

// Actions
const (
	ActionRead    = "read"
	ActionWrite   = "write"
	ActionDelete  = "delete"
	ActionExecute = "execute"
	ActionManage  = "manage" // Full control
)

// Pre-defined permissions (resource:action format)
const (
	// User permissions
	PermUsersRead   Permission = "users:read"
	PermUsersWrite  Permission = "users:write"
	PermUsersDelete Permission = "users:delete"
	PermUsersManage Permission = "users:manage"

	// Role permissions
	PermRolesRead   Permission = "roles:read"
	PermRolesWrite  Permission = "roles:write"
	PermRolesDelete Permission = "roles:delete"
	PermRolesManage Permission = "roles:manage"

	// Task permissions
	PermTasksRead    Permission = "tasks:read"
	PermTasksWrite   Permission = "tasks:write"
	PermTasksDelete  Permission = "tasks:delete"
	PermTasksExecute Permission = "tasks:execute"
	PermTasksManage  Permission = "tasks:manage"

	// Client permissions
	PermClientsRead       Permission = "clients:read"
	PermClientsWrite      Permission = "clients:write"
	PermClientsDelete     Permission = "clients:delete"
	PermClientsDisconnect Permission = "clients:disconnect"
	PermClientsManage     Permission = "clients:manage"

	// Session permissions
	PermSessionsRead   Permission = "sessions:read"
	PermSessionsDelete Permission = "sessions:delete"
	PermSessionsManage Permission = "sessions:manage"

	// Schedule permissions
	PermSchedulesRead   Permission = "schedules:read"
	PermSchedulesWrite  Permission = "schedules:write"
	PermSchedulesDelete Permission = "schedules:delete"
	PermSchedulesManage Permission = "schedules:manage"

	// Webhook permissions
	PermWebhooksRead   Permission = "webhooks:read"
	PermWebhooksWrite  Permission = "webhooks:write"
	PermWebhooksDelete Permission = "webhooks:delete"
	PermWebhooksManage Permission = "webhooks:manage"

	// Audit permissions
	PermAuditRead Permission = "audit:read"

	// Settings permissions
	PermSettingsRead  Permission = "settings:read"
	PermSettingsWrite Permission = "settings:write"

	// API Key permissions
	PermAPIKeysRead   Permission = "apikeys:read"
	PermAPIKeysWrite  Permission = "apikeys:write"
	PermAPIKeysDelete Permission = "apikeys:delete"
	PermAPIKeysManage Permission = "apikeys:manage"

	// Secrets permissions
	PermSecretsRead   Permission = "secrets:read"
	PermSecretsWrite  Permission = "secrets:write"
	PermSecretsDelete Permission = "secrets:delete"
	PermSecretsManage Permission = "secrets:manage"

	// Template permissions
	PermTemplatesRead   Permission = "templates:read"
	PermTemplatesWrite  Permission = "templates:write"
	PermTemplatesDelete Permission = "templates:delete"
	PermTemplatesManage Permission = "templates:manage"

	// DLQ permissions
	PermDLQRead   Permission = "dlq:read"
	PermDLQWrite  Permission = "dlq:write"
	PermDLQDelete Permission = "dlq:delete"
	PermDLQManage Permission = "dlq:manage"

	// Plugin permissions
	PermPluginsRead   Permission = "plugins:read"
	PermPluginsWrite  Permission = "plugins:write"
	PermPluginsManage Permission = "plugins:manage"

	// Wildcard permission
	PermAll Permission = "*:*"
)

// AllPermissions returns all available permissions.
func AllPermissions() []Permission {
	return []Permission{
		PermUsersRead, PermUsersWrite, PermUsersDelete, PermUsersManage,
		PermRolesRead, PermRolesWrite, PermRolesDelete, PermRolesManage,
		PermTasksRead, PermTasksWrite, PermTasksDelete, PermTasksExecute, PermTasksManage,
		PermClientsRead, PermClientsWrite, PermClientsDelete, PermClientsDisconnect, PermClientsManage,
		PermSessionsRead, PermSessionsDelete, PermSessionsManage,
		PermSchedulesRead, PermSchedulesWrite, PermSchedulesDelete, PermSchedulesManage,
		PermWebhooksRead, PermWebhooksWrite, PermWebhooksDelete, PermWebhooksManage,
		PermAuditRead,
		PermSettingsRead, PermSettingsWrite,
		PermAPIKeysRead, PermAPIKeysWrite, PermAPIKeysDelete, PermAPIKeysManage,
		PermSecretsRead, PermSecretsWrite, PermSecretsDelete, PermSecretsManage,
		PermTemplatesRead, PermTemplatesWrite, PermTemplatesDelete, PermTemplatesManage,
		PermDLQRead, PermDLQWrite, PermDLQDelete, PermDLQManage,
		PermPluginsRead, PermPluginsWrite, PermPluginsManage,
	}
}

// PermissionSet provides efficient permission checking.
type PermissionSet map[Permission]struct{}

// NewPermissionSet creates a new PermissionSet from permissions.
func NewPermissionSet(perms []Permission) PermissionSet {
	ps := make(PermissionSet, len(perms))
	for _, p := range perms {
		ps[p] = struct{}{}
	}
	return ps
}

// Has checks if the permission set contains the given permission.
func (ps PermissionSet) Has(perm Permission) bool {
	// Check for wildcard
	if _, ok := ps[PermAll]; ok {
		return true
	}
	_, ok := ps[perm]
	return ok
}

// HasAny checks if the permission set contains any of the given permissions.
func (ps PermissionSet) HasAny(perms ...Permission) bool {
	for _, p := range perms {
		if ps.Has(p) {
			return true
		}
	}
	return false
}

// HasAll checks if the permission set contains all of the given permissions.
func (ps PermissionSet) HasAll(perms ...Permission) bool {
	for _, p := range perms {
		if !ps.Has(p) {
			return false
		}
	}
	return true
}

// ToSlice converts the permission set to a slice.
func (ps PermissionSet) ToSlice() []Permission {
	perms := make([]Permission, 0, len(ps))
	for p := range ps {
		perms = append(perms, p)
	}
	return perms
}
