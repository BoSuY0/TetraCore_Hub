"""
WebSocket Security Middleware for TetraCore Hub
Захист WebSocket з'єднань з JWT автентифікацією та валідацією
"""

import json
import time
import asyncio
from typing import Dict, Optional, List, Set, Any
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import hmac
from urllib.parse import parse_qs

from fastapi import WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.websockets import WebSocketState
import structlog
import redis
from pydantic import BaseModel, Field, validator
import jwt

from core.auth_manager import get_auth_manager, initialize_auth_manager_redis

logger = structlog.get_logger()

# Константи безпеки
MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB
MAX_MESSAGES_PER_SECOND = 10
MAX_CONNECTIONS_PER_USER = 20  # Збільшено для development
CONNECTION_TIMEOUT = 300  # 5 хвилин
HEARTBEAT_INTERVAL = 30  # 30 секунд
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_WINDOW = 60  # 1 хвилина


class WebSocketMessage(BaseModel):
    """Базова модель для WebSocket повідомлень"""
    type: str = Field(..., max_length=50)
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message_id: Optional[str] = None
    correlation_id: Optional[str] = None

    @validator('type')
    def validate_type(cls, v):
        allowed_types = [
            'ping', 'pong', 'subscribe', 'unsubscribe',
            'task_update', 'status_update', 'error',
            'auth', 'client_info', 'metrics',
            'client_registration', 'registration_ack', 'registration_error',
            'task_submit', 'task_assign', 'task_result',
            'health_check', 'health_status', 'broadcast',
            'system_notification', 'stats_update'
        ]
        if v not in allowed_types:
            raise ValueError(f'Invalid message type: {v}')
        return v

    @validator('data')
    def validate_data_size(cls, v):
        # Перевірка розміру даних
        data_str = json.dumps(v)
        if len(data_str) > MAX_MESSAGE_SIZE:
            raise ValueError(f'Message too large: {len(data_str)} bytes')
        return v


class ConnectionInfo:
    """Інформація про WebSocket з'єднання"""
    def __init__(self, websocket: WebSocket, user_id: str, client_id: str):
        self.websocket = websocket
        self.user_id = user_id
        self.client_id = client_id
        self.connected_at = datetime.now(timezone.utc)
        self.last_activity = datetime.now(timezone.utc)
        self.message_count = 0
        self.last_message_time = time.time()
        self.subscriptions: Set[str] = set()
        self.permissions: List[str] = []
        self.metadata: Dict[str, Any] = {}


