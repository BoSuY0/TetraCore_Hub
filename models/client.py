"""
TetraCore StreamHub Client Models

Моделі для роботи з клієнтами (боти та воркери) у StreamHub.
Включає інформацію про клієнтів, їх можливості та статистику.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Set
from enum import Enum
from pydantic import BaseModel, Field
import uuid
import structlog

from models.messages import ClientType, TaskStatus

logger = structlog.get_logger(__name__)


class ConnectionStatus(str, Enum):
    """Статуси підключення клієнта"""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class WorkerStatus(str, Enum):
    """Статуси воркера"""

    IDLE = "idle"
    BUSY = "busy"
    OVERLOADED = "overloaded"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class WorkerCapabilities(BaseModel):
    """Можливості воркера"""

    # Типи завдань, які може обробляти воркер
    supported_task_types: List[str] = Field(default_factory=list)

    # Максимальна кількість одночасних завдань
    max_concurrent_tasks: int = 1

    # Середній час обробки завдання (секунди)
    average_processing_time: float = 0.0

    # Максимальний розмір завдання (байти)
    max_task_size: int = 1024 * 1024  # 1MB

    # Підтримувані формати даних
    supported_formats: List[str] = Field(default_factory=lambda: ["json"])

    # Спеціальні можливості
    special_capabilities: List[str] = Field(default_factory=list)

    # Версія API воркера
    api_version: str = "1.0.0"

    # Мінімальна пріоритетність завдань
    min_priority: str = "low"

    # Максимальна пріоритетність завдань
    max_priority: str = "critical"

    # Alias для сумісності зі старим кодом
    @property
    def supported_actions(self) -> List[str]:
        return self.supported_task_types


class ClientStats(BaseModel):
    """Статистика клієнта"""

    # Загальна кількість оброблених завдань
    total_tasks: int = 0

    # Успішно виконані завдання
    successful_tasks: int = 0

    # Невдалі завдання
    failed_tasks: int = 0

    # Завдання з таймаутом
    timeout_tasks: int = 0

    # Поточна кількість активних завдань
    active_tasks: int = 0

    # Середній час обробки (мілісекунди)
    average_processing_time: float = 0.0

    # Час останньої активності
    last_activity: datetime = Field(default_factory=datetime.utcnow)

    # Час підключення
    connected_at: datetime = Field(default_factory=datetime.utcnow)

    # Загальний час підключення (секунди)
    total_connection_time: float = 0.0

    # Кількість відключень
    disconnection_count: int = 0

    # Статистика помилок
    error_stats: Dict[str, int] = Field(default_factory=dict)

    # Використання ресурсів
    resource_usage: Dict[str, float] = Field(default_factory=dict)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ClientInfo(BaseModel):
    """Інформація про клієнта"""

    # Базова інформація
    client_id: str
    client_type: ClientType
    client_name: str = "unknown"
    client_version: str = "1.0.0"

    # Статус підключення
    connection_status: ConnectionStatus = ConnectionStatus.DISCONNECTED

    # Ідентифікатор сесії
    session_id: Optional[str] = None

    # Інформація про з'єднання
    remote_address: Optional[str] = None
    user_agent: Optional[str] = None

    # Час реєстрації
    registered_at: datetime = Field(default_factory=datetime.utcnow)

    # Час останнього ping
    last_ping: Optional[datetime] = None

    # Час останнього pong
    last_pong: Optional[datetime] = None

    # Можливості (тільки для воркерів)
    capabilities: Optional[WorkerCapabilities] = None

    # Статус воркера (тільки для воркерів)
    worker_status: Optional[WorkerStatus] = None

    # Поточне навантаження (0-100)
    current_load: int = 0

    # Статистика
    stats: ClientStats = Field(default_factory=ClientStats)

    # Конфігурація клієнта
    config: Dict[str, Any] = Field(default_factory=dict)

    # Метадані
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Теги для групування клієнтів
    tags: Set[str] = Field(default_factory=set)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            set: lambda v: list(v),  # Конвертуємо set в list для JSON серіалізації
        }

    def is_connected(self) -> bool:
        """Перевірка чи клієнт підключений"""
        return self.connection_status == ConnectionStatus.CONNECTED

    def is_worker(self) -> bool:
        """Перевірка чи це воркер"""
        return self.client_type in [ClientType.WORKER, ClientType.WORKER_API]

    def is_bot(self) -> bool:
        """Перевірка чи це бот"""
        return self.client_type == ClientType.BOT

    def can_execute_tasks(self) -> bool:
        """Перевірка чи може клієнт виконувати завдання (уніфікований метод)"""
        # Монітори та адміни не виконують таски
        if self.client_type in [ClientType.MONITOR, ClientType.ADMIN]:
            return False

        # Для всіх інших типів (BOT, WORKER, WORKER_API, STREAM_HUB) перевіряємо capabilities
        return bool(self.capabilities and self.capabilities.supported_task_types)

    def can_handle_task(self, task_type: str) -> bool:
        """Перевірка чи може клієнт обробити завдання"""
        # Використовуємо новий уніфікований метод
        if not self.can_execute_tasks():
            return False
        return task_type in self.capabilities.supported_task_types

    def is_available(self) -> bool:
        """Перевірка чи доступний клієнт для нових завдань"""
        # Використовуємо уніфікований метод та перевіряємо підключення
        if not self.can_execute_tasks() or not self.is_connected():
            return False

        # Для воркерів перевіряємо статус
        if self.is_worker() and self.worker_status in [
            WorkerStatus.MAINTENANCE,
            WorkerStatus.ERROR,
        ]:
            return False

        return self.stats.active_tasks < self.capabilities.max_concurrent_tasks

    def get_load_percentage(self) -> float:
        """Отримання процентного навантаження"""
        if not self.can_execute_tasks():
            return 0.0

        if self.capabilities.max_concurrent_tasks == 0:
            return 0.0

        return (self.stats.active_tasks / self.capabilities.max_concurrent_tasks) * 100

    def update_stats(self, **kwargs):
        """Оновлення статистики"""
        for key, value in kwargs.items():
            if hasattr(self.stats, key):
                setattr(self.stats, key, value)
        self.stats.last_activity = datetime.utcnow()

    def increment_task_count(self, status: TaskStatus):
        """Збільшення лічильника завдань"""
        self.stats.total_tasks += 1

        if status == TaskStatus.COMPLETED:
            self.stats.successful_tasks += 1
        elif status == TaskStatus.FAILED:
            self.stats.failed_tasks += 1
        elif status == TaskStatus.TIMEOUT:
            self.stats.timeout_tasks += 1

    def add_error(self, error_type: str):
        """Додавання помилки до статистики"""
        if error_type not in self.stats.error_stats:
            self.stats.error_stats[error_type] = 0
        self.stats.error_stats[error_type] += 1


class Client(BaseModel):
    """Повна модель клієнта з додатковими методами"""

    # Основна інформація
    info: ClientInfo

    # WebSocket з'єднання (не серіалізується)
    websocket: Optional[Any] = Field(exclude=True, default=None)

    # ID для security менеджера (не серіалізується)
    security_client_id: Optional[str] = Field(exclude=True, default=None)

    # Черга завдань для воркера
    task_queue: List[str] = Field(default_factory=list)

    # Активні завдання
    active_tasks: Dict[str, datetime] = Field(default_factory=dict)

    # Історія завдань (останні 100)
    task_history: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            set: lambda v: list(v),  # Конвертуємо set в list для JSON серіалізації
        }

    @classmethod
    def create_bot(
        cls,
        client_id: str,
        client_name: str,
        capabilities: Optional[WorkerCapabilities] = None,
        **kwargs,
    ) -> "Client":
        """Створення клієнта-бота"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.BOT,
            client_name=client_name,
            capabilities=capabilities,
            **kwargs,
        )
        return cls(info=info)

    @classmethod
    def create_worker(
        cls,
        client_id: str,
        client_name: str,
        capabilities: WorkerCapabilities,
        **kwargs,
    ) -> "Client":
        """Створення клієнта-воркера"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.WORKER,
            client_name=client_name,
            capabilities=capabilities,
            worker_status=WorkerStatus.IDLE,
            **kwargs,
        )
        return cls(info=info)

    @classmethod
    def create_monitor(cls, client_id: str, client_name: str, **kwargs) -> "Client":
        """Створення клієнта-монітора"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.MONITOR,
            client_name=client_name,
            **kwargs,
        )
        return cls(info=info)

    @classmethod
    def create_worker_api(
        cls,
        client_id: str,
        client_name: str,
        capabilities: WorkerCapabilities,
        **kwargs,
    ) -> "Client":
        """Створення API воркера"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.WORKER_API,
            client_name=client_name,
            capabilities=capabilities,
            worker_status=WorkerStatus.IDLE,
            **kwargs,
        )
        return cls(info=info)

    @classmethod
    def create_stream_hub(
        cls,
        client_id: str,
        client_name: str,
        capabilities: Optional[WorkerCapabilities] = None,
        **kwargs,
    ) -> "Client":
        """Створення Stream Hub клієнта"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.STREAM_HUB,
            client_name=client_name,
            capabilities=capabilities,
            **kwargs,
        )
        return cls(info=info)

    @classmethod
    def create_admin(cls, client_id: str, client_name: str, **kwargs) -> "Client":
        """Створення адміністративного клієнта"""
        info = ClientInfo(
            client_id=client_id,
            client_type=ClientType.ADMIN,
            client_name=client_name,
            **kwargs,
        )
        return cls(info=info)

    def connect(self, websocket, session_id: str = None):
        """Підключення клієнта"""
        self.websocket = websocket
        self.info.connection_status = ConnectionStatus.CONNECTED
        self.info.session_id = session_id or str(uuid.uuid4())
        self.info.stats.connected_at = datetime.utcnow()

    def disconnect(self):
        """Відключення клієнта"""
        self.websocket = None
        self.info.connection_status = ConnectionStatus.DISCONNECTED
        self.info.stats.disconnection_count += 1

        # Оновлення загального часу підключення
        if self.info.stats.connected_at:
            connection_time = (
                datetime.utcnow() - self.info.stats.connected_at
            ).total_seconds()
            self.info.stats.total_connection_time += connection_time

    def assign_task(self, task_id: str):
        """Призначення завдання клієнту"""
        logger.info(
            f"[ASSIGN_TASK] Attempting to assign task {task_id} to client {self.info.client_id}"
        )
        logger.info(
            f"[ASSIGN_TASK] Client checks: can_execute_tasks={self.info.can_execute_tasks()}, client_type={self.info.client_type.value}, has_capabilities={bool(self.info.capabilities)}"
        )
        logger.info(
            f"[ASSIGN_TASK] Load: active_tasks={self.info.stats.active_tasks}, max_concurrent={self.info.capabilities.max_concurrent_tasks if self.info.capabilities else 0}"
        )

        # Використовуємо уніфікований метод замість перевірки окремих типів
        if not self.info.can_execute_tasks():
            logger.warning(
                f"[ASSIGN_TASK] Rejected: client cannot execute tasks (type: {self.info.client_type.value})"
            )
            return False

        if self.info.stats.active_tasks >= self.info.capabilities.max_concurrent_tasks:
            logger.warning(
                f"[ASSIGN_TASK] Rejected: max tasks reached ({self.info.stats.active_tasks}/{self.info.capabilities.max_concurrent_tasks})"
            )
            return False

        self.active_tasks[task_id] = datetime.utcnow()
        self.info.stats.active_tasks = len(self.active_tasks)
        self.info.stats.total_tasks += 1
        self.info.stats.last_activity = datetime.utcnow()
        logger.info(
            f"[ASSIGN_TASK] Accepted: task {task_id} assigned successfully to {self.info.client_type.value}"
        )
        return True

    def release_task(self, task_id: str):
        """Скидання призначення завдання"""
        if task_id in self.active_tasks:
            self.active_tasks.pop(task_id)
            self.info.stats.active_tasks = len(self.active_tasks)
            self.info.stats.last_activity = datetime.utcnow()
            logger.info(
                f"[RELEASE_TASK] Task {task_id} released from client {self.info.client_id}"
            )
            return True
        return False

    def complete_task(
        self, task_id: str, status: TaskStatus, execution_time: float = None
    ):
        """Завершення завдання"""
        if task_id in self.active_tasks:
            start_time = self.active_tasks.pop(task_id)
            self.info.stats.active_tasks = len(self.active_tasks)

            # Розрахунок часу виконання
            if execution_time is None:
                execution_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            # Оновлення статистики
            self.info.increment_task_count(status)

            # Оновлення середнього часу обробки
            total_time = (
                self.info.stats.average_processing_time
                * (self.info.stats.total_tasks - 1)
                + execution_time
            )
            self.info.stats.average_processing_time = (
                total_time / self.info.stats.total_tasks
            )

            # Додавання до історії
            self.task_history.append(
                {
                    "task_id": task_id,
                    "status": status.value,
                    "execution_time": execution_time,
                    "completed_at": datetime.utcnow().isoformat(),
                }
            )

            # Обмеження розміру історії
            if len(self.task_history) > 100:
                self.task_history = self.task_history[-100:]

    def ping(self):
        """Відправка ping"""
        self.info.last_ping = datetime.utcnow()

    def pong(self):
        """Отримання pong"""
        self.info.last_pong = datetime.utcnow()

    def is_healthy(self, timeout: int = 60) -> bool:
        """Перевірка здоров'я клієнта"""
        if not self.info.is_connected():
            return False

        if self.info.last_pong:
            time_since_pong = (datetime.utcnow() - self.info.last_pong).total_seconds()
            return time_since_pong < timeout

        return True

    def to_dict(self) -> Dict[str, Any]:
        """Конвертація в словник для серіалізації"""
        return {
            "client_id": self.info.client_id,
            "client_type": self.info.client_type.value,
            "client_name": self.info.client_name,
            "client_version": self.info.client_version,
            "connection_status": self.info.connection_status.value,
            "worker_status": (
                self.info.worker_status.value if self.info.worker_status else None
            ),
            "current_load": self.info.get_load_percentage(),
            "remote_address": self.info.remote_address,
            "session_id": self.info.session_id,
            "last_ping": (
                self.info.last_ping.isoformat() if self.info.last_ping else None
            ),
            "last_pong": (
                self.info.last_pong.isoformat() if self.info.last_pong else None
            ),
            "registered_at": (
                self.info.registered_at.isoformat() if self.info.registered_at else None
            ),
            "stats": self.info.stats.model_dump(),
            "capabilities": (
                self.info.capabilities.model_dump() if self.info.capabilities else None
            ),
            "active_tasks_count": len(self.active_tasks),
            "is_healthy": self.is_healthy(),
            "metadata": self.info.metadata,
            "config": self.info.config,
            "tags": list(self.info.tags) if self.info.tags else [],
        }
