package task

import (
	"testing"

	"github.com/tetra/core-hub/internal/domain/entity"
)

func TestResolveExecutorTaskType_WorkerLegacyFlatPayload(t *testing.T) {
	task := &entity.Task{
		TaskType:     entity.TaskTypeWorkerTask,
		ExecutorType: entity.ExecutorTypeWorker,
		Data: map[string]any{
			"action": "test_simple",
		},
	}

	got := resolveExecutorTaskType(task)
	if got != "test_simple" {
		t.Fatalf("resolveExecutorTaskType() = %q, want %q", got, "test_simple")
	}
}

func TestResolveExecutorTaskType_WorkerLegacyNestedPayload(t *testing.T) {
	task := &entity.Task{
		TaskType:     entity.TaskTypeWorkerTask,
		ExecutorType: entity.ExecutorTypeWorker,
		Data: map[string]any{
			"task_data": map[string]any{
				"action": "get_chat_settings",
			},
		},
	}

	got := resolveExecutorTaskType(task)
	if got != "get_chat_settings" {
		t.Fatalf("resolveExecutorTaskType() = %q, want %q", got, "get_chat_settings")
	}
}

func TestResolveExecutorTaskType_WorkerLegacyMissingActionFallback(t *testing.T) {
	task := &entity.Task{
		TaskType:     entity.TaskTypeWorkerTask,
		ExecutorType: entity.ExecutorTypeWorker,
		Data: map[string]any{
			"params": map[string]any{"k": "v"},
		},
	}

	got := resolveExecutorTaskType(task)
	if got != string(entity.TaskTypeWorkerTask) {
		t.Fatalf("resolveExecutorTaskType() = %q, want %q", got, entity.TaskTypeWorkerTask)
	}
}

func TestResolveExecutorTaskType_NonWorkerNoRewrite(t *testing.T) {
	task := &entity.Task{
		TaskType:     entity.TaskTypeWorkerTask,
		ExecutorType: entity.ExecutorTypeBot,
		Data: map[string]any{
			"action": "test_simple",
		},
	}

	got := resolveExecutorTaskType(task)
	if got != string(entity.TaskTypeWorkerTask) {
		t.Fatalf("resolveExecutorTaskType() = %q, want %q", got, entity.TaskTypeWorkerTask)
	}
}
