use serde::{Deserialize, Serialize};
use dashmap::{DashMap, DashSet};
use std::{collections::VecDeque, time::{SystemTime, UNIX_EPOCH}};
use tokio::sync::mpsc::{Sender as BoundedSender};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use jsonwebtoken as jwt;
use models::WsEnvelope;
use http::HeaderMap;
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthResult {
    pub user_id: String,
    pub username: String,
    pub role: String,
    pub permissions: Vec<String>,
    pub session_id: String,
}

#[derive(Debug, Default)]
pub struct WebSocketSecurityManager {
    pub connections: DashMap<String, ConnectionInfo>,
    pub user_connections: DashMap<String, DashSet<String>>,
    pub rate_limiters: DashMap<String, VecDeque<f64>>,
    pub used_nonces: DashMap<String, f64>,
    pub conn_attempts_ip: DashMap<String, VecDeque<f64>>,
    pub conn_attempts_tok: DashMap<String, VecDeque<f64>>,
    pub conn_window_seconds: u64,
    pub conn_max_per_window: usize,
    pub nonce_ttl_seconds: u64,
    pub senders: DashMap<String, BoundedSender<String>>,
    pub max_connections_per_user: usize,
    pub max_subscriptions_per_client: usize,
    pub tasks: DashMap<String, TaskRecord>,
    pub metrics: DashMap<String, u64>,
}

#[derive(Debug)]
pub enum ValidationOutcome {
    Ok(WsEnvelope),
    TooLarge,
    RateLimited,
    Invalid,
}

