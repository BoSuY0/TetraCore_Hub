use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ClientType {
    Bot,
    Worker,
    WorkerApi,
    StreamHub,
    Monitor,
    Admin,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum WorkerStatus {
    Idle,
    Busy,
    Overloaded,
    Maintenance,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerCapabilities {
    #[serde(default)]
    pub supported_task_types: Vec<String>,
    #[serde(default = "WorkerCapabilities::default_max_concurrent_tasks")]
    pub max_concurrent_tasks: u32,
    #[serde(default)]
    pub average_processing_time: f64,
    #[serde(default = "WorkerCapabilities::default_max_task_size")]
    pub max_task_size: u64,
    #[serde(default = "WorkerCapabilities::default_supported_formats")]
    pub supported_formats: Vec<String>,
    #[serde(default)]
    pub special_capabilities: Vec<String>,
    #[serde(default = "WorkerCapabilities::default_api_version")]
    pub api_version: String,
    #[serde(default = "WorkerCapabilities::default_min_priority")]
    pub min_priority: String,
    #[serde(default = "WorkerCapabilities::default_max_priority")]
    pub max_priority: String,
}

impl WorkerCapabilities {
    fn default_max_concurrent_tasks() -> u32 { 1 }
    fn default_max_task_size() -> u64 { 1024 * 1024 }
    fn default_supported_formats() -> Vec<String> { vec!["json".to_string()] }
    fn default_api_version() -> String { "1.0.0".to_string() }
    fn default_min_priority() -> String { "low".to_string() }
    fn default_max_priority() -> String { "critical".to_string() }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ClientStats {
    #[serde(default)]
    pub total_tasks: i64,
    #[serde(default)]
    pub successful_tasks: i64,
    #[serde(default)]
    pub failed_tasks: i64,
    #[serde(default)]
    pub timeout_tasks: i64,
    #[serde(default)]
    pub active_tasks: i64,
    #[serde(default)]
    pub average_processing_time: f64,
    #[serde(default = "ClientStats::now_iso")]
    pub last_activity: String,
    #[serde(default = "ClientStats::now_iso")]
    pub connected_at: String,
    #[serde(default)]
    pub total_connection_time: f64,
    #[serde(default)]
    pub disconnection_count: i64,
    #[serde(default)]
    pub error_stats: HashMap<String, i64>,
    #[serde(default)]
    pub resource_usage: HashMap<String, f64>,
}

impl ClientStats {
    fn now_iso() -> String { chrono::Utc::now().to_rfc3339() }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClientInfo {
    pub client_id: String,
    pub client_type: ClientType,
    #[serde(default = "ClientInfo::default_client_name")] pub client_name: String,
    #[serde(default = "ClientInfo::default_client_version")] pub client_version: String,

    #[serde(default)]
    pub connection_status: String,
    #[serde(default)]
    pub session_id: Option<String>,

    #[serde(default)]
    pub remote_address: Option<String>,
    #[serde(default)]
    pub user_agent: Option<String>,

    #[serde(default = "ClientInfo::now_iso")] pub registered_at: String,
    #[serde(default)] pub last_ping: Option<String>,
    #[serde(default)] pub last_pong: Option<String>,

    #[serde(default)] pub capabilities: Option<WorkerCapabilities>,
    #[serde(default)] pub worker_status: Option<WorkerStatus>,

    #[serde(default)] pub current_load: i64,
    #[serde(default)] pub stats: ClientStats,

    #[serde(default)] pub config: HashMap<String, serde_json::Value>,
    #[serde(default)] pub metadata: HashMap<String, serde_json::Value>,
    #[serde(default)] pub tags: HashSet<String>,
}

impl ClientInfo {
    fn default_client_name() -> String { "unknown".to_string() }
    fn default_client_version() -> String { "1.0.0".to_string() }
    fn now_iso() -> String { chrono::Utc::now().to_rfc3339() }
}
