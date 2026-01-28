// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"time"
)

// TimeoutAction defines what happens when a task times out.
type TimeoutAction string

const (
	TimeoutActionRetry  TimeoutAction = "retry"   // Retry the task
	TimeoutActionDLQ    TimeoutAction = "dlq"     // Move to dead letter queue
	TimeoutActionCancel TimeoutAction = "cancel"  // Cancel the task
	TimeoutActionFail   TimeoutAction = "fail"    // Mark as failed
)

// TimeoutPolicy defines timeout behavior for tasks.
type TimeoutPolicy struct {
	ID                string                        `json:"id"`
	Name              string                        `json:"name"`
	Description       string                        `json:"description,omitempty"`
	DefaultTimeout    time.Duration                 `json:"default_timeout"`
	MaxTimeout        time.Duration                 `json:"max_timeout"`
	TimeoutByType     map[TaskType]time.Duration    `json:"timeout_by_type,omitempty"`
	TimeoutByPriority map[TaskPriority]time.Duration `json:"timeout_by_priority,omitempty"`
	GracePeriod       time.Duration                 `json:"grace_period"`   // Extra time for cleanup
	OnTimeout         TimeoutAction                 `json:"on_timeout"`     // What to do on timeout
	MaxRetries        int                           `json:"max_retries"`    // Retries before giving up
	CreatedAt         time.Time                     `json:"created_at"`
	UpdatedAt         time.Time                     `json:"updated_at"`
}

// NewTimeoutPolicy creates a new TimeoutPolicy with sensible defaults.
func NewTimeoutPolicy(name string, defaultTimeout time.Duration) *TimeoutPolicy {
	now := time.Now().UTC()
	return &TimeoutPolicy{
		ID:                GenerateID(),
		Name:              name,
		DefaultTimeout:    defaultTimeout,
		MaxTimeout:        defaultTimeout * 2,
		TimeoutByType:     make(map[TaskType]time.Duration),
		TimeoutByPriority: make(map[TaskPriority]time.Duration),
		GracePeriod:       30 * time.Second,
		OnTimeout:         TimeoutActionRetry,
		MaxRetries:        3,
		CreatedAt:         now,
		UpdatedAt:         now,
	}
}

// DefaultTimeoutPolicy returns a default timeout policy.
func DefaultTimeoutPolicy() *TimeoutPolicy {
	policy := NewTimeoutPolicy("default", 5*time.Minute)
	policy.TimeoutByPriority = map[TaskPriority]time.Duration{
		TaskPriorityLow:      10 * time.Minute,
		TaskPriorityNormal:   5 * time.Minute,
		TaskPriorityHigh:     3 * time.Minute,
		TaskPriorityCritical: 1 * time.Minute,
	}
	return policy
}

// GetTimeoutForTask returns the appropriate timeout for a task.
func (p *TimeoutPolicy) GetTimeoutForTask(task *Task) time.Duration {
	// Check task type specific timeout
	if timeout, ok := p.TimeoutByType[task.TaskType]; ok {
		return p.clampTimeout(timeout)
	}

	// Check priority specific timeout
	if timeout, ok := p.TimeoutByPriority[task.Priority]; ok {
		return p.clampTimeout(timeout)
	}

	// Return default
	return p.clampTimeout(p.DefaultTimeout)
}

// clampTimeout ensures timeout is within bounds.
func (p *TimeoutPolicy) clampTimeout(timeout time.Duration) time.Duration {
	if timeout < time.Second {
		timeout = time.Second
	}
	if p.MaxTimeout > 0 && timeout > p.MaxTimeout {
		timeout = p.MaxTimeout
	}
	return timeout
}

// GetTotalTimeout returns timeout plus grace period.
func (p *TimeoutPolicy) GetTotalTimeout(task *Task) time.Duration {
	return p.GetTimeoutForTask(task) + p.GracePeriod
}

// ShouldRetry determines if a task should be retried after timeout.
func (p *TimeoutPolicy) ShouldRetry(task *Task, currentAttempt int) bool {
	if p.OnTimeout != TimeoutActionRetry {
		return false
	}
	return currentAttempt < p.MaxRetries
}

// SetTypeTimeout sets a specific timeout for a task type.
func (p *TimeoutPolicy) SetTypeTimeout(taskType TaskType, timeout time.Duration) {
	p.TimeoutByType[taskType] = timeout
	p.UpdatedAt = time.Now().UTC()
}

// SetPriorityTimeout sets a specific timeout for a priority level.
func (p *TimeoutPolicy) SetPriorityTimeout(priority TaskPriority, timeout time.Duration) {
	p.TimeoutByPriority[priority] = timeout
	p.UpdatedAt = time.Now().UTC()
}
