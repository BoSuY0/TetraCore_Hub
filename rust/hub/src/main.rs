use axum::{extract::ws::{Message, WebSocket, WebSocketUpgrade}, extract::{Query, ConnectInfo, State}, http::HeaderMap, response::IntoResponse, routing::get, Router};
use futures::{SinkExt, StreamExt};
use base64::Engine;
use rsa::pkcs8::DecodePublicKey;
use rsa::traits::PublicKeyParts;
use tower_http::cors::{Any, CorsLayer};
use std::sync::Arc;
use tetra_core::ws::WebSocketSecurityManager;
use std::net::SocketAddr;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

async fn health() -> axum::Json<serde_json::Value> {
    axum::Json(serde_json::json!({
        "status": "ok",
        "service": "tetra-hub",
    }))
}

async fn jwks() -> axum::Json<serde_json::Value> {
    // Генеруємо JWKS з ENV AUTH_PUBLIC_KEY_PEM (RSA)
    if let Ok(pem) = std::env::var("AUTH_PUBLIC_KEY_PEM") {
        if let Ok(key) = rsa::RsaPublicKey::from_public_key_pem(&pem) {
            let n_bytes: Vec<u8> = key.n().to_bytes_be();
            let e_bytes: Vec<u8> = key.e().to_bytes_be();
            let n = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(n_bytes);
            let e = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(e_bytes);
            let jwk = serde_json::json!({
                "kty":"RSA","alg":"RS256","use":"sig","n":n,"e":e,
            });
            return axum::Json(serde_json::json!({"keys":[jwk]}));
        }
    }
    axum::Json(serde_json::json!({"keys":[]}))
}

async fn diagnostics() -> axum::Json<serde_json::Value> {
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "development".to_string());
    let allowed = std::env::var("ALLOWED_ORIGINS").unwrap_or_default();
    let ws_max_size: usize = std::env::var("WS_MAX_MESSAGE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(256*1024);
    let ws_max_rate: usize = std::env::var("WS_MAX_MESSAGES_PER_SECOND").ok().and_then(|v| v.parse().ok()).unwrap_or(10);
    axum::Json(serde_json::json!({
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "environment": env,
        "allowed_origins": allowed,
        "ws": {
            "max_message_size": ws_max_size,
            "max_messages_per_second": ws_max_rate
        }
    }))
}

async fn ws_stats(State(security): State<Arc<WebSocketSecurityManager>>) -> axum::Json<serde_json::Value> {
    axum::Json(security.get_connection_stats())
}

async fn clients(State(security): State<Arc<WebSocketSecurityManager>>) -> axum::Json<serde_json::Value> {
    axum::Json(security.list_clients_json())
}

