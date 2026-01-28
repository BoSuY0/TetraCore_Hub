// Package tetraclient provides a Go SDK for TetraCore Hub API.
package tetraclient

import (
	"context"
	"net/url"
	"strconv"
)

// TaskService provides task operations.
type TaskService struct {
	client *Client
}

// List lists tasks with optional filters.
func (s *TaskService) List(ctx context.Context, limit, offset int, status, taskType string) (*TaskList, error) {
	path := "/api/v1/tasks"
	params := url.Values{}
	if limit > 0 {
		params.Set("limit", strconv.Itoa(limit))
	}
	if offset > 0 {
		params.Set("offset", strconv.Itoa(offset))
	}
	if status != "" {
		params.Set("status", status)
	}
	if taskType != "" {
		params.Set("type", taskType)
	}
	if len(params) > 0 {
		path += "?" + params.Encode()
	}

	var result TaskList
	err := s.client.doRequest(ctx, "GET", path, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Get retrieves a task by ID.
func (s *TaskService) Get(ctx context.Context, id string) (*Task, error) {
	var result Task
	err := s.client.doRequest(ctx, "GET", "/api/v1/tasks/"+id, nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Submit submits a new task.
func (s *TaskService) Submit(ctx context.Context, input SubmitTaskInput) (*TaskSubmitResponse, error) {
	var result TaskSubmitResponse
	err := s.client.doRequest(ctx, "POST", "/api/v1/tasks", input, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Cancel cancels a task.
func (s *TaskService) Cancel(ctx context.Context, id, reason string) error {
	path := "/api/v1/tasks/" + id + "/cancel"
	if reason != "" {
		path += "?reason=" + url.QueryEscape(reason)
	}
	return s.client.doRequest(ctx, "POST", path, nil, nil)
}

// Retry retries a failed task.
func (s *TaskService) Retry(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "POST", "/api/v1/tasks/"+id+"/retry", nil, nil)
}

// Delete deletes a task.
func (s *TaskService) Delete(ctx context.Context, id string) error {
	return s.client.doRequest(ctx, "DELETE", "/api/v1/tasks/"+id, nil, nil)
}

// GetStats retrieves task statistics.
func (s *TaskService) GetStats(ctx context.Context) (*TaskStats, error) {
	var result TaskStats
	err := s.client.doRequest(ctx, "GET", "/api/v1/tasks/stats", nil, &result)
	if err != nil {
		return nil, err
	}
	return &result, nil
}

// Task represents a task.
type Task struct {
	TaskID        string         `json:"task_id"`
	TaskType      string         `json:"task_type"`
	Status        string         `json:"status"`
	Priority      string         `json:"priority"`
	ExecutorType  string         `json:"executor_type"`
	WorkerID      string         `json:"worker_id,omitempty"`
	ClientID      string         `json:"client_id,omitempty"`
	CreatedAt     string         `json:"created_at"`
	StartedAt     string         `json:"started_at,omitempty"`
	CompletedAt   string         `json:"completed_at,omitempty"`
	ExecutionTime *float64       `json:"execution_time_ms,omitempty"`
	Timeout       int            `json:"timeout"`
	MaxRetries    int            `json:"max_retries"`
	Attempt       int            `json:"attempt"`
	CanRetry      bool           `json:"can_retry"`
	IsExpired     bool           `json:"is_expired"`
	Data          map[string]any `json:"data,omitempty"`
	Result        map[string]any `json:"result,omitempty"`
}

// TaskList represents a list of tasks.
type TaskList struct {
	Tasks []Task `json:"tasks"`
	Total int    `json:"total"`
}

// SubmitTaskInput represents input for submitting a task.
type SubmitTaskInput struct {
	TaskType           string         `json:"task_type"`
	Data               map[string]any `json:"data"`
	Priority           string         `json:"priority,omitempty"`
	ExecutorType       string         `json:"executor_type,omitempty"`
	Timeout            int            `json:"timeout,omitempty"`
	MaxRetries         int            `json:"max_retries,omitempty"`
	WorkerRequirements []string       `json:"worker_requirements,omitempty"`
	IdempotencyKey     string         `json:"idempotency_key,omitempty"`
}

// TaskSubmitResponse represents the response from task submission.
type TaskSubmitResponse struct {
	TaskID  string `json:"task_id"`
	Status  string `json:"status"`
	Message string `json:"message"`
}

// TaskStats represents task statistics.
type TaskStats struct {
	TotalTasks        int64            `json:"total_tasks"`
	PendingTasks      int64            `json:"pending_tasks"`
	ProcessingTasks   int64            `json:"processing_tasks"`
	CompletedTasks    int64            `json:"completed_tasks"`
	FailedTasks       int64            `json:"failed_tasks"`
	TimeoutTasks      int64            `json:"timeout_tasks"`
	TasksByType       map[string]int64 `json:"tasks_by_type"`
	TasksByPriority   map[string]int64 `json:"tasks_by_priority"`
	AverageProcessing float64          `json:"average_processing_ms"`
	OldestPendingAge  float64          `json:"oldest_pending_age_seconds"`
}
