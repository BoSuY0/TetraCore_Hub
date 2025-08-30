use axum::{extract::ws::{Message, WebSocket, WebSocketUpgrade}, extract::{Query, ConnectInfo, State}, http::HeaderMap, response::IntoResponse, routing::get, Router};
use futures::{SinkExt, StreamExt};
use tower_http::cors::{Any, CorsLayer};
use std::sync::Arc;
mod ws;
use crate::ws::{WebSocketSecurityManager, ValidationOutcome};
mod config;
use crate::config::AppConfig;
mod task_router;
use crate::task_router::{TaskRouter, parse_priority};
use std::net::SocketAddr;
use std::borrow::Cow;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

async fn health() -> axum::Json<serde_json::Value> {
    axum::Json(serde_json::json!({
        "status": "ok",
        "service": "tetra-hub",
    }))
}

// JWKS видалено як зайве для поточного оточення

#[derive(Clone)]
struct AppState {
    security: Arc<WebSocketSecurityManager>,
    config: Arc<AppConfig>,
    task_router: Arc<TaskRouter>,
}

async fn diagnostics(State(state): State<Arc<AppState>>) -> axum::Json<serde_json::Value> {
    let cfg = &state.config;
    let task_stats = state.task_router.get_stats_json();
    axum::Json(serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "environment": cfg.environment,
        "allowed_origins": cfg.allowed_origins,
        "ws": {
            "max_message_size": cfg.ws_max_message_size,
            "max_messages_per_second": cfg.ws_max_messages_per_second
        },
        "tasks": task_stats
    }))
}

async fn ws_stats(State(state): State<Arc<AppState>>) -> axum::Json<serde_json::Value> {
    axum::Json(state.security.get_connection_stats())
}

async fn clients(State(state): State<Arc<AppState>>) -> axum::Json<serde_json::Value> {
    axum::Json(state.security.list_clients_json())
}

async fn tasks(State(state): State<Arc<AppState>>) -> axum::Json<serde_json::Value> {
    let v = state.task_router.list_tasks_json().await;
    axum::Json(v)
}

// New handler that passes TaskRouter
async fn ws_handler_tr(
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    State(state): State<Arc<AppState>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Query(q): Query<WsQuery>,
) -> impl IntoResponse {
    let client_ip = addr.ip().to_string();
    let security = state.security.clone();
    let task_router = state.task_router.clone();
    ws.on_upgrade(move |socket| ws_on_upgrade_full_tr(socket, headers, q.token.clone(), security, task_router, client_ip))
}

#[tokio::main]
async fn main() {
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "info".to_string()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let security = Arc::new(WebSocketSecurityManager::new());
    let cfg = Arc::new(AppConfig::load());
    let task_router = TaskRouter::new();
    let state = Arc::new(AppState { security: security.clone(), config: cfg.clone(), task_router: task_router.clone() });
    let allowed = cfg.allowed_origins.clone();
    let cors = if allowed.trim().is_empty() {
        CorsLayer::permissive()
    } else {
        let mut layer = CorsLayer::new().allow_methods([axum::http::Method::GET, axum::http::Method::POST, axum::http::Method::OPTIONS])
            .allow_headers([axum::http::header::AUTHORIZATION, axum::http::header::CONTENT_TYPE]);
        if allowed.trim() == "*" {
            layer = layer.allow_origin(Any);
        } else {
            for origin in allowed.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()) {
                if let Ok(uri) = origin.parse::<axum::http::HeaderValue>() {
                    layer = layer.clone().allow_origin(uri);
                }
            }
        }
        layer
    };
    let app = Router::new()
        .route("/api/health", get(health))
        // .route("/api/jwks", get(jwks))
        .route("/api/diagnostics", get(diagnostics))
        .route("/api/ws/stats", get(ws_stats))
        .route("/api/clients", get(clients))
        .route("/api/tasks", get(tasks))
        .route("/ws", get(ws_handler_tr))
        .with_state(state.clone())
        .layer(cors);

    let addr: SocketAddr = "0.0.0.0:8000".parse().unwrap();
    tracing::info!("listening on {}", addr);

    let cert_path = std::env::var("APP_TLS_CERT").ok();
    let key_path = std::env::var("APP_TLS_KEY").ok();

    if let (Some(cert), Some(key)) = (cert_path, key_path) {
        tracing::info!("starting HTTPS with rustls");
        let tls_config = axum_server::tls_rustls::RustlsConfig::from_pem_file(cert, key)
            .await
            .expect("invalid TLS cert/key");
        axum_server::bind_rustls(addr, tls_config)
            .serve(app.into_make_service_with_connect_info::<SocketAddr>())
            .await
            .unwrap();
    } else {
        let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
        axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
            .await
            .unwrap();
    }
}

