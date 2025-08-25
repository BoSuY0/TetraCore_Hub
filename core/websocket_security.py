"""
WebSocket Security Middleware for TetraCore Hub
Захист WebSocket з'єднань з JWT автентифікацією та валідацією
"""

import json
import orjson
import time
import asyncio
from typing import Dict, Optional, List, Set, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
from collections import defaultdict, deque
import os

from fastapi import WebSocket, Query, HTTPException
from fastapi.websockets import WebSocketState
import structlog
import redis
import jwt
from pydantic import BaseModel, Field, validator, ValidationError

from core.auth_manager import get_auth_manager, initialize_auth_manager_redis

logger = structlog.get_logger()

# Константи безпеки (env-override)
MAX_MESSAGE_SIZE = int(os.getenv("WS_MAX_MESSAGE_SIZE", str(256 * 1024)))
MAX_MESSAGES_PER_SECOND = int(os.getenv("WS_MAX_MESSAGES_PER_SECOND", "10"))
MAX_CONNECTIONS_PER_USER = 20  # Збільшено для development
CONNECTION_TIMEOUT = 300  # 5 хвилин
HEARTBEAT_INTERVAL = 30  # 30 секунд
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_WINDOW = 60  # 1 хвилина
HANDSHAKE_WINDOW_SECONDS = 60  # Дозволене вікно часу для HMAC-handshake


class WebSocketMessage(BaseModel):
    """Базова модель для WebSocket повідомлень"""

    type: str = Field(..., max_length=50)
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_id: Optional[str] = None
    correlation_id: Optional[str] = None

    @validator("type")
    def validate_type(cls, v):
        allowed_types = [
            "ping",
            "pong",
            "subscribe",
            "unsubscribe",
            "task_update",
            "status_update",
            "error",
            "auth",
            "client_info",
            "metrics",
            "client_registration",
            "registration_ack",
            "registration_error",
            "task_submit",
            "task_assign",
            "task_result",
            "health_check",
            "health_status",
            "broadcast",
            "system_notification",
            "stats_update",
        ]
        if v not in allowed_types:
            raise ValueError(f"Invalid message type: {v}")
        return v


class ClientRegistrationMessage(WebSocketMessage):
    """Повідомлення реєстрації клієнта (WebSocket)."""

    type: str = "client_registration"
    data: Dict[str, Any]

    @validator("data")
    def validate_registration(cls, v):
        required = {"client_id", "client_type", "client_name", "client_version"}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(
                f"Missing registration fields: {', '.join(sorted(missing))}"
            )
        return v


class TaskResultMessage(WebSocketMessage):
    """Повідомлення з результатом виконання задачі."""

    type: str = "task_result"
    data: Dict[str, Any]

    @validator("data")
    def validate_result(cls, v):
        required = {"task_id", "status"}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(
                f"Missing task_result fields: {', '.join(sorted(missing))}"
            )
        return v

    @validator("data")
    def validate_data_size(cls, v):
        # Перевірка розміру даних
        try:
            payload = orjson.dumps(v)
            size = len(payload)
        except (orjson.JSONEncodeError, TypeError):
            data_str = json.dumps(v)
            size = len(data_str.encode("utf-8"))
        if size > MAX_MESSAGE_SIZE:
            raise ValueError(f"Message too large: {size} bytes")
        return v


class TaskSubmitMessage(WebSocketMessage):
    """Повідомлення на подання задачі до виконання."""

    type: str = "task_submit"
    data: Dict[str, Any]

    @validator("data")
    def validate_fields(cls, v):
        # Розширений дозволений набір полів для сумісності з клієнтами
        allowed = {
            "task_id",
            "task_type",
            "task_data",
            "priority",
            "timeout",
            "max_retries",
            "worker_requirements",
            "created_at",
            "executor_type",
            "correlation_id",
        }
        extra = set(v.keys()) - allowed
        if extra:
            raise ValueError(f"Unexpected fields: {', '.join(extra)}")
        return v


class SubscriptionMessage(WebSocketMessage):
    """Повідомлення керування підпискою (subscribe/unsubscribe)."""

    type: str
    data: Dict[str, Any]

    @validator("type")
    def validate_type(cls, v):
        if v not in ("subscribe", "unsubscribe"):
            raise ValueError("Invalid subscription action")
        return v

    @validator("data")
    def validate_sub_data(cls, v):
        if "channel" not in v:
            raise ValueError("Missing channel")
        return v