class WebSocketSecurityManager:
    """Менеджер безпеки для WebSocket з'єднань"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.connections: Dict[str, ConnectionInfo] = {}
        self.user_connections: Dict[str, List[str]] = {}
        self.rate_limiters: Dict[str, List[float]] = {}
        self._cleanup_task = None

    async def authenticate_websocket(self, websocket: WebSocket, token: Optional[str]) -> Optional[Dict]:
        """Автентифікація WebSocket з'єднання"""
        import os
        import time
        from config import get_settings
        
        environment = os.getenv("ENVIRONMENT", "development")
        settings = get_settings()
        
        # В development режимі дозволяємо підключення без токена для тестування
        if not token:
            if environment == "development":
                logger.info("WebSocket connection in development mode without token - allowing guest access")
                return {
                    "user_id": "guest",
                    "username": "guest", 
                    "role": "viewer",
                    "permissions": ["tasks.view", "clients.view"],
                    "session_id": f"guest-{int(time.time())}"
                }
            else:
                logger.warning("WebSocket authentication failed: no token provided")
                return None

        # Спочатку перевіряємо чи це статичний AUTH_TOKEN для ботів
        if settings.auth_token and token == settings.auth_token:
            logger.info("WebSocket authentication successful with static AUTH_TOKEN", 
                       token_preview=token[:8] + "..." if len(token) > 8 else token)
            return {
                "user_id": "bot_client",
                "username": "bot_client",
                "role": "bot",
                "permissions": ["tasks.view", "tasks.execute", "clients.view"],
                "session_id": f"bot-{int(time.time())}"
            }

        try:
            # Валідація JWT токена для Dashboard/Monitor клієнтів
            auth_mgr = get_auth_manager()
            
            # Ініціалізуємо Redis якщо потрібно
            if auth_mgr.redis_client is None:
                try:
                    await initialize_auth_manager_redis()
                except Exception as e:
                    logger.warning("Could not initialize Redis for WebSocket auth", error=str(e))

            
            payload = await auth_mgr.decode_token(token)
            
            logger.info("WebSocket authentication successful with JWT token", 
                       user_id=payload.get("user_id"),
                       username=payload.get("username"))

            return {
                "user_id": payload.get("user_id"),
                "username": payload.get("username"),
                "role": payload.get("role"),
                "permissions": payload.get("permissions", []),
                "session_id": payload.get("session_id")
            }

        except Exception as e:
            # В development режимі також дозволяємо fallback на guest
            if environment == "development":
                logger.warning("WebSocket authentication failed, falling back to guest access", 
                             error=str(e),
                             token_preview=token[:20] + "..." if len(token) > 20 else token)
                return {
                    "user_id": "guest",
                    "username": "guest",
                    "role": "viewer", 
                    "permissions": ["tasks.view", "clients.view"],
                    "session_id": f"guest-fallback-{int(time.time())}"
                }
            else:
                logger.warning("WebSocket authentication failed", 
                             error=str(e),
                             token_preview=token[:20] + "..." if len(token) > 20 else token)
                return None

    async def accept_connection(self, websocket: WebSocket, user_data: Dict) -> Optional[ConnectionInfo]:
        """Прийняття та реєстрація WebSocket з'єднання"""
        user_id = user_data["user_id"]
        client_id = f"{user_id}:{user_data['session_id']}:{time.time()}"

        # Перевірка кількості з'єднань користувача
        current_connections = len(self.user_connections.get(user_id, []))
        if not self._check_connection_limit(user_id):
            logger.warning("WebSocket connection limit exceeded",
                         user_id=user_id,
                         current_connections=current_connections,
                         max_connections=MAX_CONNECTIONS_PER_USER)
            await self._send_error(websocket, "Too many connections")
            return None
        
        logger.info("WebSocket connection limit check passed",
                   user_id=user_id,
                   current_connections=current_connections,
                   max_connections=MAX_CONNECTIONS_PER_USER)

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
                "permissions": conn_info.permissions
            }
            await self.redis_client.setex(conn_key, CONNECTION_TIMEOUT, json.dumps(conn_data))

        logger.info("WebSocket connection accepted",
                   client_id=client_id,
                   user_id=user_id,
                   total_connections=len(self.connections))

        # Запускаємо cleanup якщо ще не запущений
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_connections())

        return conn_info

    async def validate_message(self, client_id: str, raw_message: str) -> Optional[WebSocketMessage]:
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
            message_data = json.loads(raw_message)
            message = WebSocketMessage(**message_data)

            # Оновлюємо статистику
            conn_info.last_activity = datetime.now(timezone.utc)
            conn_info.message_count += 1

            return message

        except json.JSONDecodeError:
            await self._send_error(conn_info.websocket, "Invalid JSON")
            return None
        except Exception as e:
            logger.warning("Message validation failed", error=str(e), client_id=client_id)
            await self._send_error(conn_info.websocket, f"Invalid message format: {str(e)}")
            return None

    async def check_permission(self, client_id: str, permission: str) -> bool:
        """Перевірка дозволу для клієнта"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            return False

        return permission in conn_info.permissions

    async def handle_subscription(self, client_id: str, channel: str, subscribe: bool = True) -> bool:
        """Управління підписками клієнта"""
        conn_info = self.connections.get(client_id)
        if not conn_info:
            return False

        # Перевірка дозволів на підписку
        channel_parts = channel.split(":")
        if channel_parts[0] == "tasks" and "tasks.view" not in conn_info.permissions:
            await self._send_error(conn_info.websocket, "Permission denied for tasks channel")
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
            await self.redis_client.setex(sub_key, CONNECTION_TIMEOUT,
                                  json.dumps(list(conn_info.subscriptions)))

        return True

    async def broadcast_to_channel(self, channel: str, message: Dict, exclude_client: Optional[str] = None):
        """Відправка повідомлення всім підписникам каналу"""
        sent_count = 0

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
                        logger.debug("Skipping send to inactive connection",
                                   client_id=client_id,
                                   state=conn_info.websocket.client_state.name)
                        await self.disconnect_client(client_id)
                except Exception as e:
                    logger.warning("Failed to send to client",
                                 client_id=client_id,
                                 error=str(e))
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
                        logger.debug("Skipping send to inactive user connection",
                                   client_id=client_id,
                                   user_id=user_id,
                                   state=conn_info.websocket.client_state.name)
                        await self.disconnect_client(client_id)
                except Exception as e:
                    logger.warning("Failed to send to user connection",
                                 client_id=client_id,
                                 error=str(e))
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
        except:
            pass

        logger.info("Client disconnected",
                   client_id=client_id,
                   user_id=conn_info.user_id,
                   duration=(datetime.now(timezone.utc) - conn_info.connected_at).total_seconds())

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
            t for t in self.rate_limiters[client_id]
            if current_time - t < 1.0
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
                await websocket.send_json({
                    "type": "error",
                    "error": error_message,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            else:
                logger.debug("Skipping error message send - WebSocket not connected",
                           state=websocket.client_state.name,
                           error=error_message)
        except Exception as e:
            logger.debug("Failed to send error message", 
                        error_message=error_message,
                        websocket_error=str(e))

    async def _cleanup_connections(self):
        """Періодичне очищення неактивних з'єднань"""
        while True:
            try:
                await asyncio.sleep(60)  # Перевірка кожну хвилину

                current_time = datetime.now(timezone.utc)
                disconnected = []

                for client_id, conn_info in self.connections.items():
                    # Перевірка таймауту
                    if (current_time - conn_info.last_activity).total_seconds() > CONNECTION_TIMEOUT:
                        disconnected.append(client_id)
                        logger.info("Connection timeout", client_id=client_id)

                    # Відправка heartbeat
                    elif (current_time - conn_info.last_activity).total_seconds() > HEARTBEAT_INTERVAL:
                        try:
                            # Перевіряємо стан WebSocket перед відправкою ping
                            if conn_info.websocket.client_state == WebSocketState.CONNECTED:
                                await conn_info.websocket.send_json({
                                    "type": "ping",
                                    "timestamp": current_time.isoformat()
                                })
                            else:
                                # З'єднання не активне - помічаємо для відключення
                                disconnected.append(client_id)
                        except Exception as e:
                            logger.debug("Failed to send heartbeat ping", 
                                       client_id=client_id, 
                                       error=str(e))
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
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Глобальний екземпляр менеджера
ws_security_manager = WebSocketSecurityManager()


