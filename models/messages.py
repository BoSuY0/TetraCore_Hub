"""
TetraCore StreamHub Message Models

Визначення всіх типів повідомлень для протоколу комунікації між
ботом, воркерами та StreamHub.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict
import uuid


class MessageType(str, Enum):
    """Типи повідомлень у протоколі StreamHub"""

    # Реєстрація та аутентифікація
    CLIENT_REGISTRATION = "client_registration"
    REGISTRATION_ACK = "registration_ack"
    REGISTRATION_ERROR = "registration_error"

    # Завдання та результати
    TASK_SUBMIT = "task_submit"
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_ERROR = "task_error"
    TASK_TIMEOUT = "task_timeout"
    TASK_RETRY = "task_retry"
    TASK_CANCEL = "task_cancel"

    # Перевірка здоров'я
    PING = "ping"
    PONG = "pong"
    HEALTH_CHECK = "health_check"
    HEALTH_STATUS = "health_status"

    # Широкомовні повідомлення
    BROADCAST = "broadcast"
    SYSTEM_NOTIFICATION = "system_notification"

    # Службові повідомлення
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    # Метрики та статистика
    METRICS_REQUEST = "metrics_request"
    METRICS_RESPONSE = "metrics_response"
    STATS_UPDATE = "stats_update"


class ClientType(str, Enum):
    """Типи клієнтів у системі"""

    BOT = "bot"
    WORKER = "worker"
    WORKER_API = "worker_api"
    STREAM_HUB = "stream_hub"
    MONITOR = "monitor"
    ADMIN = "admin"


class TaskStatus(str, Enum):
    """Статуси завдань"""

    PENDING = "pending"
    ASSIGNED = "assigned"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RETRY = "retry"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Пріоритети завдань"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class BaseMessage(BaseModel):
    """Базовий клас для всіх повідомлень"""

    # Унікальний ідентифікатор повідомлення
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Тип повідомлення
    message_type: MessageType

    # Часові мітки
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Ідентифікатор відправника
    sender_id: Optional[str] = None

    # Ідентифікатор отримувача (None для broadcast)
    recipient_id: Optional[str] = None

    model_config = ConfigDict(
        use_enum_values=True, json_encoders={datetime: lambda v: v.isoformat()}
    )

    # Ідентифікатор кореляції для зв'язування запитів/відповідей
    correlation_id: Optional[str] = None

    # Метадані повідомлення
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ClientRegistration(BaseMessage):
    """Повідомлення реєстрації клієнта"""

    message_type: MessageType = MessageType.CLIENT_REGISTRATION

    # Тип клієнта
    client_type: ClientType

    # Ідентифікатор клієнта
    client_id: str

    # Назва клієнта
    client_name: str

    # Версія клієнта
    client_version: str = "1.0.0"

    # Можливості клієнта (для воркерів)
    capabilities: List[str] = Field(default_factory=list)

    # Максимальна кількість одночасних завдань (для воркерів)
    max_concurrent_tasks: int = 1

    # Токен аутентифікації
    auth_token: Optional[str] = None

    # Додаткова інформація про клієнта
    client_info: Dict[str, Any] = Field(default_factory=dict)


class RegistrationAck(BaseMessage):
    """Підтвердження реєстрації клієнта"""

    message_type: MessageType = MessageType.REGISTRATION_ACK

    # Ідентифікатор клієнта
    client_id: str

    # Статус реєстрації
    success: bool = True

    # Повідомлення про статус
    message: str = "Registration successful"

    # Призначений ідентифікатор сесії
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Конфігурація для клієнта
    config: Dict[str, Any] = Field(default_factory=dict)


class TaskMessage(BaseMessage):
    """Повідомлення з завданням"""

    message_type: MessageType = MessageType.TASK_SUBMIT

    # Унікальний ідентифікатор завдання
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Тип завдання
    task_type: str

    # Дані завдання
    task_data: Dict[str, Any]

    # Пріоритет завдання
    priority: TaskPriority = TaskPriority.NORMAL

    # Таймаут виконання (секунди)
    timeout: int = 300

    # Максимальна кількість повторних спроб
    max_retries: int = 3

    # Поточна кількість спроб
    retry_count: int = 0

    # Вимоги до воркера
    worker_requirements: List[str] = Field(default_factory=list)

    # Тип виконавця завдання
    executor_type: str = "worker"

    # Час створення завдання
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Час початку виконання
    started_at: Optional[datetime] = None

    # Час завершення
    completed_at: Optional[datetime] = None


class TaskAssignment(BaseMessage):
    """Призначення завдання воркеру"""

    message_type: MessageType = MessageType.TASK_ASSIGN

    # Ідентифікатор завдання
    task_id: str

    # Ідентифікатор воркера
    worker_id: str

    # Дані завдання
    task_data: Dict[str, Any]

    # Тип завдання
    task_type: str

    # Пріоритет
    priority: TaskPriority

    # Таймаут виконання
    timeout: int

    # Час призначення
    assigned_at: datetime = Field(default_factory=datetime.utcnow)


class TaskResult(BaseMessage):
    """Результат виконання завдання"""

    message_type: MessageType = MessageType.TASK_RESULT

    # Ідентифікатор завдання
    task_id: str

    # Статус виконання
    status: TaskStatus

    # Результат виконання
    result: Optional[Dict[str, Any]] = None

    # Повідомлення про помилку (якщо є)
    error_message: Optional[str] = None

    # Трейс помилки
    error_trace: Optional[str] = None

    # Час виконання (мілісекунди)
    execution_time: Optional[int] = None

    # Використані ресурси
    resource_usage: Dict[str, Any] = Field(default_factory=dict)

    # Час завершення
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class HealthCheck(BaseMessage):
    """Перевірка здоров'я клієнта"""

    message_type: MessageType = MessageType.PING

    # Ідентифікатор клієнта (опціональний, може бути автоматично призначений)
    client_id: Optional[str] = None

    # Тип перевірки
    check_type: str = "ping"

    # Час відправки
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class HealthStatus(BaseMessage):
    """Відповідь на перевірку здоров'я"""

    message_type: MessageType = MessageType.PONG

    # Ідентифікатор клієнта (опціональний)
    client_id: Optional[str] = None

    # Статус здоров'я
    healthy: bool = True

    # Деталі стану
    status_details: Dict[str, Any] = Field(default_factory=dict)

    # Поточне навантаження (для воркерів)
    current_load: Optional[int] = None

    # Кількість активних завдань
    active_tasks: Optional[int] = None

    # Час відповіді
    responded_at: datetime = Field(default_factory=datetime.utcnow)