@dataclass(slots=True)
class ConnectionInfo:
    """Інформація про WebSocket з'єднання"""

    websocket: WebSocket
    user_id: str
    client_id: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_count: int = 0
    last_message_time: float = field(default_factory=time.time)
    subscriptions: Set[str] = field(default_factory=set)
    permissions: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class WebSocketSecurityManager:
    """Менеджер безпеки для WebSocket з'єднань"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.connections: Dict[str, ConnectionInfo] = {}
        self.user_connections: Dict[str, List[str]] = {}
        self.rate_limiters: Dict[str, List[float]] = {}
        self._cleanup_task = None

        # Rate limiting для спроб підключення
        self._conn_attempts_ip: Dict[str, deque] = defaultdict(deque)
        self._conn_attempts_tok: Dict[str, deque] = defaultdict(deque)
        self._conn_window_seconds: int = int(os.getenv("WS_CONN_WINDOW_SECONDS", "60"))
        self._conn_max_per_window: int = int(
            os.getenv("WS_MAX_CONN_ATTEMPTS_PER_MIN", "20")
        )

        # Анти-replay: кеш використаних nonce (in-memory; Redis використовується коли є)
        self._used_nonces: Dict[str, float] = {}
        self._nonce_ttl_seconds: int = int(os.getenv("WS_NONCE_TTL_SECONDS", "120"))

    async def cleanup(self):
        """Cleanup resources and cancel background tasks"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    def __del__(self):
        """Ensure cleanup task is cancelled on deletion"""
        if self._cleanup_task and not self._cleanup_task.done():
            try:
                # Try to get the event loop
                loop = asyncio.get_event_loop()
                if not loop.is_closed():
                    self._cleanup_task.cancel()
            except RuntimeError:
                # Event loop doesn't exist or is closed, task will be cleaned up anyway
                pass

    # --------------------- Header helpers ---------------------
    def _get_header_ci(
        self, headers: Any, name: str, default: Optional[str] = None
    ) -> Optional[str]:
        """Повертає значення заголовка без врахування регістру ключа.

        Працює з будь-яким Mapping-подібним об'єктом (включно з MappingProxyType
        та Starlette Headers). Безпечно обробляє відсутність методів .get/.items.
        """
        try:
            if headers is None:
                return default
            # Пряма спроба через get
            getter = getattr(headers, "get", None)
            if callable(getter):
                val = getter(name)
                if val is not None:
                    return val
                # Спробуємо поширені варіації регістру
                val = getter(name.lower())
                if val is not None:
                    return val
                val = getter(name.title())
                if val is not None:
                    return val
            # Перебір елементів з порівнянням ключів у нижньому регістрі
            items_iter = getattr(headers, "items", None)
            if callable(items_iter):
                target = name.lower()
                for k, v in headers.items():
                    try:
                        if str(k).lower() == target:
                            return v
                    except (ValueError, TypeError, AttributeError):
                        continue
        except (AttributeError, TypeError):
            return default
        return default

    async def authenticate_websocket(
        self, websocket: WebSocket, token: Optional[str]
    ) -> Optional[Dict]:
        """Автентифікація WebSocket з'єднання"""
        import os
        import time
        from config import get_settings

        environment = os.getenv("ENVIRONMENT", "development")
        settings = get_settings()
        client_ip = websocket.client.host if websocket.client else "unknown"

        # Rate limit за IP
        if self._is_rate_limited_ip(client_ip):
            logger.warning("WebSocket connection rate limited (IP)", ip=client_ip)
            await self._incr_metric("ip_rate_limited")
            return None

        # 1) Отримуємо токени з query, заголовка та subprotocol (case-insensitive для сумісності)
        headers = getattr(websocket, "headers", None)
        auth_header = self._get_header_ci(headers, "authorization")
        # Спроба отримати токен з WebSocket subprotocols (наприклад: ["bearer", "<JWT>"])
        subprotocol_token = None
        try:
            # Спершу дивимось у ASGI scope, який надає Starlette/FastAPI
            scope = getattr(websocket, "scope", {}) or {}
            offered = scope.get("subprotocols")
            if isinstance(offered, (list, tuple)) and len(offered) >= 2:
                first = str(offered[0]).lower()
                if first == "bearer":
                    subprotocol_token = str(offered[1])
            # Якщо у scope немає — пробуємо заголовок 'Sec-WebSocket-Protocol'
            if not subprotocol_token:
                proto_hdr = self._get_header_ci(headers, "sec-websocket-protocol")
                if proto_hdr:
                    parts = [p.strip() for p in str(proto_hdr).split(",") if p.strip()]
                    if len(parts) >= 2 and parts[0].lower() == "bearer":
                        subprotocol_token = parts[1]
        except Exception:
            subprotocol_token = None

        query_token_present = bool(token)
        header_token = None
        if auth_header:
            auth_header_str = str(auth_header)
            if auth_header_str.lower().startswith("bearer "):
                header_token = auth_header_str.split(" ", 1)[1].strip()
            else:
                header_token = auth_header_str.strip()

        # Перевірка Origin лише для браузерів у продакшні
        if environment.lower() == "production":
            origin = self._get_header_ci(headers, "origin")
            ua = (self._get_header_ci(headers, "user-agent") or "").lower()
            is_browser = bool(origin) and (
                "mozilla" in ua
                or self._get_header_ci(headers, "sec-fetch-site") is not None
            )
            if origin and is_browser:
                from config import get_settings

                allowed = get_settings().allowed_origins or []
                if allowed and "*" not in allowed and origin not in allowed:
                    logger.warning("WebSocket Origin not allowed", origin=origin)
                    await self._incr_metric("ws_origin_blocked")
                    return None

        # У production забороняємо ?token=
        if environment.lower() == "production" and query_token_present:
            logger.warning("Query token is not allowed in production")
            await self._incr_metric("query_token_rejected")
            return None

        token = subprotocol_token or header_token or token

        # 2) Якщо досі немає токена — у development/testing дозволяємо гостьовий доступ
        if not token:
            if environment.lower() in ("development", "testing"):
                logger.info("WebSocket guest access granted (dev/test mode)")
                guest_id = (
                    self._get_header_ci(headers, "X-Client-Id")
                    or f"guest-{int(time.time())}"
                )
                guest_type = (
                    self._get_header_ci(headers, "X-Client-Type") or "guest"
                ).lower()
                return {
                    "user_id": guest_id,
                    "username": "guest",
                    "role": guest_type,
                    "permissions": ["tasks.view"],
                    "session_id": f"guest-{int(time.time())}",
                }
            logger.warning("WebSocket authentication failed: no token provided")
            return None

        # Спочатку перевіряємо чи це один зі статичних токенів для сервісних клієнтів (бот/воркер)
        static_tokens: list[str] = []
        # Підтримка dual-token ротації з settings
        token_active = getattr(settings, "auth_token_active", None) or getattr(
            settings, "auth_token", None
        )
        token_next = getattr(settings, "auth_token_next", None)
        # Також враховуємо ENV-перемінні без перезавантаження settings
        env_active = os.getenv("AUTH_TOKEN_ACTIVE") or os.getenv("AUTH_TOKEN")
        env_next = os.getenv("AUTH_TOKEN_NEXT") or os.getenv("HUB_AUTH_TOKEN")

        for t in (token_active, token_next, env_active, env_next):
            if t:
                static_tokens.append(t.strip())

        if token in static_tokens:
            # Для сервісних клієнтів у проді HMAC обов'язковий
            if environment.lower() == "production" and not (
                await self._validate_hmac_handshake_async(websocket, token)
            ):
                logger.warning("HMAC handshake validation failed")
                await self._incr_metric("hmac_failed")
                return None

            # Rate-limit за токеном (через хеш)
            self._record_token_attempt(token)
            if self._is_rate_limited_token(token):
                logger.warning("WebSocket connection rate limited (token)")
                await self._incr_metric("token_rate_limited")
                return None

            client_id = (
                self._get_header_ci(headers, "X-Client-Id")
                or f"service-{int(time.time())}"
            )
            client_type = (
                self._get_header_ci(headers, "X-Client-Type") or "service"
            ).lower()
            logger.info(
                "WebSocket authentication successful with static token",
                client_id=client_id,
                client_type=client_type,
            )
            return {
                "user_id": client_id,
                "username": client_type,
                "role": "service",
                "permissions": ["tasks.view", "tasks.execute", "clients.view"],
                "session_id": f"svc-{int(time.time())}",
            }

        try:
            # Валідація JWT токена для Dashboard/Monitor клієнтів
            auth_mgr = get_auth_manager()

            # Ініціалізуємо Redis якщо потрібно ТА явно дозволено конфігом
            if auth_mgr.redis_client is None:
                try:
                    redis_enabled_env = os.getenv("REDIS_ENABLED", "true").lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                    if redis_enabled_env:
                        await initialize_auth_manager_redis()
                except (redis.exceptions.RedisError, RuntimeError) as e:
                    logger.warning(
                        "Could not initialize Redis for WebSocket auth", error=str(e)
                    )

            payload = await auth_mgr.decode_token(token)

            # Не спамимо на кожне підключення: лог тільки за прапорцем або для перших підключень
            if os.getenv("LOG_WS_AUTH", "false").lower() in ("1", "true", "yes"):
                logger.info(
                    "WebSocket authentication successful with JWT token",
                    user_id=payload.get("user_id"),
                    username=payload.get("username"),
                )

            return {
                "user_id": payload.get("user_id"),
                "username": payload.get("username"),
                "role": payload.get("role"),
                "permissions": payload.get("permissions", []),
                "session_id": payload.get("session_id"),
            }

        except (jwt.InvalidTokenError, ValueError, TypeError, HTTPException) as e:
            # Уникаємо дублювання логів: детальну причину логуємо тут,
            # у виклику зверху (hub) логуємо тільки короткий контекст без повтору помилки
            logger.warning("WebSocket authentication failed", error=str(e))
            return None

    async def accept_connection(
        self, websocket: WebSocket, user_data: Dict
    ) -> Optional[ConnectionInfo]:
        """Прийняття та реєстрація WebSocket з'єднання"""
        user_id = user_data["user_id"]
        client_id = f"{user_id}:{user_data['session_id']}:{time.time()}"

        # Перевірка кількості з'єднань користувача
        current_connections = len(self.user_connections.get(user_id, []))
        if not self._check_connection_limit(user_id):
            logger.warning(
                "WebSocket connection limit exceeded",
                user_id=user_id,
                current_connections=current_connections,
                max_connections=MAX_CONNECTIONS_PER_USER,
            )
            await self._send_error(websocket, "Too many connections")
            return None

        # Лог успішної перевірки ліміту виводимо не частіше ніж раз на хвилину для кожного користувача
        _now = int(time.time())
        throttle_key = f"limit_ok:{user_id}"
        last = (
            getattr(self, "_throttle_log_ts", {}).get(throttle_key)
            if hasattr(self, "_throttle_log_ts")
            else None
        )
        if not hasattr(self, "_throttle_log_ts"):
            self._throttle_log_ts = {}
        if last is None or _now - last >= 60:
            logger.info(
                "WebSocket connection limit check passed",
                user_id=user_id,
                current_connections=current_connections,
                max_connections=MAX_CONNECTIONS_PER_USER,
            )
            self._throttle_log_ts[throttle_key] = _now

        # Створюємо інформацію про з'єднання
        conn_info = ConnectionInfo(websocket, user_id, client_id)
        conn_info.permissions = user_data.get("permissions", [])

        # Реєструємо з'єднання
        self.connections[client_id] = conn_info

        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(client_id)

        # Зберігаємо в Redis якщо доступний
        if self.redis_client:
            conn_key = f"ws_conn:{client_id}"
            conn_data = {
                "user_id": user_id,
                "connected_at": conn_info.connected_at.isoformat(),
                "permissions": conn_info.permissions,
            }
            await self.redis_client.setex(
                conn_key, CONNECTION_TIMEOUT, json.dumps(conn_data)
            )

        # Прийняття з'єднання — лог лише якщо змінилась кількість підключень modulo 10 або для перших підключень
        total_now = len(self.connections)
        if total_now <= 3 or total_now % 10 == 0:
            logger.info(
                "WebSocket connection accepted",
                client_id=client_id,
                user_id=user_id,
                total_connections=total_now,
            )

        # Запускаємо cleanup якщо ще не запущений
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_connections())

        return conn_info

    async def validate_message(
        self, client_id: str, raw_message: str
    ) -> Optional[WebSocketMessage]:
        """Валідація вхідного повідомлення"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            logger.warning("Message from unknown connection", client_id=client_id)
            return None

        # Перевірка розміру
        if len(raw_message) > MAX_MESSAGE_SIZE:
            await self._send_error(conn_info.websocket, "Message too large")
            return None

        # Rate limiting
        if not self._check_rate_limit(client_id):
            await self._send_error(conn_info.websocket, "Rate limit exceeded")
            return None

        # Парсинг та валідація
        try:
            try:
                message_data = orjson.loads(
                    raw_message
                    if isinstance(raw_message, (bytes, bytearray))
                    else raw_message.encode("utf-8")
                )
            except (orjson.JSONDecodeError, TypeError):
                message_data = json.loads(raw_message)

            base = WebSocketMessage(**message_data)

            if base.type in ("task_submit",):
                # Підтримка плоского формату: загортаємо поля у data при потребі
                if "data" not in message_data or not isinstance(
                    message_data.get("data"), dict
                ):
                    allowed_fields = {
                        "task_id",
                        "task_type",
                        "task_data",
                        "priority",
                        "timeout",
                        "max_retries",
                        "worker_requirements",
                        "created_at",
                        "executor_type",
                    }
                    nested = {
                        k: v for k, v in message_data.items() if k in allowed_fields
                    }
                    normalized = {"type": "task_submit", "data": nested}
                    for mk in ("timestamp", "message_id", "correlation_id"):
                        if mk in message_data:
                            normalized[mk] = message_data[mk]
                    message = TaskSubmitMessage(**normalized)
                else:
                    message = TaskSubmitMessage(**message_data)
            elif base.type in ("client_registration",):
                # Підтримка плоского формату: загортаємо поля у data при потребі
                if "data" not in message_data or not isinstance(
                    message_data.get("data"), dict
                ):
                    allowed_fields = {
                        "client_id",
                        "client_type",
                        "client_name",
                        "client_version",
                        "capabilities",
                        "max_concurrent_tasks",
                        "auth_token",
                        "client_info",
                    }
                    nested = {
                        k: v for k, v in message_data.items() if k in allowed_fields
                    }
                    normalized = {"type": "client_registration", "data": nested}
                    for mk in ("timestamp", "message_id", "correlation_id"):
                        if mk in message_data:
                            normalized[mk] = message_data[mk]
                    message = ClientRegistrationMessage(**normalized)
                else:
                    message = ClientRegistrationMessage(**message_data)
            elif base.type in ("task_result",):
                message = TaskResultMessage(**message_data)
            elif base.type in ("subscribe", "unsubscribe"):
                message = SubscriptionMessage(**message_data)
            else:
                message = base

            # Оновлюємо статистику
            conn_info.last_activity = datetime.now(timezone.utc)
            conn_info.message_count += 1

            return message

        except json.JSONDecodeError:
            await self._send_error(conn_info.websocket, "Invalid JSON")
            return None
        except (ValidationError, ValueError, TypeError) as e:
            logger.warning(
                "Message validation failed", error=str(e), client_id=client_id
            )
            await self._send_error(
                conn_info.websocket, f"Invalid message format: {str(e)}"
            )
            return None

    async def check_permission(self, client_id: str, permission: str) -> bool:
        """Перевірка дозволу для клієнта"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            return False

        return permission in conn_info.permissions

    async def handle_subscription(
        self, client_id: str, channel: str, subscribe: bool = True
    ) -> bool:
        """Управління підписками клієнта"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            return False

        # Ліміт кількості підписок на клієнта
        max_subs = int(os.getenv("WS_MAX_SUBSCRIPTIONS", "50"))
        if subscribe and len(conn_info.subscriptions) >= max_subs:
            await self._send_error(conn_info.websocket, "Too many subscriptions")
            return False

        # Перевірка дозволів на підписку
        channel_parts = channel.split(":")
        if channel_parts[0] == "tasks" and "tasks.view" not in conn_info.permissions:
            await self._send_error(
                conn_info.websocket, "Permission denied for tasks channel"
            )
            return False

        if subscribe:
            conn_info.subscriptions.add(channel)
            logger.info("Client subscribed", client_id=client_id, channel=channel)
        else:
            conn_info.subscriptions.discard(channel)
            logger.info("Client unsubscribed", client_id=client_id, channel=channel)

        # Зберігаємо в Redis
        if self.redis_client:
            sub_key = f"ws_subs:{client_id}"
            await self.redis_client.setex(
                sub_key, CONNECTION_TIMEOUT, json.dumps(list(conn_info.subscriptions))
            )

        return True

    async def broadcast_to_channel(
        self, channel: str, message: Dict, exclude_client: Optional[str] = None
    ):
        """Відправка повідомлення всім підписникам каналу"""
        sent_count = 0
        # Обмеження на розсилку у великий канал
        max_broadcast = int(os.getenv("WS_MAX_BROADCAST", "1000"))
        if len(self.connections) > max_broadcast:
            logger.warning(
                "Broadcast suppressed due to size limit",
                connections=len(self.connections),
            )
            return 0

        for client_id, conn_info in self.connections.items():
            if client_id == exclude_client:
                continue

            if channel in conn_info.subscriptions:
                try:
                    if conn_info.websocket.client_state == WebSocketState.CONNECTED:
                        await conn_info.websocket.send_json(message)
                        sent_count += 1
                    else:
                        # З'єднання не активне - помічаємо для видалення
                        logger.debug(
                            "Skipping send to inactive connection",
                            client_id=client_id,
                            state=conn_info.websocket.client_state.name,
                        )
                        await self.disconnect_client(client_id)
                except Exception as e:
                    logger.warning(
                        "Failed to send to client", client_id=client_id, error=str(e)
                    )
                    # Помічаємо з'єднання для видалення
                    await self.disconnect_client(client_id)

        logger.debug("Broadcast complete", channel=channel, sent_count=sent_count)
        return sent_count

    async def send_to_user(self, user_id: str, message: Dict):
        """Відправка повідомлення всім з'єднанням користувача"""
        client_ids = self.user_connections.get(user_id, [])

        for client_id in client_ids:
            conn_info = self.connections.get(client_id)
            if conn_info:
                try:
                    if conn_info.websocket.client_state == WebSocketState.CONNECTED:
                        await conn_info.websocket.send_json(message)
                    else:
                        logger.debug(
                            "Skipping send to inactive user connection",
                            client_id=client_id,
                            user_id=user_id,
                            state=conn_info.websocket.client_state.name,
                        )
                        await self.disconnect_client(client_id)
                except Exception as e:
                    logger.warning(
                        "Failed to send to user connection",
                        client_id=client_id,
                        error=str(e),
                    )
                    await self.disconnect_client(client_id)

    async def disconnect_client(self, client_id: str):
        """Відключення клієнта"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            return

        # Видаляємо з'єднання
        del self.connections[client_id]

        # Видаляємо з користувацьких з'єднань
        if conn_info.user_id in self.user_connections:
            self.user_connections[conn_info.user_id].remove(client_id)
            if not self.user_connections[conn_info.user_id]:
                del self.user_connections[conn_info.user_id]

        # Видаляємо з Redis
        if self.redis_client:
            await self.redis_client.delete(f"ws_conn:{client_id}")
            await self.redis_client.delete(f"ws_subs:{client_id}")

        # Закриваємо WebSocket
        try:
            await conn_info.websocket.close()
        except Exception:
            pass

        logger.info(
            "Client disconnected",
            client_id=client_id,
            user_id=conn_info.user_id,
            duration=(
                datetime.now(timezone.utc) - conn_info.connected_at
            ).total_seconds(),
        )

        # Якщо більше немає підключень — акуратно зупиняємо фоновий cleanup
        if (
            not self.connections
            and self._cleanup_task
            and not self._cleanup_task.done()
        ):
            try:
                self._cleanup_task.cancel()
            except Exception:
                pass
            finally:
                self._cleanup_task = None

    def _check_connection_limit(self, user_id: str) -> bool:
        """Перевірка ліміту з'єднань для користувача"""
        current_connections = len(self.user_connections.get(user_id, []))
        return current_connections < MAX_CONNECTIONS_PER_USER

    def _check_rate_limit(self, client_id: str) -> bool:
        """Перевірка rate limit для клієнта"""
        current_time = time.time()

        if client_id not in self.rate_limiters:
            self.rate_limiters[client_id] = []

        # Видаляємо старі записи
        self.rate_limiters[client_id] = [
            t for t in self.rate_limiters[client_id] if current_time - t < 1.0
        ]

        # Перевіряємо ліміт
        if len(self.rate_limiters[client_id]) >= MAX_MESSAGES_PER_SECOND:
            return False

        self.rate_limiters[client_id].append(current_time)
        return True

    async def _send_error(self, websocket: WebSocket, error_message: str):
        """Відправка повідомлення про помилку"""
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": error_message,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            else:
                logger.debug(
                    "Skipping error message send - WebSocket not connected",
                    state=websocket.client_state.name,
                    error=error_message,
                )
        except Exception as e:
            logger.debug(
                "Failed to send error message",
                error_message=error_message,
                websocket_error=str(e),
            )

    async def _cleanup_connections(self):
        """Періодичне очищення неактивних з'єднань"""
        while True:
            try:
                await asyncio.sleep(60)  # Перевірка кожну хвилину

                current_time = datetime.now(timezone.utc)
                disconnected = []

                for client_id, conn_info in self.connections.items():
                    # Перевірка таймауту
                    if (
                        current_time - conn_info.last_activity
                    ).total_seconds() > CONNECTION_TIMEOUT:
                        disconnected.append(client_id)
                        logger.info("Connection timeout", client_id=client_id)

                    # Відправка heartbeat
                    elif (
                        current_time - conn_info.last_activity
                    ).total_seconds() > HEARTBEAT_INTERVAL:
                        try:
                            # Перевіряємо стан WebSocket перед відправкою ping
                            if (
                                conn_info.websocket.client_state
                                == WebSocketState.CONNECTED
                            ):
                                await conn_info.websocket.send_json(
                                    {
                                        "type": "ping",
                                        "timestamp": current_time.isoformat(),
                                    }
                                )
                            else:
                                # З'єднання не активне - помічаємо для відключення
                                disconnected.append(client_id)
                        except Exception as e:
                            logger.debug(
                                "Failed to send heartbeat ping",
                                client_id=client_id,
                                error=str(e),
                            )
                            disconnected.append(client_id)

                # Відключаємо неактивні з'єднання
                for client_id in disconnected:
                    await self.disconnect_client(client_id)

            except Exception as e:
                logger.error("Cleanup error", error=str(e))

    async def get_connection_stats(self) -> Dict:
        """Отримання статистики з'єднань"""
        total_connections = len(self.connections)
        users_connected = len(self.user_connections)

        channels = {}
        for conn_info in self.connections.values():
            for channel in conn_info.subscriptions:
                channels[channel] = channels.get(channel, 0) + 1

        return {
            "total_connections": total_connections,
            "unique_users": users_connected,
            "channels": channels,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # ===================== INTERNAL HELPERS =====================
    def _is_rate_limited_ip(self, ip: str) -> bool:
        try:
            now = time.time()
            dq = self._conn_attempts_ip[ip]
            while dq and now - dq[0] > self._conn_window_seconds:
                dq.popleft()
            dq.append(now)
            return len(dq) > self._conn_max_per_window
        except Exception:
            return False

    def _record_token_attempt(self, token: str) -> None:
        try:
            tok_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            now = time.time()
            dq = self._conn_attempts_tok[tok_hash]
            while dq and now - dq[0] > self._conn_window_seconds:
                dq.popleft()
            dq.append(now)
        except Exception:
            pass

    def _is_rate_limited_token(self, token: str) -> bool:
        try:
            tok_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            dq = self._conn_attempts_tok.get(tok_hash)
            if not dq:
                return False
            return len(dq) > self._conn_max_per_window
        except Exception:
            return False

    def _validate_hmac_handshake(self, websocket: WebSocket, secret: str) -> bool:
        try:
            headers = getattr(websocket, "headers", None)
            client_id = self._get_header_ci(headers, "X-Client-Id")
            ts_str = self._get_header_ci(headers, "X-Timestamp")
            nonce = self._get_header_ci(headers, "X-Nonce")
            sig = self._get_header_ci(headers, "X-Signature")
            client_type = self._get_header_ci(headers, "X-Client-Type") or "service"
            client_version = self._get_header_ci(headers, "X-Client-Version") or "1.0.0"

            if not all([client_id, ts_str, nonce, sig]):
                logger.warning("Missing HMAC handshake headers")
                return False

            # Перевірка timestamp
            try:
                ts = int(ts_str)
            except ValueError:
                logger.warning("Invalid timestamp in HMAC handshake")
                return False
            now = int(time.time())
            if abs(now - ts) > HANDSHAKE_WINDOW_SECONDS:
                logger.warning("HMAC timestamp window exceeded", delta=abs(now - ts))
                return False

            # Перевірка nonce (replay protection)
            if not self._check_and_store_nonce(nonce):
                logger.warning("Replay detected: nonce reused")
                return False

            # Обчислення очікуваного підпису
            canonical = f"{client_id}|{ts_str}|{nonce}|{client_type}|{client_version}"
            expected = hmac.new(
                key=secret.encode("utf-8"),
                msg=canonical.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(expected, sig):
                logger.warning("Invalid HMAC signature")
                return False

            return True
        except Exception as e:
            logger.warning("HMAC handshake validation error", error=str(e))
            return False

    async def _validate_hmac_handshake_async(
        self, websocket: WebSocket, secret: str
    ) -> bool:
        try:
            headers = getattr(websocket, "headers", None)
            client_id = self._get_header_ci(headers, "X-Client-Id")
            ts_str = self._get_header_ci(headers, "X-Timestamp")
            nonce = self._get_header_ci(headers, "X-Nonce")
            sig = self._get_header_ci(headers, "X-Signature")
            client_type = self._get_header_ci(headers, "X-Client-Type") or "service"
            client_version = self._get_header_ci(headers, "X-Client-Version") or "1.0.0"

            if not all([client_id, ts_str, nonce, sig]):
                logger.warning("Missing HMAC handshake headers")
                return False

            try:
                ts = int(ts_str)
            except ValueError:
                logger.warning("Invalid timestamp in HMAC handshake")
                return False
            now = int(time.time())
            if abs(now - ts) > HANDSHAKE_WINDOW_SECONDS:
                logger.warning("HMAC timestamp window exceeded", delta=abs(now - ts))
                return False

            # Async перевірка nonce
            if not await self._check_and_store_nonce_async(nonce):
                logger.warning("Replay detected: nonce reused")
                await self._incr_metric("nonce_replay")
                return False

            canonical = f"{client_id}|{ts_str}|{nonce}|{client_type}|{client_version}"
            expected = hmac.new(
                key=secret.encode("utf-8"),
                msg=canonical.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, sig):
                logger.warning("Invalid HMAC signature")
                return False
            return True
        except Exception as e:
            logger.warning("HMAC handshake validation error", error=str(e))
            return False

    def _check_and_store_nonce(self, nonce: str) -> bool:
        try:
            now = time.time()
            # Якщо Redis доступний — використовуємо його
            if self.redis_client:
                key = f"ws_nonce:{nonce}"
                try:
                    res = self.redis_client.set(
                        key, "1", ex=self._nonce_ttl_seconds, nx=True
                    )
                except Exception:
                    res = None
                # Якщо не вдалося атомарно встановити або ключ уже існує — перевірка/retry
                try:
                    if not res:
                        exists = self.redis_client.get(key)
                        if exists:
                            return False
                        self.redis_client.set(key, "1", ex=self._nonce_ttl_seconds)
                except Exception:
                    # Якщо Redis недоступний – переходимо до in-memory
                    pass
                else:
                    # Якщо сюди дійшли без виключення — успіх
                    return True
                # Якщо сталася помилка вище – не повертаємо тут, дамо впасти на in-memory

            # In-memory fallback
            expired = [
                n
                for n, t in self._used_nonces.items()
                if now - t > self._nonce_ttl_seconds
            ]
            for n in expired:
                self._used_nonces.pop(n, None)
            if nonce in self._used_nonces:
                return False
            self._used_nonces[nonce] = now
            return True
        except Exception:
            return False

    async def _check_and_store_nonce_async(self, nonce: str) -> bool:
        try:
            now = time.time()
            if self.redis_client:
                key = f"ws_nonce:{nonce}"
                try:
                    res = await self.redis_client.set(
                        key, "1", ex=self._nonce_ttl_seconds, nx=True
                    )  # type: ignore
                    if not res:
                        return False
                except Exception:
                    # Якщо Redis недоступний – перевірка існування і повторна спроба
                    try:
                        exists = await self.redis_client.get(key)  # type: ignore
                        if exists:
                            return False
                        await self.redis_client.set(
                            key, "1", ex=self._nonce_ttl_seconds
                        )  # type: ignore
                    except Exception:
                        # перехід на in-memory
                        pass
                else:
                    return True

            # In-memory fallback
            expired = [
                n
                for n, t in self._used_nonces.items()
                if now - t > self._nonce_ttl_seconds
            ]
            for n in expired:
                self._used_nonces.pop(n, None)
            if nonce in self._used_nonces:
                return False
            self._used_nonces[nonce] = now
            return True
        except Exception:
            return False

    async def _incr_metric(self, name: str, amount: int = 1) -> None:
        try:
            if self.redis_client:
                await self.redis_client.incrby(f"metrics:{name}", amount)
        except Exception:
            pass


# Глобальний екземпляр менеджера
ws_security_manager = WebSocketSecurityManager()


# Декоратор для захищених WebSocket endpoints
def secure_websocket(permission: Optional[str] = None):
    """Декоратор для захисту WebSocket ендпоінтів"""

    def decorator(func):
        @wraps(func)
        async def wrapper(
            websocket: WebSocket, token: Optional[str] = Query(None), *args, **kwargs
        ):
            # Автентифікація
            user_data = await ws_security_manager.authenticate_websocket(
                websocket, token
            )
            if not user_data:
                await websocket.close(code=1008, reason="Authentication failed")
                return

            # Перевірка дозволів якщо потрібно
            if permission and permission not in user_data.get("permissions", []):
                await websocket.send_json(
                    {"type": "error", "error": f"Permission '{permission}' required"}
                )
                await websocket.close(code=1008, reason="Permission denied")
                return

            # Приймаємо з'єднання
            await websocket.accept()
            conn_info = await ws_security_manager.accept_connection(
                websocket, user_data
            )

            if not conn_info:
                await websocket.close(code=1008, reason="Connection rejected")
                return

            try:
                # Викликаємо оригінальну функцію
                await func(
                    websocket=websocket,
                    user_data=user_data,
                    client_id=conn_info.client_id,
                    *args,
                    **kwargs,
                )
            finally:
                # Завжди відключаємо при виході
                await ws_security_manager.disconnect_client(conn_info.client_id)

        return wrapper

    return decorator