impl WebSocketSecurityManager {
    pub fn new() -> Self {
        Self {
            connections: DashMap::new(),
            user_connections: DashMap::new(),
            rate_limiters: DashMap::new(),
            used_nonces: DashMap::new(),
            conn_attempts_ip: DashMap::new(),
            conn_attempts_tok: DashMap::new(),
            conn_window_seconds: std::env::var("WS_CONN_WINDOW_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(60),
            conn_max_per_window: std::env::var("WS_MAX_CONN_ATTEMPTS_PER_MIN").ok().and_then(|v| v.parse().ok()).unwrap_or(20),
            nonce_ttl_seconds: std::env::var("WS_NONCE_TTL_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(120),
            senders: DashMap::new(),
            max_connections_per_user: std::env::var("WS_MAX_CONNECTIONS_PER_USER").ok().and_then(|v| v.parse().ok()).unwrap_or(20),
            max_subscriptions_per_client: std::env::var("WS_MAX_SUBSCRIPTIONS").ok().and_then(|v| v.parse().ok()).unwrap_or(50),
            tasks: DashMap::new(),
            metrics: DashMap::new(),
        }
    }

    pub fn authenticate_with_headers(
        &self,
        headers: &HeaderMap,
        query_token: Option<&str>,
        environment: &str,
    ) -> Option<AuthResult> {
        let env = environment.to_lowercase();

        let auth_header = get_header_ci(headers, "authorization");
        let mut header_token: Option<String> = None;
        if let Some(a) = auth_header {
            let s = a.trim();
            if let Some(t) = s.strip_prefix("Bearer ") { header_token = Some(t.to_string()); }
            else if !s.is_empty() { header_token = Some(s.to_string()); }
        }

        let protocols = extract_subprotocols(headers);
        let mut subprotocol_token: Option<String> = None;
        if protocols.len() >= 2 && protocols[0].eq_ignore_ascii_case("bearer") {
            subprotocol_token = Some(protocols[1].clone());
        }

        let token = subprotocol_token.or(header_token).or_else(|| {
            if env == "production" { None } else { query_token.map(|s| s.to_string()) }
        });

        if token.is_none() && (env == "development" || env == "testing") {
            return Some(AuthResult {
                user_id: format!("guest-{}", current_ts()),
                username: "guest".into(),
                role: "guest".into(),
                permissions: vec!["tasks.view".into()],
                session_id: format!("guest-{}", current_ts()),
            });
        }

        let token = token?;

        let static_tokens: Vec<String> = [
            std::env::var("AUTH_TOKEN_ACTIVE").ok(),
            std::env::var("AUTH_TOKEN").ok(),
            std::env::var("AUTH_TOKEN_NEXT").ok(),
            std::env::var("HUB_AUTH_TOKEN").ok(),
        ].into_iter().flatten().map(|s| s.trim().to_string()).collect();

        if static_tokens.iter().any(|t| t == &token) {
            if env == "production" {
                let hp = parse_hmac_params_from_subprotocols(&protocols, headers);
                if !(hp.client_id.is_some() && hp.timestamp.is_some() && hp.nonce.is_some() && hp.signature.is_some()) {
                    return None;
                }
                let ok = self.validate_hmac(
                    &token,
                    hp.client_id.as_deref().unwrap(),
                    hp.timestamp.as_deref().unwrap(),
                    hp.nonce.as_deref().unwrap(),
                    hp.client_type.as_deref().unwrap_or("service"),
                    hp.client_version.as_deref().unwrap_or("1.0.0"),
                    hp.signature.as_deref().unwrap(),
                );
                if !ok { return None; }
            }
            return Some(AuthResult {
                user_id: format!("service-{}", current_ts()),
                username: "service".into(),
                role: "service".into(),
                permissions: vec!["tasks.view".into(), "tasks.execute".into(), "clients.view".into()],
                session_id: format!("svc-{}", current_ts()),
            });
        }

        if let Some(res) = self.decode_jwt(&token) { return Some(res); }
        None
    }

    pub fn decode_jwt(&self, token: &str) -> Option<AuthResult> {
        if let Ok(secret) = std::env::var("AUTH_SECRET") {
            let dec_key = jwt::DecodingKey::from_secret(secret.as_bytes());
            return self.decode_with_key(token, &dec_key);
        }
        if let Ok(pem) = std::env::var("AUTH_PUBLIC_KEY_PEM") {
            let dec_key = jwt::DecodingKey::from_rsa_pem(pem.as_bytes()).ok()?;
            return self.decode_with_key(token, &dec_key);
        }
        None
    }

    fn decode_with_key(&self, token: &str, key: &jwt::DecodingKey) -> Option<AuthResult> {
        #[derive(Deserialize)]
        struct Claims {
            user_id: Option<String>,
            username: Option<String>,
            role: Option<String>,
            permissions: Option<Vec<String>>,
            session_id: Option<String>,
            exp: Option<u64>,
        }
        let mut v = jwt::Validation::default();
        v.validate_exp = true;
        let data = jwt::decode::<Claims>(token, key, &v).ok()?;
        Some(AuthResult {
            user_id: data.claims.user_id.unwrap_or_else(|| "user".into()),
            username: data.claims.username.unwrap_or_else(|| "user".into()),
            role: data.claims.role.unwrap_or_else(|| "user".into()),
            permissions: data.claims.permissions.unwrap_or_default(),
            session_id: data.claims.session_id.unwrap_or_else(|| format!("sess-{}", current_ts())),
        })
    }

    pub fn is_rate_limited_ip(&self, ip: &str) -> bool {
        let now = now_secs();
        let mut dq = self.conn_attempts_ip.entry(ip.to_string()).or_default();
        while dq.front().map(|t| now - *t > self.conn_window_seconds as f64).unwrap_or(false) { dq.pop_front(); }
        dq.push_back(now);
        dq.len() > self.conn_max_per_window
    }

    pub fn record_token_attempt(&self, token: &str) {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(token.as_bytes());
        let hash = format!("{:x}", hasher.finalize());
        let now = now_secs();
        let mut dq = self.conn_attempts_tok.entry(hash).or_default();
        while dq.front().map(|t| now - *t > self.conn_window_seconds as f64).unwrap_or(false) { dq.pop_front(); }
        dq.push_back(now);
    }

    pub fn is_rate_limited_token(&self, token: &str) -> bool {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new(); hasher.update(token.as_bytes());
        let hash = format!("{:x}", hasher.finalize());
        let dq = match self.conn_attempts_tok.get(&hash) { Some(v) => v, None => return false };
        dq.len() > self.conn_max_per_window
    }

    pub fn check_and_store_nonce(&self, nonce: &str) -> bool {
        let now = now_secs();
        for k in self.used_nonces.iter() {
            if now - *k.value() > self.nonce_ttl_seconds as f64 {
                self.used_nonces.remove(k.key());
            }
        }
        if self.used_nonces.contains_key(nonce) { return false; }
        self.used_nonces.insert(nonce.to_string(), now);
        true
    }

    pub fn validate_hmac(
        &self,
        secret: &str,
        client_id: &str,
        ts_str: &str,
        nonce: &str,
        client_type: &str,
        client_version: &str,
        sig_hex: &str,
    ) -> bool {
        let Ok(ts) = ts_str.parse::<i64>() else { return false };
        let now = current_ts();
        const HANDSHAKE_WINDOW_SECONDS: i64 = 60;
        if (now - ts).abs() > HANDSHAKE_WINDOW_SECONDS { return false; }
        if !self.check_and_store_nonce(nonce) { return false; }
        let canonical = format!("{}|{}|{}|{}|{}", client_id, ts_str, nonce, client_type, client_version);
        type HmacSha256 = Hmac<Sha256>;
        let mut mac = match HmacSha256::new_from_slice(secret.as_bytes()) { Ok(m) => m, Err(_) => return false };
        mac.update(canonical.as_bytes());
        let expected = hex::encode(mac.finalize().into_bytes());
        subtle_equals(&expected, sig_hex)
    }

    pub fn validate_message(&self, client_id: &str, raw: &str, max_size: usize, per_second: usize) -> ValidationOutcome {
        if raw.len() > max_size { self.incr("errors_message_too_large_total", 1); return ValidationOutcome::TooLarge; }
        if !self.check_rate_limit(client_id, per_second) { self.incr("errors_rate_limited_total", 1); return ValidationOutcome::RateLimited; }
        // Normalize incoming payloads like Python (data flattening, message_type alias)
        match serde_json::from_str::<serde_json::Value>(raw) {
            Ok(v) => {
                let n = normalize_message_value(v);
                match serde_json::from_value::<WsEnvelope>(n) {
                    Ok(env) => ValidationOutcome::Ok(env),
                    Err(_) => ValidationOutcome::Invalid,
                }
            }
            Err(_) => ValidationOutcome::Invalid,
        }
    }

    pub fn check_rate_limit(&self, client_id: &str, per_second: usize) -> bool {
        let now = now_secs();
        let mut dq = self.rate_limiters.entry(client_id.to_string()).or_default();
        while dq.front().map(|t| now - *t > 1.0).unwrap_or(false) { dq.pop_front(); }
        if dq.len() >= per_second { return false; }
        dq.push_back(now);
        true
    }
}

#[derive(Debug, Clone)]
pub struct ConnectionInfo {
    pub user_id: String,
    pub permissions: Vec<String>,
    pub subscriptions: Vec<String>,
    pub connected_at: f64,
    pub last_activity: f64,
    pub message_count: u64,
    pub registered: bool,
    pub metadata: serde_json::Value,
}

impl WebSocketSecurityManager {
    pub fn register_connection(&self, client_id: String, auth: &AuthResult, sender: BoundedSender<String>) {
        if !self.can_accept_connection(&auth.user_id) { return; }
        let info = ConnectionInfo {
            user_id: auth.user_id.clone(),
            permissions: auth.permissions.clone(),
            subscriptions: Vec::new(),
            connected_at: now_secs(),
            last_activity: now_secs(),
            message_count: 0,
            registered: false,
            metadata: json!({}),
        };
        self.connections.insert(client_id.clone(), info);
        self.senders.insert(client_id.clone(), sender);
        let set = self.user_connections.entry(auth.user_id.clone()).or_insert_with(DashSet::new);
        set.insert(client_id);
    }

    pub fn try_register_connection(&self, client_id: String, auth: &AuthResult, sender: BoundedSender<String>) -> bool {
        if !self.can_accept_connection(&auth.user_id) { return false; }
        self.register_connection(client_id, auth, sender);
        true
    }

    pub fn disconnect_client(&self, client_id: &str) {
        if let Some((_k, info)) = self.connections.remove(client_id) {
            if let Some(mut set) = self.user_connections.get_mut(&info.user_id) {
                set.remove(client_id);
                if set.is_empty() { self.user_connections.remove(&info.user_id); }
            }
        }
        self.senders.remove(client_id);
    }

    pub fn handle_subscription(&self, client_id: &str, channel: &str, subscribe: bool) -> bool {
        let mut ok = false;
        if let Some(mut entry) = self.connections.get_mut(client_id) {
            let subs = &mut entry.subscriptions;
            if subscribe {
                if subs.len() >= self.max_subscriptions_per_client { return false; }
                if !subs.iter().any(|c| c == channel) { subs.push(channel.to_string()); }
                ok = true;
                self.incr("subscriptions_total", 1);
            } else {
                let before = subs.len();
                subs.retain(|c| c != channel);
                ok = before != subs.len();
                if ok { self.incr("unsubscriptions_total", 1); }
            }
        }
        ok
    }

    pub fn broadcast_to_channel(&self, channel: &str, message: &serde_json::Value, exclude: Option<&str>) -> usize {
        let text = message.to_string();
        let mut sent = 0usize;
        for kv in self.connections.iter() {
            let cid = kv.key();
            if Some(cid.as_str()) == exclude { continue; }
            if kv.subscriptions.iter().any(|c| c == channel) {
                if let Some(tx) = self.senders.get(cid) {
                    if tx.try_send(text.clone()).is_ok() {
                        sent += 1;
                    } else {
                        self.incr("errors_backpressure_total", 1);
                    }
                }
            }
        }
        self.incr("broadcasts_total", 1);
        if sent > 0 { self.incr("broadcast_recipients_total", sent as u64); }
        sent
    }

    pub fn send_to_user(&self, user_id: &str, message: &serde_json::Value) {
        if let Some(set) = self.user_connections.get(user_id) {
            let text = message.to_string();
            for cid in set.iter() {
                if let Some(tx) = self.senders.get(cid.as_str()) { let _ = tx.try_send(text.clone()); }
            }
        }
    }

    pub fn touch(&self, client_id: &str) {
        if let Some(mut entry) = self.connections.get_mut(client_id) {
            entry.last_activity = now_secs();
            entry.message_count += 1;
        }
    }

    pub fn is_registered(&self, client_id: &str) -> bool {
        self.connections.get(client_id).map(|e| e.registered).unwrap_or(false)
    }

    pub fn update_registration(&self, client_id: &str, data: &serde_json::Value) -> bool {
        if let Some(mut entry) = self.connections.get_mut(client_id) {
            entry.metadata = data.clone();
            entry.registered = true;
            return true;
        }
        false
    }

    pub fn permission_required_for_channel(&self, channel: &str) -> Option<&'static str> {
        if let Some(prefix) = channel.split(':').next() {
            return match prefix {
                "tasks" => Some("tasks.view"),
                _ => None,
            };
        }
        None
    }

    pub fn can_accept_connection(&self, user_id: &str) -> bool {
        let count = self.user_connections.get(user_id).map(|s| s.len()).unwrap_or(0);
        count < self.max_connections_per_user
    }

    pub fn check_permission(&self, client_id: &str, permission: &str) -> bool {
        self.connections.get(client_id).map(|e| e.permissions.iter().any(|p| p == permission)).unwrap_or(false)
    }

    pub fn check_origin_allowed(&self, headers: &HeaderMap, environment: &str) -> bool {
        if environment.eq_ignore_ascii_case("production") {
            let origin = get_header_ci(headers, "origin");
            let ua = get_header_ci(headers, "user-agent").unwrap_or_default().to_ascii_lowercase();
            let is_browser = origin.is_some() && (ua.contains("mozilla") || get_header_ci(headers, "sec-fetch-site").is_some());
            if let Some(origin_val) = origin {
                if is_browser {
                    let allowed = std::env::var("ALLOWED_ORIGINS").unwrap_or_default();
                    if allowed.trim().is_empty() { return true; }
                    let list: Vec<String> = allowed.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect();
                    if list.iter().any(|a| a == "*" || a == &origin_val) { return true; }
                    return false;
                }
            }
        }
        true
    }

    pub fn get_connection_stats(&self) -> serde_json::Value {
        let total_connections = self.connections.len();
        let unique_users = self.user_connections.len();
        let mut channels = std::collections::HashMap::<String, usize>::new();
        for info in self.connections.iter() {
            for ch in &info.subscriptions {
                *channels.entry(ch.clone()).or_insert(0) += 1;
            }
        }
        let mut metrics = std::collections::HashMap::<String, u64>::new();
        for kv in self.metrics.iter() { metrics.insert(kv.key().clone(), *kv.value()); }
        json!({
            "total_connections": total_connections,
            "unique_users": unique_users,
            "channels": channels,
            "metrics": metrics,
            "timestamp": chrono::Utc::now().to_rfc3339(),
        })
    }

    pub fn list_clients_json(&self) -> serde_json::Value {
        let mut list = Vec::new();
        for kv in self.connections.iter() {
            list.push(json!({
                "client_id": kv.key(),
                "user_id": kv.user_id,
                "permissions": kv.permissions,
                "subscriptions": kv.subscriptions,
                "connected_at": kv.connected_at,
                "last_activity": kv.last_activity,
                "message_count": kv.message_count,
                "metadata": kv.metadata,
            }));
        }
        json!({"clients": list, "total": list.len()})
    }

    pub fn list_tasks_json(&self) -> serde_json::Value {
        let mut list = Vec::new();
        for kv in self.tasks.iter() {
            list.push(json!({
                "task_id": kv.task_id,
                "task_type": kv.task_type,
                "status": kv.status,
                "created_at": kv.created_at,
                "submitter_client_id": kv.submitter_client_id,
            }));
        }
        json!({"tasks": list, "total": list.len()})
    }
}

fn current_ts() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64
}

