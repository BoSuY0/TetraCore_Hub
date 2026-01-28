// Package entity defines core domain entities for TetraCore Hub.
package entity

import (
	"time"

	"github.com/google/uuid"
)

// ScheduleStatus represents the status of a schedule.
type ScheduleStatus string

const (
	ScheduleStatusActive   ScheduleStatus = "active"
	ScheduleStatusPaused   ScheduleStatus = "paused"
	ScheduleStatusDisabled ScheduleStatus = "disabled"
	ScheduleStatusExpired  ScheduleStatus = "expired"
)

// ScheduleFrequency represents the frequency of a schedule.
type ScheduleFrequency string

const (
	ScheduleFrequencyOnce     ScheduleFrequency = "once"
	ScheduleFrequencyMinutely ScheduleFrequency = "minutely"
	ScheduleFrequencyHourly   ScheduleFrequency = "hourly"
	ScheduleFrequencyDaily    ScheduleFrequency = "daily"
	ScheduleFrequencyWeekly   ScheduleFrequency = "weekly"
	ScheduleFrequencyMonthly  ScheduleFrequency = "monthly"
	ScheduleFrequencyCron     ScheduleFrequency = "cron"
)

// Schedule represents a scheduled task execution.
type Schedule struct {
	ID             string            `json:"id"`
	Name           string            `json:"name"`
	Description    string            `json:"description,omitempty"`
	TaskType       TaskType          `json:"task_type"`
	TaskData       map[string]any    `json:"task_data"`
	Priority       TaskPriority      `json:"priority"`
	ExecutorType   ExecutorType      `json:"executor_type"`
	Timeout        int               `json:"timeout"`
	MaxRetries     int               `json:"max_retries"`
	Frequency      ScheduleFrequency `json:"frequency"`
	CronExpression string            `json:"cron_expression,omitempty"`
	Interval       int               `json:"interval,omitempty"` // Interval in seconds for non-cron schedules
	Status         ScheduleStatus    `json:"status"`
	CreatedBy      string            `json:"created_by"`
	CreatedAt      time.Time         `json:"created_at"`
	UpdatedAt      time.Time         `json:"updated_at"`
	NextRunAt      *time.Time        `json:"next_run_at,omitempty"`
	LastRunAt      *time.Time        `json:"last_run_at,omitempty"`
	LastRunStatus  *TaskStatus       `json:"last_run_status,omitempty"`
	LastRunTaskID  string            `json:"last_run_task_id,omitempty"`
	RunCount       int               `json:"run_count"`
	SuccessCount   int               `json:"success_count"`
	FailureCount   int               `json:"failure_count"`
	MaxRuns        int               `json:"max_runs,omitempty"` // 0 = unlimited
	ExpiresAt      *time.Time        `json:"expires_at,omitempty"`
	Tags           []string          `json:"tags"`
	Metadata       map[string]any    `json:"metadata"`
}

// NewSchedule creates a new schedule.
func NewSchedule(name string, taskType TaskType, taskData map[string]any, createdBy string) *Schedule {
	now := time.Now().UTC()
	return &Schedule{
		ID:           uuid.New().String(),
		Name:         name,
		TaskType:     taskType,
		TaskData:     taskData,
		Priority:     TaskPriorityNormal,
		ExecutorType: ExecutorTypeWorker,
		Timeout:      300,
		MaxRetries:   3,
		Frequency:    ScheduleFrequencyOnce,
		Status:       ScheduleStatusActive,
		CreatedBy:    createdBy,
		CreatedAt:    now,
		UpdatedAt:    now,
		Tags:         []string{},
		Metadata:     make(map[string]any),
	}
}

// CreateTask creates a task from this schedule.
func (s *Schedule) CreateTask() *Task {
	task := CreateTask(
		s.TaskType,
		s.TaskData,
		WithPriority(s.Priority),
		WithExecutorType(s.ExecutorType),
		WithTimeout(s.Timeout),
		WithMaxRetries(s.MaxRetries),
	)
	task.Metadata.Source = "schedule"
	task.Metadata.CustomMetadata["schedule_id"] = s.ID
	task.Metadata.CustomMetadata["schedule_name"] = s.Name
	return task
}

// RecordRun records a schedule run.
func (s *Schedule) RecordRun(taskID string, status TaskStatus) {
	now := time.Now().UTC()
	s.LastRunAt = &now
	s.LastRunStatus = &status
	s.LastRunTaskID = taskID
	s.RunCount++
	s.UpdatedAt = now

	if status == TaskStatusCompleted {
		s.SuccessCount++
	} else if status == TaskStatusFailed || status == TaskStatusTimeout {
		s.FailureCount++
	}
}

