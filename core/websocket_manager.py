"""
TetraCore StreamHub WebSocket Manager

Менеджер для управління WebSocket з'єднаннями в StreamHub.
Забезпечує управління з'єднаннями, heartbeat, компресію та моніторинг.
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Set, Callable, Any
from collections import defaultdict
import structlog
import gzip
from fastapi import WebSocket, WebSocketDisconnect

from config import Settings


class WebSocketConnection:
    """Обгортка для WebSocket з'єднання з додатковими можливостями"""

    def __init__(self, websocket: WebSocket, client_id: str = None):
        self.websocket = websocket
        self.client_id = client_id
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.last_ping = None
        self.last_pong = None
        self.is_alive = True
        self.compression_enabled = False
        self.message_count = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.errors = 0

    async def send_json(self, data: Dict[str, Any], compress: bool = False):
        """Відправка JSON повідомлення"""
        try:
            message = json.dumps(data, default=str, ensure_ascii=False)

            if compress and self.compression_enabled and len(message) > 1024:
                # Компресія для великих повідомлень
                compressed = gzip.compress(message.encode("utf-8"))
                if len(compressed) < len(message):
                    await self.websocket.send_bytes(compressed)
                    self.bytes_sent += len(compressed)
                else:
                    await self.websocket.send_text(message)
                    self.bytes_sent += len(message)
            else:
                await self.websocket.send_text(message)
                self.bytes_sent += len(message)

            self.message_count += 1
            self.last_activity = datetime.utcnow()

        except Exception:
            self.errors += 1
            self.is_alive = False
            raise

    async def receive_json(self) -> Dict[str, Any]:
        """Отримання JSON повідомлення"""
        try:
            message = await self.websocket.receive()

            if message["type"] == "websocket.receive":
                if "text" in message:
                    data = message["text"]
                    self.bytes_received += len(data)
                elif "bytes" in message:
                    # Декомпресія якщо потрібно
                    data = gzip.decompress(message["bytes"]).decode("utf-8")
                    self.bytes_received += len(message["bytes"])
                else:
                    raise ValueError("No text or bytes in message")

                self.last_activity = datetime.utcnow()
                return json.loads(data)

            elif message["type"] == "websocket.disconnect":
                self.is_alive = False
                raise WebSocketDisconnect()

            else:
                raise ValueError(f"Unexpected message type: {message['type']}")

        except Exception as e:
            self.errors += 1
            if not isinstance(e, (WebSocketDisconnect, json.JSONDecodeError)):
                self.is_alive = False
            raise

    async def ping(self):
        """Відправка ping"""
        try:
            ping_data = {"type": "ping", "timestamp": datetime.utcnow().isoformat()}
            await self.send_json(ping_data)
            self.last_ping = datetime.utcnow()

        except Exception:
            self.is_alive = False
            raise

    async def pong(self):
        """Відправка pong у відповідь на ping"""
        try:
            pong_data = {"type": "pong", "timestamp": datetime.utcnow().isoformat()}
            await self.send_json(pong_data)
            self.last_pong = datetime.utcnow()

        except Exception:
            self.is_alive = False
            raise

    async def close(self, code: int = 1000, reason: str = "Normal closure"):
        """Закриття з'єднання"""
        try:
            await self.websocket.close(code, reason)
            self.is_alive = False
        except Exception:
            pass  # Ignore errors during close

    def is_healthy(self, timeout: int = 60) -> bool:
        """Перевірка здоров'я з'єднання"""
        if not self.is_alive:
            return False

        # Перевірка останньої активності
        inactive_time = (datetime.utcnow() - self.last_activity).total_seconds()
        return inactive_time < timeout

    def get_stats(self) -> Dict[str, Any]:
        """Статистика з'єднання"""
        uptime = (datetime.utcnow() - self.connected_at).total_seconds()

        return {
            "client_id": self.client_id,
            "connected_at": self.connected_at.isoformat(),
            "uptime_seconds": uptime,
            "last_activity": self.last_activity.isoformat(),
            "is_alive": self.is_alive,
            "message_count": self.message_count,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "errors": self.errors,
            "compression_enabled": self.compression_enabled,
            "last_ping": self.last_ping.isoformat() if self.last_ping else None,
            "last_pong": self.last_pong.isoformat() if self.last_pong else None,
        }