fn now_secs() -> f64 {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    now.as_secs_f64()
}

fn subtle_equals(a: &str, b: &str) -> bool {
    if a.len() != b.len() { return false; }
    let mut diff = 0u8;
    for (x, y) in a.bytes().zip(b.bytes()) { diff |= x ^ y; }
    diff == 0
}

fn get_header_ci(headers: &HeaderMap, name: &str) -> Option<String> {
    if let Some(val) = headers.get(name) { return val.to_str().ok().map(|s| s.to_string()); }
    if let Some(val) = headers.get(name.to_ascii_lowercase()) { return val.to_str().ok().map(|s| s.to_string()); }
    let title = {
        let mut chars = name.chars();
        match chars.next() { Some(c) => format!("{}{}", c.to_ascii_uppercase(), chars.as_str()), None => name.to_string() }
    };
    if let Some(val) = headers.get(title) { return val.to_str().ok().map(|s| s.to_string()); }
    None
}

#[derive(Default)]
struct HmacParams {
    client_id: Option<String>,
    timestamp: Option<String>,
    nonce: Option<String>,
    client_type: Option<String>,
    client_version: Option<String>,
    signature: Option<String>,
}

fn extract_subprotocols(headers: &HeaderMap) -> Vec<String> {
    let mut protocols = Vec::new();
    if let Some(hv) = headers.get("sec-websocket-protocol") {
        if let Ok(s) = hv.to_str() { protocols = s.split(',').map(|p| p.trim().to_string()).filter(|p| !p.is_empty()).collect(); }
    }
    protocols
}