#[derive(Debug, serde::Deserialize)]
struct WsQuery { token: Option<String> }

async fn ws_handler(
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    State(state): State<Arc<AppState>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Query(q): Query<WsQuery>,
) -> impl IntoResponse {
    let token: Option<String> = None; // токен визначимо всередині через headers + query
    let client_ip = addr.ip().to_string();
    let security = state.security.clone();
    ws.on_upgrade(move |socket| ws_on_upgrade_full(socket, headers, q.token.clone(), security, client_ip))
}

fn extract_token(headers: &HeaderMap, query_token: Option<&str>) -> Option<String> {
    // Authorization: Bearer <token>
    if let Some(hv) = headers.get(axum::http::header::AUTHORIZATION) {
        if let Ok(s) = hv.to_str() {
            let s = s.trim();
            if let Some(t) = s.strip_prefix("Bearer ") {
                return Some(t.to_string());
            }
            if !s.is_empty() { return Some(s.to_string()); }
        }
    }
    // Fallback to query in dev/test
    if matches!(std::env::var("ENVIRONMENT").as_deref(), Ok("development") | Ok("testing")) {
        if let Some(t) = query_token { return Some(t.to_string()); }
    }
    None
}

async fn ws_on_upgrade_full(mut socket: WebSocket, headers: HeaderMap, query_token: Option<String>, security: Arc<WebSocketSecurityManager>, client_ip: String) {
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".into());
    if security.is_rate_limited_ip(&client_ip) { security.incr("errors_rate_limited_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"rate_limited"}).to_string())).await; let _ = socket.close().await; return; }
    if !security.check_origin_allowed(&headers, &env) { security.incr("errors_origin_blocked_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"origin_not_allowed"}).to_string())).await; let _ = socket.close().await; return; }
    let auth = security.authenticate_with_headers(&headers, query_token.as_deref(), &env);
    let Some(auth) = auth else { security.incr("errors_auth_failed_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"Authentication failed"}).to_string())).await; let _ = socket.close().await; return; };

    let max_inflight: usize = std::env::var("WS_MAX_INFLIGHT").ok().and_then(|v| v.parse().ok()).unwrap_or(32);
    let (tx, mut rx) = tokio::sync::mpsc::channel::<String>(max_inflight);
    let client_id = format!("{}:{}:{}", auth.user_id, auth.session_id, chrono::Utc::now().timestamp());
    if !security.try_register_connection(client_id.clone(), &auth, tx) { security.incr("errors_too_many_connections_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"too_many_connections"}).to_string())).await; let _ = socket.close().await; return; }

    let (mut sender, mut receiver) = socket.split();
    // control channel to send Close frames from other tasks
    let (ctrl_tx, mut ctrl_rx) = tokio::sync::mpsc::unbounded_channel::<(u16, String)>();

    // Відправник: слухає внутрішній канал і шле клієнту
    let mut out_rx = rx;
    tokio::spawn(async move {
        loop {
            tokio::select! {
                Some(text) = out_rx.recv() => {
                    let _ = sender.send(Message::Text(text)).await;
                }
                Some((code, reason)) = ctrl_rx.recv() => {
                    let _ = sender.send(Message::Close(Some(axum::extract::ws::CloseFrame{
                        code,
                        reason: Cow::from(reason),
                    }))).await;
                    break;
                }
                else => break,
            }
        }
    });

    // Приймач: обробляє вхідні повідомлення
    let mgr = security.clone();
    let cid = client_id.clone();
    let max_msg_size: usize = std::env::var("WS_MAX_MESSAGE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(256*1024);
    let max_rate: usize = std::env::var("WS_MAX_MESSAGES_PER_SECOND").ok().and_then(|v| v.parse().ok()).unwrap_or(10);
    let close_tx = ctrl_tx.clone();
    tokio::spawn(async move {
        let idle: u64 = std::env::var("WS_IDLE_TIMEOUT_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(120);
        loop {
            let next = receiver.next();
            let res = tokio::time::timeout(std::time::Duration::from_secs(idle), next).await;
            let Some(Ok(msg)) = match res {
                Ok(v) => v,
                Err(_) => {
                    mgr.incr("pong_missed_total", 1);
                    let _ = close_tx.send((axum::extract::ws::close_code::NORMAL, "idle_timeout".to_string()));
                    mgr.incr("idle_closed_total", 1);
                    break;
                }
            } else { break };
            match msg {
                Message::Text(text) => {
                    if text.trim().eq_ignore_ascii_case("ping") {
                        if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"pong"}).to_string()); }
                        continue;
                    }
                    match mgr.validate_message(&cid, &text, max_msg_size, max_rate) {
                        ValidationOutcome::Ok(env) => {
                        let require_reg = std::env::var("WS_REQUIRE_REGISTRATION_BEFORE_ACTIONS").ok().map(|v| v == "1" || v.eq_ignore_ascii_case("true")).unwrap_or(true);
                        if require_reg && !mgr.is_registered(&cid) {
                            match env.payload {
                                models::WsMessage::ClientRegistration{..} | models::WsMessage::Ping | models::WsMessage::Pong | models::WsMessage::Noop => {}
                                _ => { if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"registration_required"}).to_string()); } continue; }
                            }
                        }
                        match env.payload {
                            models::WsMessage::Subscribe{channel} => {
                                if !mgr.check_permission(&cid, "tasks.view") {
                                    mgr.incr("errors_permission_denied_total", 1);
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                } else {
                                    if let Some(required) = mgr.permission_required_for_channel(&channel) {
                                        if !mgr.check_permission(&cid, required) {
                                            mgr.incr("errors_permission_denied_total", 1);
                                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                            continue;
                                        }
                                    }
                                    mgr.handle_subscription(&cid, &channel, true);
                                }
                            }
                            models::WsMessage::Unsubscribe{channel} => { mgr.handle_subscription(&cid, &channel, false); }
                            models::WsMessage::Broadcast{channel, payload} => {
                                if !mgr.check_permission(&cid, "tasks.view") { mgr.incr("errors_permission_denied_total", 1); if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); } }
                                else { mgr.broadcast_to_channel(&channel, &payload, Some(&cid)); }
                            }
                            models::WsMessage::TaskSubmit{..} => {
                                if !mgr.check_permission(&cid, "tasks.execute") {
                                    mgr.incr("errors_permission_denied_total", 1);
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                } else {
                                    let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                    let resp = mgr.submit_task(&cid, &v);
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(resp.to_string()); }
                                }
                            }
                            models::WsMessage::TaskResult{..} => {
                                let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                let resp = mgr.task_result(&v);
                                if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(resp.to_string()); }
                            }
                            models::WsMessage::ClientRegistration { .. } => {
                                let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                if mgr.update_registration(&cid, &v) {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"registration_ack"}).to_string()); }
                                } else {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"registration_error","error":"unknown_client"}).to_string()); }
                                }
                            }
                            models::WsMessage::TaskUpdate { task_id, status, data } => {
                                let st = status.to_ascii_lowercase();
                                let resp = serde_json::json!({"type":"task_status","task_id":task_id,"status":st, "data": data});
                                if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(resp.to_string()); }
                            }
                            models::WsMessage::HealthStatus { status } => {
                                let payload = serde_json::json!({"type":"health_status","status": status});
                                if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(payload.to_string()); }
                            }
                            models::WsMessage::MetricsResponse { metrics } => {
                                let payload = serde_json::json!({"type":"metrics_response","metrics": metrics});
                                if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(payload.to_string()); }
                            }
                            models::WsMessage::Noop => { /* ignore */ }
                            _ => {}
                        }
                        mgr.touch(&cid);
                        }
                        ValidationOutcome::TooLarge => {
                            // Inform client then close with policy violation
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"message_too_large"}).to_string()); }
                            let _ = close_tx.send((axum::extract::ws::close_code::POLICY, "message_too_large".to_string()));
                        }
                        ValidationOutcome::RateLimited => {
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"too_many_ws_messages"}).to_string()); }
                            let _ = close_tx.send((axum::extract::ws::close_code::POLICY, "rate_limited".to_string()));
                        }
                        ValidationOutcome::Invalid => {
                            mgr.incr("errors_invalid_message_total", 1);
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"invalid_message"}).to_string()); }
                        }
                    }
                }
                Message::Binary(_) => {}
                Message::Ping(_) => { mgr.touch(&cid); }
                Message::Pong(_) => { mgr.touch(&cid); }
                Message::Close(_) => break,
            }
        }
        mgr.disconnect_client(&cid);
    });
}

