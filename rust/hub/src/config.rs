use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub environment: String,
    pub allowed_origins: String,
    pub ws_max_message_size: usize,
    pub ws_max_messages_per_second: usize,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            environment: std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".to_string()),
            allowed_origins: std::env::var("ALLOWED_ORIGINS").unwrap_or_default(),
            ws_max_message_size: std::env::var("WS_MAX_MESSAGE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(256*1024),
            ws_max_messages_per_second: std::env::var("WS_MAX_MESSAGES_PER_SECOND").ok().and_then(|v| v.parse().ok()).unwrap_or(10),
        }
    }
}

impl AppConfig {
    pub fn load() -> Self { Self::default() }
}