fn parse_hmac_params_from_subprotocols(protocols: &Vec<String>, headers: &HeaderMap) -> HmacParams {
    let mut res = HmacParams::default();
    let mapping = [
        ("xci", "client_id"),
        ("xts", "timestamp"),
        ("xnn", "nonce"),
        ("xct", "client_type"),
        ("xcv", "client_version"),
        ("xsig", "signature"),
    ];
    for raw in protocols.iter() {
        let s = raw.trim(); if s.is_empty() { continue; }
        if let Some((k,v)) = s.split_once('=') { set_param(&mut res, k.trim(), v.trim()); continue; }
        for (pfx, target) in mapping.iter() {
            let hy = format!("{}-", pfx);
            if s.to_ascii_lowercase().starts_with(&hy) {
                let val = &s[hy.len()..]; set_param(&mut res, target, val.trim()); break;
            }
        }
    }

    if let Some(v) = get_header_ci(headers, "X-Client-Id") { res.client_id = Some(v); }
    if let Some(v) = get_header_ci(headers, "X-Timestamp") { res.timestamp = Some(v); }
    if let Some(v) = get_header_ci(headers, "X-Nonce") { res.nonce = Some(v); }
    if let Some(v) = get_header_ci(headers, "X-Signature") { res.signature = Some(v); }
    if let Some(v) = get_header_ci(headers, "X-Client-Type") { res.client_type = Some(v); }
    if let Some(v) = get_header_ci(headers, "X-Client-Version") { res.client_version = Some(v); }

    res
}

