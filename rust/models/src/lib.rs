use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WsMessage {
    Ping,
    Pong,
    Subscribe { channel: String },
    Unsubscribe { channel: String },
    TaskSubmit {
        task_id: String,
        task_type: String,
        #[serde(default)] task_data: serde_json::Value,
        #[serde(default)] priority: Option<u32>,
        #[serde(default)] timeout: Option<u64>,
        #[serde(default)] max_retries: Option<u32>,
    },
    TaskResult {
        task_id: String,
        status: String,
        #[serde(default)] data: Option<serde_json::Value>,
    },
    Broadcast { channel: String, #[serde(default)] payload: serde_json::Value },
    ClientRegistration {
        client_id: String,
        client_type: String,
        client_name: String,
        client_version: String,
        #[serde(default)] capabilities: Option<Vec<String>>,
        #[serde(default)] max_concurrent_tasks: Option<u32>,
    },
    Error { error: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WsEnvelope<T = WsMessage> {
    pub timestamp: Option<String>,
    pub message_id: Option<String>,
    pub correlation_id: Option<String>,
    #[serde(flatten)]
    pub payload: T,
}