// IsActive checks if the schedule is active.
func (s *Schedule) IsActive() bool {
	if s.Status != ScheduleStatusActive {
		return false
	}
	if s.ExpiresAt != nil && time.Now().UTC().After(*s.ExpiresAt) {
		return false
	}
	if s.MaxRuns > 0 && s.RunCount >= s.MaxRuns {
		return false
	}
	return true
}

// ShouldRun checks if the schedule should run now.
func (s *Schedule) ShouldRun() bool {
	if !s.IsActive() {
		return false
	}
	if s.NextRunAt == nil {
		return false
	}
	return time.Now().UTC().After(*s.NextRunAt)
}

// Pause pauses the schedule.
func (s *Schedule) Pause() {
	s.Status = ScheduleStatusPaused
	s.UpdatedAt = time.Now().UTC()
}

// Resume resumes the schedule.
func (s *Schedule) Resume() {
	s.Status = ScheduleStatusActive
	s.UpdatedAt = time.Now().UTC()
}

// Disable disables the schedule.
func (s *Schedule) Disable() {
	s.Status = ScheduleStatusDisabled
	s.UpdatedAt = time.Now().UTC()
}

// SetNextRun sets the next run time.
func (s *Schedule) SetNextRun(nextRun time.Time) {
	s.NextRunAt = &nextRun
	s.UpdatedAt = time.Now().UTC()
}

// CalculateNextRun calculates and sets the next run time based on frequency.
func (s *Schedule) CalculateNextRun() {
	now := time.Now().UTC()
	var nextRun time.Time

	switch s.Frequency {
	case ScheduleFrequencyOnce:
		// One-time schedules don't have a next run after execution
		s.NextRunAt = nil
		return
	case ScheduleFrequencyMinutely:
		interval := s.Interval
		if interval == 0 {
			interval = 60
		}
		nextRun = now.Add(time.Duration(interval) * time.Second)
	case ScheduleFrequencyHourly:
		interval := s.Interval
		if interval == 0 {
			interval = 3600
		}
		nextRun = now.Add(time.Duration(interval) * time.Second)
	case ScheduleFrequencyDaily:
		nextRun = now.Add(24 * time.Hour)
	case ScheduleFrequencyWeekly:
		nextRun = now.Add(7 * 24 * time.Hour)
	case ScheduleFrequencyMonthly:
		nextRun = now.AddDate(0, 1, 0)
	case ScheduleFrequencyCron:
		// Cron parsing requires external library, set to nil for now
		s.NextRunAt = nil
		return
	default:
		s.NextRunAt = nil
		return
	}

	s.NextRunAt = &nextRun
	s.UpdatedAt = now
}

// ToMap converts the schedule to a map.
func (s *Schedule) ToMap() map[string]any {
	var nextRunAt, lastRunAt, expiresAt, lastRunStatus *string
	if s.NextRunAt != nil {
		t := s.NextRunAt.Format(time.RFC3339)
		nextRunAt = &t
	}
	if s.LastRunAt != nil {
		t := s.LastRunAt.Format(time.RFC3339)
		lastRunAt = &t
	}
	if s.ExpiresAt != nil {
		t := s.ExpiresAt.Format(time.RFC3339)
		expiresAt = &t
	}
	if s.LastRunStatus != nil {
		t := string(*s.LastRunStatus)
		lastRunStatus = &t
	}

	return map[string]any{
		"id":              s.ID,
		"name":            s.Name,
		"description":     s.Description,
		"task_type":       string(s.TaskType),
		"priority":        string(s.Priority),
		"executor_type":   string(s.ExecutorType),
		"frequency":       string(s.Frequency),
		"cron_expression": s.CronExpression,
		"interval":        s.Interval,
		"status":          string(s.Status),
		"created_by":      s.CreatedBy,
		"created_at":      s.CreatedAt.Format(time.RFC3339),
		"updated_at":      s.UpdatedAt.Format(time.RFC3339),
		"next_run_at":     nextRunAt,
		"last_run_at":     lastRunAt,
		"last_run_status": lastRunStatus,
		"last_run_task_id": s.LastRunTaskID,
		"run_count":       s.RunCount,
		"success_count":   s.SuccessCount,
		"failure_count":   s.FailureCount,
		"max_runs":        s.MaxRuns,
		"expires_at":      expiresAt,
		"is_active":       s.IsActive(),
		"tags":            s.Tags,
		"metadata":        s.Metadata,
	}
}