fn set_param(res: &mut HmacParams, k: &str, v: &str) {
    match k.to_ascii_lowercase().as_str() {
        "client_id" => res.client_id = Some(v.to_string()),
        "timestamp" => res.timestamp = Some(v.to_string()),
        "nonce" => res.nonce = Some(v.to_string()),
        "client_type" => res.client_type = Some(v.to_string()),
        "client_version" => res.client_version = Some(v.to_string()),
        "signature" => res.signature = Some(v.to_string()),
        _ => {}
    }
}

fn normalize_message_value(mut v: serde_json::Value) -> serde_json::Value {
    use serde_json::{Value, Map};
    let obj = match v {
        Value::Object(ref mut m) => m,
        _ => return v,
    };

    // message_type alias to type
    if !obj.contains_key("type") {
        if let Some(mt) = obj.remove("message_type") { obj.insert("type".to_string(), mt); }
    }

    // broadcast: allow data as payload
    if matches!(obj.get("type").and_then(|t| t.as_str()), Some("broadcast")) {
        if obj.get("payload").is_none() {
            if let Some(d) = obj.remove("data") { obj.insert("payload".to_string(), d); }
        }
    }

    // subscribe/unsubscribe: flatten data.channel
    if matches!(obj.get("type").and_then(|t| t.as_str()), Some("subscribe") | Some("unsubscribe")) {
        if let Some(Value::Object(mut data)) = obj.remove("data") {
            if let Some(ch) = data.remove("channel") { obj.insert("channel".to_string(), ch); }
        }
    }

    // task_submit/client_registration/task_result: flatten data fields
    if matches!(obj.get("type").and_then(|t| t.as_str()), Some("task_submit") | Some("client_registration") | Some("task_result")) {
        if let Some(Value::Object(data)) = obj.remove("data") {
            for (k, val) in data.into_iter() {
                obj.entry(k).or_insert(val);
            }
        }
    }

    v
}

