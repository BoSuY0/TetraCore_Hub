"""
WebSocket Connection Pool Manager for TetraCore Hub
Ефективне управління пулом WebSocket з'єднань з чергами та обмеженнями
"""

import asyncio
import time
import uuid
from typing import Dict, Optional, Set, Any, Callable
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from contextlib import asynccontextmanager

from fastapi import WebSocket
import structlog

logger = structlog.get_logger()

# Константи для pooling
DEFAULT_POOL_SIZE = 100
MAX_POOL_SIZE = 1000
MIN_POOL_SIZE = 10
DEFAULT_MAX_CONNECTIONS_PER_CLIENT = 5
DEFAULT_QUEUE_SIZE = 50
CONNECTION_IDLE_TIMEOUT = 300  # 5 хвилин
CONNECTION_MAX_LIFETIME = 3600  # 1 година
HEALTH_CHECK_INTERVAL = 30  # 30 секунд
CLEANUP_INTERVAL = 60  # 1 хвилина
MAX_RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1.0  # Початкова затримка для reconnect


class ConnectionState(Enum):
    """Стани WebSocket з'єднання"""

    PENDING = "pending"
    ACTIVE = "active"
    IDLE = "idle"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class ConnectionPriority(Enum):
    """Пріоритети з'єднань"""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class PooledConnection:
    """WebSocket з'єднання в пулі"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    websocket: WebSocket = None
    client_id: Optional[str] = None
    client_type: Optional[str] = None
    state: ConnectionState = ConnectionState.PENDING
    priority: ConnectionPriority = ConnectionPriority.NORMAL
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)
    last_health_check: Optional[datetime] = None
    message_count: int = 0
    error_count: int = 0
    reconnect_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def age(self) -> float:
        """Вік з'єднання в секундах"""
        return (datetime.utcnow() - self.created_at).total_seconds()

    @property
    def idle_time(self) -> float:
        """Час неактивності в секундах"""
        return (datetime.utcnow() - self.last_active).total_seconds()

    @property
    def is_idle(self) -> bool:
        """Чи є з'єднання неактивним"""
        return (
            self.state == ConnectionState.IDLE
            and self.idle_time > CONNECTION_IDLE_TIMEOUT
        )

    @property
    def is_expired(self) -> bool:
        """Чи закінчився термін життя з'єднання"""
        return self.age > CONNECTION_MAX_LIFETIME

    def update_activity(self):
        """Оновлення часу останньої активності"""
        self.last_active = datetime.utcnow()
        self.message_count += 1