class BroadcastMessage(BaseMessage):
    """Широкомовне повідомлення"""

    message_type: MessageType = MessageType.BROADCAST

    # Тип широкомовного повідомлення
    broadcast_type: str

    # Дані повідомлення
    data: Dict[str, Any]

    # Цільова аудиторія
    target_clients: List[ClientType] = Field(default_factory=list)

    # Канал широкомовлення
    channel: str = "general"


class ErrorMessage(BaseMessage):
    """Повідомлення про помилку"""

    message_type: MessageType = MessageType.ERROR

    # Код помилки
    error_code: str

    # Повідомлення про помилку
    error_message: str

    # Деталі помилки
    error_details: Dict[str, Any] = Field(default_factory=dict)

    # Трейс помилки
    error_trace: Optional[str] = None

    # Рівень критичності
    severity: str = "error"  # error, warning, info

    # Чи можна повторити операцію
    retryable: bool = False


class MetricsRequest(BaseMessage):
    """Запит метрик"""

    message_type: MessageType = MessageType.METRICS_REQUEST

    # Типи метрик
    metric_types: List[str] = Field(default_factory=list)

    # Період для метрик
    time_range: Optional[Dict[str, datetime]] = None


class MetricsResponse(BaseMessage):
    """Відповідь з метриками"""

    message_type: MessageType = MessageType.METRICS_RESPONSE

    # Метрики
    metrics: Dict[str, Any]

    # Час збору метрик
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class StatsUpdate(BaseMessage):
    """Оновлення статистики"""

    message_type: MessageType = MessageType.STATS_UPDATE

    # Ідентифікатор клієнта
    client_id: str

    # Статистика
    stats: Dict[str, Any]

    # Час оновлення
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Тип для всіх повідомлень
Message = Union[
    BaseMessage,
    ClientRegistration,
    RegistrationAck,
    TaskMessage,
    TaskAssignment,
    TaskResult,
    HealthCheck,
    HealthStatus,
    BroadcastMessage,
    ErrorMessage,
    MetricsRequest,
    MetricsResponse,
    StatsUpdate,
]