impl WebSocketSecurityManager {
    pub fn incr(&self, key: &str, delta: u64) {
        let mut entry = self.metrics.entry(key.to_string()).or_insert(0);
        let val = *entry.value();
        *entry.value_mut() = val.saturating_add(delta);
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskRecord {
    pub task_id: String,
    pub task_type: String,
    pub status: String,
    pub created_at: f64,
    pub submitter_client_id: String,
}

impl WebSocketSecurityManager {
    pub fn submit_task(&self, client_id: &str, payload: &serde_json::Value) -> serde_json::Value {
        let task_id = payload.get("task_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let task_type = payload.get("task_type").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if task_id.is_empty() || task_type.is_empty() {
            return json!({"type":"error","error":"invalid_task_payload"});
        }
        let rec = TaskRecord {
            task_id: task_id.clone(),
            task_type,
            status: "queued".to_string(),
            created_at: now_secs(),
            submitter_client_id: client_id.to_string(),
        };
        self.tasks.insert(task_id.clone(), rec);
        json!({"type":"status_update","task_id":task_id,"status":"queued"})
    }

    pub fn task_result(&self, payload: &serde_json::Value) -> serde_json::Value {
        let task_id = payload.get("task_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let status = payload.get("status").and_then(|v| v.as_str()).unwrap_or("").to_string();
        if task_id.is_empty() || status.is_empty() { return json!({"type":"error","error":"invalid_task_result"}); }
        if let Some(mut rec) = self.tasks.get_mut(&task_id) {
            rec.status = status.clone();
        }
        json!({"type":"task_status","task_id":task_id,"status":status})
    }
}