@dataclass
class ConnectionRequest:
    """Запит на з'єднання"""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str = None
    client_type: str = None
    priority: ConnectionPriority = ConnectionPriority.NORMAL
    callback: Optional[Callable] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout: float = 30.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Чи закінчився таймаут запиту"""
        return (datetime.utcnow() - self.created_at).total_seconds() > self.timeout


class ConnectionPool:
    """Пул WebSocket з'єднань з чергами та оптимізаціями"""

    def __init__(
        self,
        pool_size: int = DEFAULT_POOL_SIZE,
        max_connections_per_client: int = DEFAULT_MAX_CONNECTIONS_PER_CLIENT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        enable_health_checks: bool = True,
        enable_auto_scaling: bool = True,
    ):
        # Конфігурація
        self.pool_size = min(max(pool_size, MIN_POOL_SIZE), MAX_POOL_SIZE)
        self.max_connections_per_client = max_connections_per_client
        self.queue_size = queue_size
        self.enable_health_checks = enable_health_checks
        self.enable_auto_scaling = enable_auto_scaling

        # Пули з'єднань
        self.active_connections: Dict[str, PooledConnection] = {}
        self.idle_connections: deque[PooledConnection] = deque()
        self.client_connections: Dict[str, Set[str]] = {}

        # Черги
        self.pending_requests: deque[ConnectionRequest] = deque()
        self.priority_queue: Dict[ConnectionPriority, deque[ConnectionRequest]] = {
            priority: deque() for priority in ConnectionPriority
        }

        # Метрики
        self.metrics = {
            "total_connections": 0,
            "active_connections": 0,
            "idle_connections": 0,
            "queued_requests": 0,
            "rejected_requests": 0,
            "recycled_connections": 0,
            "failed_health_checks": 0,
            "total_messages": 0,
        }

        # Блокування для thread-safety
        self._lock = asyncio.Lock()

        # Background tasks
        self._health_check_task = None
        self._cleanup_task = None
        self._auto_scale_task = None

        # Callbacks
        self.on_connection_acquired: Optional[Callable] = None
        self.on_connection_released: Optional[Callable] = None
        self.on_connection_error: Optional[Callable] = None

        logger.info(
            "Connection pool initialized",
            pool_size=self.pool_size,
            max_per_client=self.max_connections_per_client,
        )

    async def start(self):
        """Запуск background tasks"""
        if self.enable_health_checks:
            self._health_check_task = asyncio.create_task(self._health_check_loop())

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        if self.enable_auto_scaling:
            self._auto_scale_task = asyncio.create_task(self._auto_scale_loop())

        logger.info("Connection pool started")

    async def stop(self):
        """Зупинка pool та закриття всіх з'єднань"""
        # Відміна background tasks
        tasks = [self._health_check_task, self._cleanup_task, self._auto_scale_task]
        for task in tasks:
            if task:
                task.cancel()

        # Закриття всіх з'єднань
        async with self._lock:
            all_connections = list(self.active_connections.values()) + list(
                self.idle_connections
            )

            for conn in all_connections:
                await self._close_connection(conn)

            self.active_connections.clear()
            self.idle_connections.clear()
            self.client_connections.clear()

        logger.info("Connection pool stopped")

    async def acquire(
        self,
        websocket: WebSocket,
        client_id: str,
        client_type: str = "unknown",
        priority: ConnectionPriority = ConnectionPriority.NORMAL,
        timeout: float = 30.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[PooledConnection]:
        """Отримання з'єднання з пулу або створення нового"""
        async with self._lock:
            # Перевірка ліміту для клієнта
            client_conn_count = len(self.client_connections.get(client_id, set()))
            if client_conn_count >= self.max_connections_per_client:
                logger.warning(
                    "Client connection limit reached",
                    client_id=client_id,
                    limit=self.max_connections_per_client,
                )

                # Додаємо в чергу якщо є місце
                if len(self.pending_requests) < self.queue_size:
                    request = ConnectionRequest(
                        client_id=client_id,
                        client_type=client_type,
                        priority=priority,
                        timeout=timeout,
                        metadata=metadata or {},
                    )
                    self._enqueue_request(request)

                    # Чекаємо на з'єднання
                    return await self._wait_for_connection(request)
                else:
                    self.metrics["rejected_requests"] += 1
                    return None

            # Спробуємо використати idle з'єднання
            conn = self._get_idle_connection(client_type)
            if conn:
                conn.websocket = websocket
                conn.client_id = client_id
                conn.client_type = client_type
                conn.state = ConnectionState.ACTIVE
                conn.reconnect_count = 0
                self.metrics["recycled_connections"] += 1
                logger.debug("Recycled idle connection", conn_id=conn.id)
            else:
                # Створюємо нове з'єднання
                if (
                    len(self.active_connections) + len(self.idle_connections)
                    >= self.pool_size
                ):
                    # Pool повний, додаємо в чергу
                    request = ConnectionRequest(
                        client_id=client_id,
                        client_type=client_type,
                        priority=priority,
                        timeout=timeout,
                        metadata=metadata or {},
                    )
                    self._enqueue_request(request)
                    return await self._wait_for_connection(request)

                # Створюємо нове з'єднання
                conn = PooledConnection(
                    websocket=websocket,
                    client_id=client_id,
                    client_type=client_type,
                    state=ConnectionState.ACTIVE,
                    priority=priority,
                    metadata=metadata or {},
                )
                self.metrics["total_connections"] += 1

            # Реєструємо з'єднання
            self.active_connections[conn.id] = conn

            if client_id not in self.client_connections:
                self.client_connections[client_id] = set()
            self.client_connections[client_id].add(conn.id)

            self.metrics["active_connections"] = len(self.active_connections)

            # Callback
            if self.on_connection_acquired:
                await self.on_connection_acquired(conn)

            logger.info(
                "Connection acquired",
                conn_id=conn.id,
                client_id=client_id,
                active=len(self.active_connections),
            )

            return conn

    async def release(self, conn_id: str, close: bool = False):
        """Повернення з'єднання в пул або закриття"""
        async with self._lock:
            conn = self.active_connections.get(conn_id)
            if not conn:
                logger.warning(
                    "Attempted to release unknown connection", conn_id=conn_id
                )
                return

            # Видаляємо з активних
            del self.active_connections[conn_id]
            self.metrics["active_connections"] = len(self.active_connections)

            # Видаляємо з client connections
            if conn.client_id in self.client_connections:
                self.client_connections[conn.client_id].discard(conn_id)
                if not self.client_connections[conn.client_id]:
                    del self.client_connections[conn.client_id]

            # Вирішуємо що робити з з'єднанням
            if close or conn.is_expired or conn.error_count > 3:
                await self._close_connection(conn)
            else:
                # Повертаємо в idle pool
                conn.state = ConnectionState.IDLE
                conn.client_id = None
                self.idle_connections.append(conn)
                self.metrics["idle_connections"] = len(self.idle_connections)

            # Callback
            if self.on_connection_released:
                await self.on_connection_released(conn)

            # Обробляємо чергу запитів
            await self._process_queue()

            logger.info(
                "Connection released",
                conn_id=conn_id,
                closed=close,
                idle=len(self.idle_connections),
            )

    async def send_message(self, conn_id: str, message: Dict[str, Any]) -> bool:
        """Відправка повідомлення через pooled connection"""
        conn = self.active_connections.get(conn_id)
        if not conn or conn.state != ConnectionState.ACTIVE:
            logger.warning("Cannot send to inactive connection", conn_id=conn_id)
            return False

        try:
            await conn.websocket.send_json(message)
            conn.update_activity()
            self.metrics["total_messages"] += 1
            return True
        except Exception as e:
            logger.error("Error sending message", conn_id=conn_id, error=str(e))
            conn.error_count += 1
            conn.state = ConnectionState.ERROR

            if self.on_connection_error:
                await self.on_connection_error(conn, e)

            return False

    async def broadcast(
        self,
        message: Dict[str, Any],
        client_type: Optional[str] = None,
        exclude: Optional[Set[str]] = None,
    ) -> int:
        """Broadcast повідомлення до всіх активних з'єднань"""
        sent_count = 0
        exclude = exclude or set()

        for conn_id, conn in self.active_connections.items():
            if conn_id in exclude:
                continue

            if client_type and conn.client_type != client_type:
                continue

            if await self.send_message(conn_id, message):
                sent_count += 1

        return sent_count

    def _get_idle_connection(
        self, preferred_type: Optional[str] = None
    ) -> Optional[PooledConnection]:
        """Отримання idle з'єднання з пулу"""
        if not self.idle_connections:
            return None

        # Шукаємо з'єднання потрібного типу
        if preferred_type:
            for i, conn in enumerate(self.idle_connections):
                if conn.client_type == preferred_type and not conn.is_expired:
                    self.idle_connections.remove(conn)
                    self.metrics["idle_connections"] = len(self.idle_connections)
                    return conn

        # Беремо будь-яке підходяще
        while self.idle_connections:
            conn = self.idle_connections.popleft()
            self.metrics["idle_connections"] = len(self.idle_connections)

            if not conn.is_expired:
                return conn
            else:
                # Закриваємо expired з'єднання
                asyncio.create_task(self._close_connection(conn))

        return None

    def _enqueue_request(self, request: ConnectionRequest):
        """Додавання запиту в чергу з урахуванням пріоритету"""
        self.priority_queue[request.priority].append(request)
        self.pending_requests.append(request)
        self.metrics["queued_requests"] = len(self.pending_requests)

        logger.debug(
            "Request queued",
            request_id=request.id,
            priority=request.priority.name,
            queue_size=len(self.pending_requests),
        )

    async def _wait_for_connection(
        self, request: ConnectionRequest
    ) -> Optional[PooledConnection]:
        """Очікування на з'єднання з черги"""
        start_time = time.time()

        while not request.is_expired:
            await asyncio.sleep(0.1)

            # Перевіряємо чи з'явилось з'єднання
            async with self._lock:
                if request.id not in [r.id for r in self.pending_requests]:
                    # Запит був оброблений
                    return self.active_connections.get(request.metadata.get("conn_id"))

            if time.time() - start_time > request.timeout:
                break

        # Таймаут - видаляємо з черги
        async with self._lock:
            self._remove_request(request)

        logger.warning(
            "Connection request timed out",
            request_id=request.id,
            waited=time.time() - start_time,
        )
        return None

    def _remove_request(self, request: ConnectionRequest):
        """Видалення запиту з черг"""
        if request in self.pending_requests:
            self.pending_requests.remove(request)

        if request in self.priority_queue[request.priority]:
            self.priority_queue[request.priority].remove(request)

        self.metrics["queued_requests"] = len(self.pending_requests)

    async def _process_queue(self):
        """Обробка черги запитів"""
        # Обробляємо в порядку пріоритету
        for priority in sorted(ConnectionPriority, key=lambda p: p.value, reverse=True):
            queue = self.priority_queue[priority]

            while queue and (
                len(self.active_connections) < self.pool_size or self.idle_connections
            ):
                request = queue.popleft()

                # Перевірка таймауту
                if request.is_expired:
                    self._remove_request(request)
                    continue

                # Спробуємо виділити з'єднання
                conn = self._get_idle_connection(request.client_type)
                if conn:
                    conn.client_id = request.client_id
                    conn.client_type = request.client_type
                    conn.state = ConnectionState.ACTIVE
                    conn.priority = request.priority

                    self.active_connections[conn.id] = conn

                    if request.client_id not in self.client_connections:
                        self.client_connections[request.client_id] = set()
                    self.client_connections[request.client_id].add(conn.id)

                    # Зберігаємо conn_id для wait_for_connection
                    request.metadata["conn_id"] = conn.id

                    # Видаляємо з черги
                    self._remove_request(request)

                    logger.info(
                        "Queued request fulfilled",
                        request_id=request.id,
                        conn_id=conn.id,
                    )

                    if request.callback:
                        await request.callback(conn)
                else:
                    # Немає доступних з'єднань, повертаємо в чергу
                    queue.appendleft(request)
                    break

    async def _close_connection(self, conn: PooledConnection):
        """Закриття з'єднання"""
        conn.state = ConnectionState.CLOSING

        try:
            if conn.websocket:
                await conn.websocket.close()
        except Exception as e:
            logger.error("Error closing connection", conn_id=conn.id, error=str(e))

        conn.state = ConnectionState.CLOSED
        logger.debug("Connection closed", conn_id=conn.id, age=conn.age)

    async def _health_check_loop(self):
        """Background task для health checks"""
        while True:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error", error=str(e))

    async def _perform_health_checks(self):
        """Виконання health checks для всіх з'єднань"""
        async with self._lock:
            connections_to_check = list(self.active_connections.values())

        for conn in connections_to_check:
            if conn.state != ConnectionState.ACTIVE:
                continue

            try:
                # Простий ping для перевірки
                pong_waiter = await conn.websocket.ping()
                await asyncio.wait_for(pong_waiter, timeout=5.0)

                conn.last_health_check = datetime.utcnow()

            except Exception as e:
                logger.warning("Health check failed", conn_id=conn.id, error=str(e))

                conn.error_count += 1
                self.metrics["failed_health_checks"] += 1

                if conn.error_count > 3:
                    await self.release(conn.id, close=True)

    async def _cleanup_loop(self):
        """Background task для очищення старих з'єднань"""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL)
                await self._cleanup_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Cleanup error", error=str(e))

    async def _cleanup_connections(self):
        """Очищення expired та idle з'єднань"""
        async with self._lock:
            # Очищення idle з'єднань
            idle_to_remove = []
            for conn in self.idle_connections:
                if conn.is_expired or conn.is_idle:
                    idle_to_remove.append(conn)

            for conn in idle_to_remove:
                self.idle_connections.remove(conn)
                await self._close_connection(conn)

            # Очищення expired запитів
            expired_requests = [r for r in self.pending_requests if r.is_expired]
            for request in expired_requests:
                self._remove_request(request)

            self.metrics["idle_connections"] = len(self.idle_connections)

            if idle_to_remove or expired_requests:
                logger.info(
                    "Cleanup completed",
                    idle_removed=len(idle_to_remove),
                    requests_removed=len(expired_requests),
                )

    async def _auto_scale_loop(self):
        """Background task для автоматичного масштабування пулу"""
        while True:
            try:
                await asyncio.sleep(60)  # Перевірка кожну хвилину
                await self._auto_scale()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Auto-scale error", error=str(e))

    async def _auto_scale(self):
        """Автоматичне масштабування розміру пулу"""
        async with self._lock:
            active_ratio = len(self.active_connections) / self.pool_size
            queue_ratio = (
                len(self.pending_requests) / self.queue_size
                if self.queue_size > 0
                else 0
            )

            # Збільшуємо pool якщо високе навантаження
            if active_ratio > 0.8 or queue_ratio > 0.5:
                new_size = min(int(self.pool_size * 1.5), MAX_POOL_SIZE)
                if new_size > self.pool_size:
                    logger.info(
                        "Scaling up pool", old_size=self.pool_size, new_size=new_size
                    )
                    self.pool_size = new_size

            # Зменшуємо pool якщо низьке навантаження
            elif active_ratio < 0.2 and queue_ratio == 0:
                new_size = max(int(self.pool_size * 0.75), MIN_POOL_SIZE)
                if new_size < self.pool_size:
                    logger.info(
                        "Scaling down pool", old_size=self.pool_size, new_size=new_size
                    )
                    self.pool_size = new_size

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики пулу"""
        return {
            "pool_size": self.pool_size,
            "active_connections": len(self.active_connections),
            "idle_connections": len(self.idle_connections),
            "queued_requests": len(self.pending_requests),
            "total_clients": len(self.client_connections),
            "metrics": self.metrics.copy(),
            "health": {
                "utilization": len(self.active_connections) / self.pool_size * 100,
                "queue_pressure": (
                    len(self.pending_requests) / self.queue_size * 100
                    if self.queue_size > 0
                    else 0
                ),
            },
        }

    @asynccontextmanager
    async def connection_context(self, websocket: WebSocket, client_id: str, **kwargs):
        """Context manager для автоматичного управління з'єднанням"""
        conn = None
        try:
            conn = await self.acquire(websocket, client_id, **kwargs)
            if conn:
                yield conn
            else:
                raise RuntimeError("Failed to acquire connection")
        finally:
            if conn:
                await self.release(conn.id)


# Глобальний пул з'єднань
connection_pool = ConnectionPool()


# Допоміжні функції
async def get_connection(
    websocket: WebSocket,
    client_id: str,
    client_type: str = "unknown",
    priority: ConnectionPriority = ConnectionPriority.NORMAL,
) -> Optional[PooledConnection]:
    """Швидке отримання з'єднання з глобального пулу"""
    return await connection_pool.acquire(websocket, client_id, client_type, priority)


async def release_connection(conn_id: str, close: bool = False):
    """Швидке звільнення з'єднання"""
    await connection_pool.release(conn_id, close)


def get_pool_stats() -> Dict[str, Any]:
    """Отримання статистики глобального пулу"""
    return connection_pool.get_stats()