def create_message(message_type: MessageType, **kwargs) -> Message:
    """Фабрика для створення повідомлень"""
    import structlog

    logger = structlog.get_logger(__name__)

    logger.debug(
        "[DEBUG] create_message called",
        message_type=message_type,
        kwargs_keys=list(kwargs.keys()),
        has_task_type=("task_type" in kwargs),
        has_task_data=("task_data" in kwargs),
        task_type_value=kwargs.get("task_type") if "task_type" in kwargs else None,
        kwargs_count=len(kwargs),
    )

    # Спеціальне логування для TASK_SUBMIT
    if message_type == MessageType.TASK_SUBMIT:
        logger.debug(
            "[DEBUG] TASK_SUBMIT specific data",
            task_type=kwargs.get("task_type", "MISSING"),
            task_data=kwargs.get("task_data", "MISSING"),
            all_fields=list(kwargs.keys()),
        )

    message_classes = {
        MessageType.CLIENT_REGISTRATION: ClientRegistration,
        MessageType.REGISTRATION_ACK: RegistrationAck,
        MessageType.TASK_SUBMIT: TaskMessage,
        MessageType.TASK_ASSIGN: TaskAssignment,
        MessageType.TASK_RESULT: TaskResult,
        MessageType.PING: HealthCheck,
        MessageType.PONG: HealthStatus,
        MessageType.BROADCAST: BroadcastMessage,
        MessageType.ERROR: ErrorMessage,
        MessageType.METRICS_REQUEST: MetricsRequest,
        MessageType.METRICS_RESPONSE: MetricsResponse,
        MessageType.STATS_UPDATE: StatsUpdate,
    }

    message_class = message_classes.get(message_type, BaseMessage)

    logger.debug(
        "[DEBUG] Creating message instance",
        message_class=message_class.__name__,
        will_pass_kwargs=kwargs,
    )

    try:
        # Для TaskMessage та інших класів з фіксованим message_type,
        # не передаємо message_type в конструктор
        if message_class in [TaskMessage, ClientRegistration, RegistrationAck]:
            return message_class(**kwargs)
        else:
            return message_class(message_type=message_type, **kwargs)
    except Exception as e:
        logger.debug(
            "[DEBUG] Failed to create message",
            message_class=message_class.__name__,
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


def parse_message(message_data: Dict[str, Any]) -> Message:
    """Парсинг повідомлення з JSON"""
    import structlog

    logger = structlog.get_logger(__name__)

    # Логування вхідних даних
    logger.debug(
        "[DEBUG] parse_message called",
        message_data_keys=list(message_data.keys()),
        message_type_value=message_data.get("message_type"),
        has_task_type=("task_type" in message_data),
        has_task_data=("task_data" in message_data),
        task_type_value=(
            message_data.get("task_type") if "task_type" in message_data else None
        ),
        full_data=message_data,
    )

    message_type = MessageType(message_data.get("message_type"))
    # Remove message_type from data to avoid duplicate parameter
    data_copy = message_data.copy()
    data_copy.pop("message_type", None)

    logger.debug(
        "[DEBUG] Creating message",
        message_type=message_type,
        data_copy_keys=list(data_copy.keys()),
        has_task_type_in_copy=("task_type" in data_copy),
        has_task_data_in_copy=("task_data" in data_copy),
    )

    return create_message(message_type, **data_copy)