async fn tasks(State(security): State<Arc<WebSocketSecurityManager>>) -> axum::Json<serde_json::Value> {
    axum::Json(security.list_tasks_json())
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
    let allowed = std::env::var("ALLOWED_ORIGINS").unwrap_or_default();
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
        .route("/api/jwks", get(jwks))
        .route("/api/diagnostics", get(diagnostics))
        .route("/api/ws/stats", get(ws_stats))
        .route("/api/clients", get(clients))
        .route("/api/tasks", get(tasks))
        .route("/ws", get(ws_handler))
        .with_state(security.clone())
        .layer(cors);

    let addr: SocketAddr = "0.0.0.0:8000".parse().unwrap();
    tracing::info!("listening on {}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
        .await
        .unwrap();
}

#[derive(Debug, serde::Deserialize)]
struct WsQuery { token: Option<String> }

async fn ws_handler(
    ws: WebSocketUpgrade,
    headers: HeaderMap,
    State(security): State<Arc<WebSocketSecurityManager>>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    Query(q): Query<WsQuery>,
) -> impl IntoResponse {
    let token: Option<String> = None; // токен визначимо всередині через headers + query
    let client_ip = addr.ip().to_string();
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
    if security.is_rate_limited_ip(&client_ip) { let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"rate_limited"}).to_string())).await; let _ = socket.close().await; return; }
    if !security.check_origin_allowed(&headers, &env) { let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"origin_not_allowed"}).to_string())).await; let _ = socket.close().await; return; }
    let auth = security.authenticate_with_headers(&headers, query_token.as_deref(), &env);
    let Some(auth) = auth else { let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"Authentication failed"}).to_string())).await; let _ = socket.close().await; return; };

    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel::<String>();
    let client_id = format!("{}:{}:{}", auth.user_id, auth.session_id, chrono::Utc::now().timestamp());
    if !security.try_register_connection(client_id.clone(), &auth, tx) { let _ = socket.send(Message::Text(serde_json::json!({"type":"error","error":"too_many_connections"}).to_string())).await; let _ = socket.close().await; return; }

    let (mut sender, mut receiver) = socket.split();

    // Відправник: слухає внутрішній канал і шле клієнту
    let mut out_rx = rx;
    tokio::spawn(async move {
        while let Some(text) = out_rx.recv().await {
            let _ = sender.send(Message::Text(text)).await;
        }
    });

    // Приймач: обробляє вхідні повідомлення
    let mgr = security.clone();
    let cid = client_id.clone();
    let max_msg_size: usize = std::env::var("WS_MAX_MESSAGE_SIZE").ok().and_then(|v| v.parse().ok()).unwrap_or(256*1024);
    let max_rate: usize = std::env::var("WS_MAX_MESSAGES_PER_SECOND").ok().and_then(|v| v.parse().ok()).unwrap_or(10);
    tokio::spawn(async move {
        while let Some(Ok(msg)) = receiver.next().await {
            match msg {
                Message::Text(text) => {
                    if text.trim().eq_ignore_ascii_case("ping") {
                        let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"pong"}).to_string()));
                        continue;
                    }
                    if let Some(env) = mgr.validate_message(&cid, &text, max_msg_size, max_rate) {
                        match env.payload {
                            models::WsMessage::Subscribe{channel} => {
                                if !mgr.check_permission(&cid, "tasks.view") {
                                    let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()));
                                } else {
                                    if let Some(required) = mgr.permission_required_for_channel(&channel) {
                                        if !mgr.check_permission(&cid, required) {
                                            let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()));
                                            continue;
                                        }
                                    }
                                    mgr.handle_subscription(&cid, &channel, true);
                                }
                            }
                            models::WsMessage::Unsubscribe{channel} => { mgr.handle_subscription(&cid, &channel, false); }
                            models::WsMessage::Broadcast{channel, payload} => {
                                if !mgr.check_permission(&cid, "tasks.view") { let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string())); }
                                else { mgr.broadcast_to_channel(&channel, &payload, Some(&cid)); }
                            }
                            models::WsMessage::TaskSubmit{..} => {
                                if !mgr.check_permission(&cid, "tasks.execute") {
                                    let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"error","error":"permission_denied"}).to_string()));
                                } else {
                                    let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                    let resp = mgr.submit_task(&cid, &v);
                                    let _ = mgr.senders.get(&cid).map(|tx| tx.send(resp.to_string()));
                                }
                            }
                            models::WsMessage::TaskResult{..} => {
                                let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                let resp = mgr.task_result(&v);
                                let _ = mgr.senders.get(&cid).map(|tx| tx.send(resp.to_string()));
                            }
                            models::WsMessage::ClientRegistration { .. } => {
                                let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
                                if mgr.update_registration(&cid, &v) {
                                    let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"registration_ack"}).to_string()));
                                } else {
                                    let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"registration_error","error":"unknown_client"}).to_string()));
                                }
                            }
                            _ => {}
                        }
                        mgr.touch(&cid);
                    } else {
                        let _ = mgr.senders.get(&cid).map(|tx| tx.send(serde_json::json!({"type":"error","error":"invalid_message"}).to_string()));
                    }
                }
                Message::Binary(_) => {}
                Message::Ping(_) => {}
                Message::Pong(_) => {}
                Message::Close(_) => break,
            }
        }
        mgr.disconnect_client(&cid);
    });
}
