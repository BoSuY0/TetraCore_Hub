use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskPriority {
    Low,
    Normal,
    High,
    Critical,
}

impl Default for TaskPriority {
    fn default() -> Self { TaskPriority::Normal }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    Assigned,
    Processing,
    Completed,
    Failed,
    Timeout,
    Retry,
    Cancelled,
}

impl Default for TaskStatus {
    fn default() -> Self { TaskStatus::Pending }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ExecutorType {
    Bot,
    Worker,
    WorkerApi,
}

impl Default for ExecutorType {
    fn default() -> Self { ExecutorType::Worker }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TaskMetadata {
    pub source: String,
    pub version: String,
    pub tags: std::collections::HashSet<String>,
    pub group: Option<String>,
    pub parent_task_id: Option<String>,
    pub child_task_ids: Vec<String>,
    pub dependencies: Vec<String>,
    pub created_by: Option<String>,
    pub custom_metadata: serde_json::Value,
    pub is_critical: bool,
    pub is_retryable: bool,
    pub is_cancellable: bool,
    pub idempotency_key: Option<String>,
    pub execution_settings: serde_json::Value,
}

impl TaskMetadata {
    pub fn new() -> Self {
        Self {
            source: "unknown".to_string(),
            version: "1.0.0".to_string(),
            tags: std::collections::HashSet::new(),
            group: None,
            parent_task_id: None,
            child_task_ids: Vec::new(),
            dependencies: Vec::new(),
            created_by: None,
            custom_metadata: serde_json::json!({}),
            is_critical: false,
            is_retryable: true,
            is_cancellable: true,
            idempotency_key: None,
            execution_settings: serde_json::json!({}),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskContext {
    pub task_id: String,
    pub worker_id: Option<String>,
    pub client_id: Option<String>,
    pub correlation_id: Option<String>,
    pub created_at: String,
    pub assigned_at: Option<String>,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub expires_at: Option<String>,
    pub current_status: TaskStatus,
    pub current_attempt: u32,
}

impl TaskContext {
    pub fn new(task_id: String) -> Self {
        Self {
            task_id,
            worker_id: None,
            client_id: None,
            correlation_id: None,
            created_at: chrono::Utc::now().to_rfc3339(),
            assigned_at: None,
            started_at: None,
            completed_at: None,
            expires_at: None,
            current_status: TaskStatus::Pending,
            current_attempt: 1,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub task_id: String,
    pub task_type: String,
    #[serde(default)] pub data: serde_json::Value,
    #[serde(default)] pub priority: TaskPriority,
    #[serde(default = "Task::default_timeout")] pub timeout: u64,
    #[serde(default = "Task::default_max_retries")] pub max_retries: u32,
    #[serde(default = "Task::default_retry_delay")] pub retry_delay: u64,
    #[serde(default)] pub executor_type: ExecutorType,
    #[serde(default)] pub worker_requirements: Vec<String>,
    #[serde(default = "TaskMetadata::new")] pub metadata: TaskMetadata,
    #[serde(default, skip_serializing_if = "Option::is_none")] pub correlation_id: Option<String>,
    #[serde(default = "Task::default_context")] pub context: TaskContext,
}

impl Task {
    pub fn create(task_id: String, task_type: String, data: serde_json::Value) -> Self {
        let context = TaskContext::new(task_id.clone());
        Self {
            task_id,
            task_type,
            data,
            priority: TaskPriority::Normal,
            timeout: Self::default_timeout(),
            max_retries: Self::default_max_retries(),
            retry_delay: Self::default_retry_delay(),
            executor_type: ExecutorType::Worker,
            worker_requirements: Vec::new(),
            metadata: TaskMetadata::new(),
            correlation_id: None,
            context,
        }
    }

    fn default_timeout() -> u64 { 300 }
    fn default_max_retries() -> u32 { 3 }
    fn default_retry_delay() -> u64 { 5 }
    fn default_context() -> TaskContext { TaskContext::new("".to_string()) }
}