# Декоратор для захищених WebSocket endpoints
def secure_websocket(permission: Optional[str] = None):
    """Декоратор для захисту WebSocket ендпоінтів"""
    def decorator(func):
        @wraps(func)
        async def wrapper(websocket: WebSocket, token: Optional[str] = Query(None), *args, **kwargs):
            # Автентифікація
            user_data = await ws_security_manager.authenticate_websocket(websocket, token)
            if not user_data:
                await websocket.close(code=1008, reason="Authentication failed")
                return

            # Перевірка дозволів якщо потрібно
            if permission and permission not in user_data.get("permissions", []):
                await websocket.send_json({
                    "type": "error",
                    "error": f"Permission '{permission}' required"
                })
                await websocket.close(code=1008, reason="Permission denied")
                return

            # Приймаємо з'єднання
            await websocket.accept()
            conn_info = await ws_security_manager.accept_connection(websocket, user_data)

            if not conn_info:
                await websocket.close(code=1008, reason="Connection rejected")
                return

            try:
                # Викликаємо оригінальну функцію
                await func(websocket=websocket, user_data=user_data,
                         client_id=conn_info.client_id, *args, **kwargs)
            finally:
                # Завжди відключаємо при виході
                await ws_security_manager.disconnect_client(conn_info.client_id)

        return wrapper
    return decorator