// WS upgrade with TaskRouter integration
async fn ws_on_upgrade_full_tr(
    mut socket: WebSocket,
    headers: HeaderMap,
    query_token: Option<String>,
    security: Arc<WebSocketSecurityManager>,
    task_router: Arc<TaskRouter>,
    client_ip: String,
) {
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".into());
    if security.is_rate_limited_ip(&client_ip) { security.incr("errors_rate_limited_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"rate_limited"}).to_string())).await; let _ = socket.close().await; return; }
    if !security.check_origin_allowed(&headers, &env) { security.incr("errors_origin_blocked_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"origin_not_allowed"}).to_string())).await; let _ = socket.close().await; return; }
    let auth = security.authenticate_with_headers(&headers, query_token.as_deref(), &env);
    let Some(auth) = auth else { security.incr("errors_auth_failed_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"Authentication failed"}).to_string())).await; let _ = socket.close().await; return; };

    let max_inflight: usize = std::env::var("WS_MAX_INFLIGHT").ok().and_then(|v| v.parse().ok()).unwrap_or(32);
    let (tx, mut rx) = tokio::sync::mpsc::channel::<String>(max_inflight);
    let client_id = format!("{}:{}:{}", auth.user_id, auth.session_id, chrono::Utc::now().timestamp());
    if !security.try_register_connection(client_id.clone(), &auth, tx) { security.incr("errors_too_many_connections_total", 1); let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"too_many_connections"}).to_string())).await; let _ = socket.close().await; return; }

    let (mut sender, mut receiver) = socket.split();
    let (ctrl_tx, mut ctrl_rx) = tokio::sync::mpsc::unbounded_channel::<(u16, String)>();

    // outbound
    let mut out_rx = rx;
    tokio::spawn(async move {
        loop {
            tokio::select! {
                Some(text) = out_rx.recv() => {
                    let _ = sender.send(Message::Text(text)).await;
                }
                Some((code, reason)) = ctrl_rx.recv() => {
                    let _ = sender.send(Message::Close(Some(axum::extract::ws::CloseFrame{
                        code,
                        reason: Cow::from(reason),
                    }))).await;
                    break;
                }
                else => break,
            }
        }
    });

    // inbound
    let mgr = security.clone();
    let cid = client_id.clone();
    let hb_mgr = security.clone();
    let hb_cid = client_id.clone();
    tokio::spawn(async move {
        let interval: u64 = std::env::var("WS_HEARTBEAT_INTERVAL").ok().and_then(|v| v.parse().ok()).unwrap_or(30);
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(interval)).await;
            if hb_mgr.connections.get(&hb_cid).is_none() { break; }
            if let Some(tx) = hb_mgr.senders.get(&hb_cid) {
                let _ = tx.try_send(serde_json::json!({"type":"ping","timestamp": chrono::Utc::now().to_rfc3339()}).to_string());
            } else { break; }
        }
    });
    // Registration reminder/timeout
    let rt_mgr = security.clone();
    let rt_cid = client_id.clone();
    let close_tx2 = ctrl_tx.clone();
    tokio::spawn(async move {
        let timeout: u64 = std::env::var("WS_REGISTRATION_TIMEOUT_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(30);
        tokio::time::sleep(std::time::Duration::from_secs(timeout)).await;
        if let Some(info) = rt_mgr.connections.get(&rt_cid) {
            if !info.registered {
                // Notify and close with policy violation
                if let Some(tx) = rt_mgr.senders.get(&rt_cid) { let _ = tx.try_send(serde_json::json!({"type":"registration_error","error":"registration_required"}).to_string()); }
                let _ = close_tx2.send((axum::extract::ws::close_code::POLICY, "registration_timeout".to_string()));
            }
        }
    });
    let tr = task_router.clone();
    let max_msg_size: usize = std::env::var("WS_MAX_MESSAGE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(256*1024);
    let max_rate: usize = std::env::var("WS_MAX_MESSAGES_PER_SECOND").ok().and_then(|v| v.parse().ok()).unwrap_or(10);
    let close_tx = ctrl_tx.clone();
    tokio::spawn(async move {
        let idle: u64 = std::env::var("WS_IDLE_TIMEOUT_SECONDS").ok().and_then(|v| v.parse().ok()).unwrap_or(120);
        loop {
            let next = receiver.next();
            let res = tokio::time::timeout(std::time::Duration::from_secs(idle), next).await;
            let Some(Ok(msg)) = match res {
                Ok(v) => v,
                Err(_) => {
                    mgr.incr("pong_missed_total", 1);
                    let _ = close_tx.send((axum::extract::ws::close_code::NORMAL, "idle_timeout".to_string()));
                    mgr.incr("idle_closed_total", 1);
                    break;
                }
            } else { break };
            match msg {
                Message::Text(text) => {
                    if text.trim().eq_ignore_ascii_case("ping") {
                        if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"pong"}).to_string()); }
                        continue;
                    }
                    match mgr.validate_message(&cid, &text, max_msg_size, max_rate) {
                        ValidationOutcome::Ok(env) => {
                        let require_reg = std::env::var("WS_REQUIRE_REGISTRATION_BEFORE_ACTIONS").ok().map(|v| v == "1" || v.eq_ignore_ascii_case("true")).unwrap_or(true);
                        if require_reg && !mgr.is_registered(&cid) {
                            match env.payload {
                                models::WsMessage::ClientRegistration{..} | models::WsMessage::Ping | models::WsMessage::Pong | models::WsMessage::Noop => {}
                                _ => { if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"registration_required"}).to_string()); } continue; }
                            }
                        }
                        match env.payload {
                            models::WsMessage::Subscribe{channel} => {
                                if !mgr.check_permission(&cid, "tasks.view") {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                } else {
                                    if let Some(required) = mgr.permission_required_for_channel(&channel) {
                                        if !mgr.check_permission(&cid, required) {
                                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                            continue;
                                        }
                                    }
                                    mgr.handle_subscription(&cid, &channel, true);
                                }
                            }
                            models::WsMessage::Unsubscribe{channel} => { mgr.handle_subscription(&cid, &channel, false); }
                            models::WsMessage::Broadcast{channel, payload} => {
                                if !mgr.check_permission(&cid, "tasks.view") { if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); } }
                                else { mgr.broadcast_to_channel(&channel, &payload, Some(&cid)); }
                            }
                            models::WsMessage::StatsUpdate{ stats } => {
                                if !mgr.check_permission(&cid, "tasks.view") { mgr.incr("errors_permission_denied_total", 1); if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); } }
                                else {
                                    let payload = serde_json::json!({"type":"stats_update","stats": stats});
                                    mgr.broadcast_to_channel("stats", &payload, None);
                                    mgr.incr("stats_updates_total", 1);
                                }
                            }
                            models::WsMessage::SystemNotification{ level, message, data } => {
                                if !mgr.check_permission(&cid, "tasks.view") { mgr.incr("errors_permission_denied_total", 1); if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); } }
                                else {
                                    let payload = match data {
                                        Some(d) => serde_json::json!({"type":"system_notification","level": level, "message": message, "data": d}),
                                        None => serde_json::json!({"type":"system_notification","level": level, "message": message}),
                                    };
                                    mgr.broadcast_to_channel("system", &payload, None);
                                    mgr.incr("system_notifications_total", 1);
                                }
                            }
                            models::WsMessage::TaskSubmit{ task_id, task_type, task_data, priority, timeout, max_retries } => {
                                if !mgr.check_permission(&cid, "tasks.execute") {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()); }
                                } else {
                                    let mut task = models::task::Task::create(task_id, task_type, task_data);
                                    task.priority = parse_priority(priority);
                                    if let Some(t) = timeout { task.timeout = t; }
                                    if let Some(r) = max_retries { task.max_retries = r; }
                                    let resp = tr.submit_task(task).await;
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(resp.to_string()); }
                                }
                            }
                            models::WsMessage::TaskResult{ task_id, status, data } => {
                                let st = match status.to_ascii_lowercase().as_str() {
                                    "pending" => models::task::TaskStatus::Pending,
                                    "assigned" => models::task::TaskStatus::Assigned,
                                    "processing" => models::task::TaskStatus::Processing,
                                    "completed" => models::task::TaskStatus::Completed,
                                    "failed" => models::task::TaskStatus::Failed,
                                    "timeout" => models::task::TaskStatus::Timeout,
                                    "retry" => models::task::TaskStatus::Retry,
                                    "cancelled" => models::task::TaskStatus::Cancelled,
                                    _ => models::task::TaskStatus::Completed,
                                };
                                let resp = tr.complete_task(&task_id, st, data);
                                if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(resp.to_string()); }
                            }
                            models::WsMessage::ClientRegistration { .. } => {
                                let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                if mgr.update_registration(&cid, &v) {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"registration_ack"}).to_string()); }
                                } else {
                                    if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"registration_error","error":"unknown_client"}).to_string()); }
                                }
                            }
                            _ => {}
                        }
                        mgr.touch(&cid);
                        }
                        ValidationOutcome::TooLarge => {
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"message_too_large"}).to_string()); }
                            let _ = close_tx.send((axum::extract::ws::close_code::POLICY, "message_too_large".to_string()));
                        }
                        ValidationOutcome::RateLimited => {
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"too_many_ws_messages"}).to_string()); }
                            let _ = close_tx.send((axum::extract::ws::close_code::POLICY, "rate_limited".to_string()));
                        }
                        ValidationOutcome::Invalid => {
                            if let Some(tx) = mgr.senders.get(&cid) { let _ = tx.try_send(serde_json::json!({"type":"error","error":"invalid_message"}).to_string()); }
                        }
                    }
                }
                Message::Binary(_) => {}
                Message::Ping(_) => { mgr.touch(&cid); }
                Message::Pong(_) => { mgr.touch(&cid); }
                Message::Close(_) => break,
            }
        }
        mgr.disconnect_client(&cid);
    });
}
