// Package plugins provides a Lua-based plugin system for TetraCore Hub.
package plugins

import "github.com/tetra/core-hub/internal/domain/entity"

// HookType represents a plugin hook type.
type HookType string

// Available hook types
const (
	HookBeforeTaskCreate   HookType = "before_task_create"
	HookAfterTaskCreate    HookType = "after_task_create"
	HookBeforeTaskAssign   HookType = "before_task_assign"
	HookAfterTaskAssign    HookType = "after_task_assign"
	HookBeforeTaskStart    HookType = "before_task_start"
	HookAfterTaskComplete  HookType = "after_task_complete"
	HookAfterTaskFail      HookType = "after_task_fail"
	HookAfterTaskTimeout   HookType = "after_task_timeout"
	HookOnClientConnect    HookType = "on_client_connect"
	HookOnClientDisconnect HookType = "on_client_disconnect"
	HookOnScheduleRun      HookType = "on_schedule_run"
	HookOnWebhookTrigger   HookType = "on_webhook_trigger"
	HookOnAuthLogin        HookType = "on_auth_login"
	HookOnAuthLogout       HookType = "on_auth_logout"
)

// AllHooks returns all available hook types.
func AllHooks() []HookType {
	return []HookType{
		HookBeforeTaskCreate,
		HookAfterTaskCreate,
		HookBeforeTaskAssign,
		HookAfterTaskAssign,
		HookBeforeTaskStart,
		HookAfterTaskComplete,
		HookAfterTaskFail,
		HookAfterTaskTimeout,
		HookOnClientConnect,
		HookOnClientDisconnect,
		HookOnScheduleRun,
		HookOnWebhookTrigger,
		HookOnAuthLogin,
		HookOnAuthLogout,
	}
}

// HookContext provides context for hook execution.
type HookContext struct {
	HookType HookType       `json:"hook_type"`
	Data     map[string]any `json:"data"`
	Task     *entity.Task   `json:"task,omitempty"`
	UserID   string         `json:"user_id,omitempty"`
	ClientID string         `json:"client_id,omitempty"`
}

// HookResult represents the result of a hook execution.
type HookResult struct {
	Modified bool           `json:"modified"`
	Data     map[string]any `json:"data,omitempty"`
	Error    string         `json:"error,omitempty"`
	Abort    bool           `json:"abort"` // Abort the operation
}

// NewHookContext creates a new HookContext.
func NewHookContext(hookType HookType) *HookContext {
	return &HookContext{
		HookType: hookType,
		Data:     make(map[string]any),
	}
}

// WithTask adds a task to the context.
func (c *HookContext) WithTask(task *entity.Task) *HookContext {
	c.Task = task
	return c
}

// WithData adds data to the context.
func (c *HookContext) WithData(key string, value any) *HookContext {
	c.Data[key] = value
	return c
}

// WithUserID adds a user ID to the context.
func (c *HookContext) WithUserID(userID string) *HookContext {
	c.UserID = userID
	return c
}

// WithClientID adds a client ID to the context.
func (c *HookContext) WithClientID(clientID string) *HookContext {
	c.ClientID = clientID
	return c
}
