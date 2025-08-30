use dashmap::DashMap;
use serde_json::json;
use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::Mutex;

use models::task::{Task, TaskContext, TaskPriority, TaskStatus};

#[derive(Default)]
struct Queues {
    critical: VecDeque<Task>,
    high: VecDeque<Task>,
    normal: VecDeque<Task>,
    low: VecDeque<Task>,
}

impl Queues {
    fn push(&mut self, task: Task) {
        match task.priority {
            TaskPriority::Critical => self.critical.push_back(task),
            TaskPriority::High => self.high.push_back(task),
            TaskPriority::Normal => self.normal.push_back(task),
            TaskPriority::Low => self.low.push_back(task),
        }
    }

    fn pop_next(&mut self) -> Option<Task> {
        if let Some(t) = self.critical.pop_front() { return Some(t); }
        if let Some(t) = self.high.pop_front() { return Some(t); }
        if let Some(t) = self.normal.pop_front() { return Some(t); }
        if let Some(t) = self.low.pop_front() { return Some(t); }
        None
    }

    fn is_empty(&self) -> bool {
        self.critical.is_empty() && self.high.is_empty() && self.normal.is_empty() && self.low.is_empty()
    }
}

#[derive(Default)]
pub struct TaskRouter {
    queues: Mutex<Queues>,
    active_tasks: DashMap<String, Task>,
    history: DashMap<String, Task>,
    pub total_submitted: DashMap<&'static str, u64>,
}

impl TaskRouter {
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    pub async fn submit_task(&self, mut task: Task) -> serde_json::Value {
        if task.task_id.trim().is_empty() || task.task_type.trim().is_empty() {
            return json!({"type":"error","error":"invalid_task_payload"});
        }
        // Initialize context fields if needed
        if task.context.task_id.is_empty() {
            task.context = TaskContext::new(task.task_id.clone());
        }
        let mut q = self.queues.lock().await;
        q.push(task.clone());
        *self.total_submitted.entry("count").or_insert(0) += 1;
        json!({
            "type":"status_update",
            "task_id": task.task_id,
            "status": "queued"
        })
    }

    pub async fn assign_next(&self, executor_id: &str, accepted_types: Option<&[String]>) -> Option<Task> {
        let mut q = self.queues.lock().await;
        if q.is_empty() { return None; }
        // naive scan: pop_next until matches accepted_types
        let mut stash: Vec<Task> = Vec::new();
        let mut picked: Option<Task> = None;
        while let Some(mut t) = q.pop_next() {
            if let Some(types) = accepted_types {
                if !types.is_empty() && !types.iter().any(|tt| tt == &t.task_type) {
                    stash.push(t);
                    continue;
                }
            }
            t.context.assigned_at = Some(chrono::Utc::now().to_rfc3339());
            t.context.current_status = TaskStatus::Assigned;
            picked = Some(t.clone());
            self.active_tasks.insert(t.task_id.clone(), t);
            break;
        }
        // return stashed back to queues preserving order
        for t in stash.into_iter() {
            q.push(t);
        }
        picked
    }

    pub fn complete_task(&self, task_id: &str, status: TaskStatus, data: Option<serde_json::Value>) -> serde_json::Value {
        let mut task = if let Some((_k, v)) = self.active_tasks.remove(task_id) {
            v
        } else {
            // task may still be queued; mark minimal status record
            Task {
                task_id: task_id.to_string(),
                task_type: "".to_string(),
                data: data.unwrap_or_else(|| json!({})),
                priority: TaskPriority::Normal,
                timeout: 300,
                max_retries: 3,
                retry_delay: 5,
                executor_type: models::task::ExecutorType::Worker,
                worker_requirements: Vec::new(),
                metadata: models::task::TaskMetadata::new(),
                correlation_id: None,
                context: TaskContext::new(task_id.to_string()),
            }
        };
        task.context.completed_at = Some(chrono::Utc::now().to_rfc3339());
        task.context.current_status = status.clone();
        self.history.insert(task_id.to_string(), task);
        json!({"type":"task_status","task_id":task_id,"status":format!("{}", to_snake_status(&status))})
    }

    pub fn get_stats_json(&self) -> serde_json::Value {
        let active = self.active_tasks.len();
        let history = self.history.len();
        json!({
            "active": active,
            "history": history,
            "timestamp": chrono::Utc::now().to_rfc3339(),
        })
    }

    pub async fn list_tasks_json(&self) -> serde_json::Value {
        let q = self.queues.lock().await;
        let queued = q.critical.len() + q.high.len() + q.normal.len() + q.low.len();
        let active = self.active_tasks.len();
        let history = self.history.len();
        json!({
            "queued": queued,
            "active": active,
            "history": history,
        })
    }
}

fn to_snake_status(status: &TaskStatus) -> &'static str {
    match status {
        TaskStatus::Pending => "pending",
        TaskStatus::Assigned => "assigned",
        TaskStatus::Processing => "processing",
        TaskStatus::Completed => "completed",
        TaskStatus::Failed => "failed",
        TaskStatus::Timeout => "timeout",
        TaskStatus::Retry => "retry",
        TaskStatus::Cancelled => "cancelled",
    }
}

pub fn parse_priority(num: Option<u32>) -> TaskPriority {
    match num.unwrap_or(2) {
        1 => TaskPriority::Low,
        2 => TaskPriority::Normal,
        3 => TaskPriority::High,
        4 => TaskPriority::Critical,
        _ => TaskPriority::Normal,
    }
}