class WebSocketManager:
    """Менеджер WebSocket з'єднань StreamHub"""

    def __init__(self, settings: Settings):
        """Ініціалізація WebSocket менеджера"""
        self.settings = settings
        self.logger = structlog.get_logger(__name__)

        # Активні з'єднання
        self.connections: Dict[str, WebSocketConnection] = {}
        self.connections_by_client: Dict[str, str] = {}  # client_id -> connection_id

        # Статистика
        self.total_connections = 0
        self.total_disconnections = 0
        self.total_messages_sent = 0
        self.total_messages_received = 0
        self.peak_connections = 0

        # Event handlers
        self.on_connection_opened: Optional[Callable] = None
        self.on_connection_closed: Optional[Callable] = None
        self.on_message_received: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # Стан менеджера
        self.is_running = False
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Ініціалізація менеджера"""
        try:
            self.logger.info("Initializing WebSocket Manager")

            # Запуск фонових задач
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self.cleanup_task = asyncio.create_task(self._cleanup_loop())

            self.is_running = True
            self.logger.info("WebSocket Manager initialized successfully")

        except Exception as e:
            self.logger.error("Failed to initialize WebSocket Manager", error=str(e))
            raise

    async def shutdown(self):
        """Зупинка менеджера"""
        self.logger.info("Shutting down WebSocket Manager")

        self.is_running = False

        # Зупинка фонових задач
        for task in [self.heartbeat_task, self.cleanup_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Закриття всіх з'єднань
        await self._close_all_connections()

        self.logger.info("WebSocket Manager shutdown complete")

    async def add_connection(self, websocket: WebSocket, client_id: str = None) -> str:
        """Додавання нового WebSocket з'єднання"""
        try:
            # Генерація унікального ID з'єднання
            connection_id = (
                f"ws_{datetime.utcnow().timestamp()}_{len(self.connections)}"
            )

            # Перевірка ліміту з'єднань
            if len(self.connections) >= self.settings.max_connections:
                await websocket.close(4008, "Maximum connections exceeded")
                self.logger.warning(
                    "Connection rejected: max connections exceeded",
                    connection_id=connection_id,
                )
                return None

            # Створення з'єднання
            connection = WebSocketConnection(websocket, client_id)

            # Увімкнення компресії якщо налаштовано
            if self.settings.enable_compression:
                connection.compression_enabled = True

            # Додавання до сховища
            self.connections[connection_id] = connection

            if client_id:
                # Закриття попереднього з'єднання клієнта якщо є
                if client_id in self.connections_by_client:
                    old_connection_id = self.connections_by_client[client_id]
                    await self.remove_connection(
                        old_connection_id, "New connection established"
                    )

                self.connections_by_client[client_id] = connection_id

            # Оновлення статистики
            self.total_connections += 1
            current_count = len(self.connections)
            if current_count > self.peak_connections:
                self.peak_connections = current_count

            # Виклик callback
            if self.on_connection_opened:
                await self.on_connection_opened(connection_id, client_id)

            self.logger.info(
                "WebSocket connection added",
                connection_id=connection_id,
                client_id=client_id,
                total_connections=len(self.connections),
            )

            return connection_id

        except Exception as e:
            self.logger.error(
                "Failed to add WebSocket connection", client_id=client_id, error=str(e)
            )
            try:
                await websocket.close(4000, "Internal server error")
            except Exception:
                pass
            return None

    async def remove_connection(
        self, connection_id: str, reason: str = "Connection closed"
    ) -> bool:
        """Видалення WebSocket з'єднання"""
        try:
            if connection_id not in self.connections:
                return False

            connection = self.connections[connection_id]
            client_id = connection.client_id

            # Закриття з'єднання
            await connection.close(1000, reason)

            # Видалення з сховища
            del self.connections[connection_id]

            if client_id and client_id in self.connections_by_client:
                if self.connections_by_client[client_id] == connection_id:
                    del self.connections_by_client[client_id]

            # Оновлення статистики
            self.total_disconnections += 1

            # Виклик callback
            if self.on_connection_closed:
                await self.on_connection_closed(connection_id, client_id, reason)

            self.logger.info(
                "WebSocket connection removed",
                connection_id=connection_id,
                client_id=client_id,
                reason=reason,
                total_connections=len(self.connections),
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to remove WebSocket connection",
                connection_id=connection_id,
                error=str(e),
            )
            return False

    async def send_to_connection(
        self, connection_id: str, message: Dict[str, Any]
    ) -> bool:
        """Відправка повідомлення конкретному з'єднанню"""
        try:
            if connection_id not in self.connections:
                return False

            connection = self.connections[connection_id]

            if not connection.is_alive:
                await self.remove_connection(connection_id, "Connection not alive")
                return False

            await connection.send_json(message, compress=True)
            self.total_messages_sent += 1

            return True

        except Exception as e:
            self.logger.error(
                "Failed to send message to connection",
                connection_id=connection_id,
                error=str(e),
            )

            # Видалення неробочого з'єднання
            await self.remove_connection(connection_id, f"Send error: {str(e)}")
            return False

    async def send_to_client(self, client_id: str, message: Dict[str, Any]) -> bool:
        """Відправка повідомлення клієнту за ID"""
        try:
            if client_id not in self.connections_by_client:
                self.logger.warning("Client not found", client_id=client_id)
                return False

            connection_id = self.connections_by_client[client_id]
            return await self.send_to_connection(connection_id, message)

        except Exception as e:
            self.logger.error(
                "Failed to send message to client", client_id=client_id, error=str(e)
            )
            return False

    async def broadcast(
        self,
        message: Dict[str, Any],
        exclude_connections: Set[str] = None,
        exclude_clients: Set[str] = None,
    ) -> int:
        """Широкомовна розсилка повідомлення"""
        try:
            exclude_connections = exclude_connections or set()
            exclude_clients = exclude_clients or set()

            sent_count = 0
            failed_count = 0

            for connection_id, connection in list(self.connections.items()):
                # Перевірка виключень
                if connection_id in exclude_connections:
                    continue

                if connection.client_id and connection.client_id in exclude_clients:
                    continue

                # Відправка повідомлення
                try:
                    if await self.send_to_connection(connection_id, message):
                        sent_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
                    self.logger.debug(
                        "Failed to send broadcast message",
                        connection_id=connection_id,
                        error=str(e),
                    )

            if sent_count or failed_count:
                self.logger.info(
                    "Broadcast completed",
                    sent=sent_count,
                    failed=failed_count,
                    total_connections=len(self.connections),
                )

            return sent_count

        except Exception as e:
            self.logger.error("Failed to broadcast message", error=str(e))
            return 0

    async def receive_from_connection(
        self, connection_id: str
    ) -> Optional[Dict[str, Any]]:
        """Отримання повідомлення від з'єднання"""
        try:
            if connection_id not in self.connections:
                return None

            connection = self.connections[connection_id]

            if not connection.is_alive:
                await self.remove_connection(connection_id, "Connection not alive")
                return None

            message = await connection.receive_json()
            self.total_messages_received += 1

            # Виклик callback
            if self.on_message_received:
                await self.on_message_received(connection_id, message)

            return message

        except WebSocketDisconnect:
            await self.remove_connection(connection_id, "Client disconnected")
            return None
        except Exception as e:
            self.logger.error(
                "Failed to receive message from connection",
                connection_id=connection_id,
                error=str(e),
            )
            await self.remove_connection(connection_id, f"Receive error: {str(e)}")
            return None

    async def ping_connection(self, connection_id: str) -> bool:
        """Ping конкретного з'єднання"""
        try:
            if connection_id not in self.connections:
                return False

            connection = self.connections[connection_id]
            await connection.ping()
            return True

        except Exception as e:
            self.logger.error(
                "Failed to ping connection", connection_id=connection_id, error=str(e)
            )
            await self.remove_connection(connection_id, f"Ping error: {str(e)}")
            return False

    async def ping_all_connections(self) -> Dict[str, bool]:
        """Ping всіх з'єднань"""
        results = {}

        for connection_id in list(self.connections.keys()):
            results[connection_id] = await self.ping_connection(connection_id)

        return results

    def get_connection(self, connection_id: str) -> Optional[WebSocketConnection]:
        """Отримання з'єднання за ID"""
        return self.connections.get(connection_id)

    def get_connection_by_client(self, client_id: str) -> Optional[WebSocketConnection]:
        """Отримання з'єднання за ID клієнта"""
        connection_id = self.connections_by_client.get(client_id)
        if connection_id:
            return self.connections.get(connection_id)
        return None

    def get_all_connections(self) -> List[WebSocketConnection]:
        """Отримання всіх з'єднань"""
        return list(self.connections.values())

    def get_healthy_connections(self) -> List[WebSocketConnection]:
        """Отримання здорових з'єднань"""
        healthy = []
        for connection in self.connections.values():
            if connection.is_healthy(self.settings.websocket_timeout):
                healthy.append(connection)
        return healthy

    def get_connection_count(self) -> int:
        """Кількість активних з'єднань"""
        return len(self.connections)

    def get_stats(self) -> Dict[str, Any]:
        """Статистика менеджера"""
        healthy_count = len(self.get_healthy_connections())

        # Статистика по клієнтах
        client_stats = defaultdict(int)
        for connection in self.connections.values():
            if connection.client_id:
                client_stats["with_client_id"] += 1
            else:
                client_stats["anonymous"] += 1

        # Статистика трафіку
        total_bytes_sent = sum(conn.bytes_sent for conn in self.connections.values())
        total_bytes_received = sum(
            conn.bytes_received for conn in self.connections.values()
        )
        total_errors = sum(conn.errors for conn in self.connections.values())

        return {
            "total_connections": len(self.connections),
            "healthy_connections": healthy_count,
            "peak_connections": self.peak_connections,
            "total_connections_ever": self.total_connections,
            "total_disconnections": self.total_disconnections,
            "total_messages_sent": self.total_messages_sent,
            "total_messages_received": self.total_messages_received,
            "total_bytes_sent": total_bytes_sent,
            "total_bytes_received": total_bytes_received,
            "total_errors": total_errors,
            "client_stats": dict(client_stats),
            "is_running": self.is_running,
        }

    def is_healthy(self) -> bool:
        """Перевірка здоров'я менеджера"""
        return (
            self.is_running
            and self.heartbeat_task is not None
            and not self.heartbeat_task.done()
            and self.cleanup_task is not None
            and not self.cleanup_task.done()
        )

    async def _heartbeat_loop(self):
        """Фонова задача heartbeat"""
        while self.is_running:
            try:
                await self.ping_all_connections()
                await asyncio.sleep(self.settings.websocket_heartbeat_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in heartbeat loop", error=str(e))
                await asyncio.sleep(10)

    async def _cleanup_loop(self):
        """Фонова задача очищення"""
        while self.is_running:
            try:
                await self._cleanup_unhealthy_connections()
                await asyncio.sleep(30)  # Очищення кожні 30 секунд

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(10)

    async def _cleanup_unhealthy_connections(self):
        """Очищення нездорових з'єднань"""
        try:
            unhealthy_connections = []

            for connection_id, connection in list(self.connections.items()):
                if not connection.is_healthy(self.settings.websocket_timeout):
                    unhealthy_connections.append(connection_id)

            for connection_id in unhealthy_connections:
                await self.remove_connection(connection_id, "Connection unhealthy")

            if unhealthy_connections:
                self.logger.info(
                    "Cleaned up unhealthy connections", count=len(unhealthy_connections)
                )

        except Exception as e:
            self.logger.error("Error cleaning up unhealthy connections", error=str(e))

    async def _close_all_connections(self):
        """Закриття всіх з'єднань"""
        try:
            connection_ids = list(self.connections.keys())

            for connection_id in connection_ids:
                await self.remove_connection(connection_id, "Server shutdown")

            self.logger.info(
                "All WebSocket connections closed", count=len(connection_ids)
            )

        except Exception as e:
            self.logger.error("Error closing all connections", error=str(e))

    def __len__(self) -> int:
        """Кількість з'єднань"""
        return len(self.connections)

    def __contains__(self, connection_id: str) -> bool:
        """Перевірка наявності з'єднання"""
        return connection_id in self.connections
