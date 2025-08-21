"""
TetraCore StreamHub Task Models

Моделі для роботи з завданнями у StreamHub.
Включає завдання, контекст виконання, метадані та черги.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from enum import Enum
from pydantic import BaseModel, Field
import uuid
from collections import deque

from models.messages import TaskStatus, TaskPriority


class TaskType(str, Enum):
    """Типи завдань у системі"""
    API_REQUEST = "api_request"
    DATA_PROCESSING = "data_processing"
    FILE_UPLOAD = "file_upload"
    EMAIL_SEND = "email_send"
    NOTIFICATION = "notification"
    WEBHOOK = "webhook"
    CALCULATION = "calculation"
    SEND_MESSAGE = "send_message"
    CUSTOM = "custom"

    # Типи завдань для бота
    ACTIVATE_MODULE = "activate_module"
    DEACTIVATE_MODULE = "deactivate_module"

    # Типи завдань для воркерів
    WORKER_TASK = "worker_task"


class ExecutorType(str, Enum):
    """Типи виконавців завдань"""
    BOT = "bot"
    WORKER = "worker"
    WORKER_API = "worker_api"


class TaskMetadata(BaseModel):
    """Метадані завдання"""

    # Джерело завдання
    source: str = "unknown"

    # Версія завдання
    version: str = "1.0.0"

    # Теги для категоризації
    tags: Set[str] = Field(default_factory=set)

    # Група завдань
    group: Optional[str] = None

    # Батьківське завдання
    parent_task_id: Optional[str] = None

    # Дочірні завдання
    child_task_ids: List[str] = Field(default_factory=list)

    # Залежності
    dependencies: List[str] = Field(default_factory=list)

    # Користувач, який створив завдання
    created_by: Optional[str] = None

    # Додаткові метадані
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)

    # Прапорці
    is_critical: bool = False
    is_retryable: bool = True
    is_cancellable: bool = True

    # Ідемпотентність: ключ для унікальної ідентифікації запиту
    idempotency_key: Optional[str] = None

    # Налаштування виконання
    execution_settings: Dict[str, Any] = Field(default_factory=dict)


class TaskContext(BaseModel):
    """Контекст виконання завдання"""

    # Ідентифікатор завдання
    task_id: str

    # Ідентифікатор воркера, який виконує завдання
    worker_id: Optional[str] = None

    # Ідентифікатор клієнта, який відправив завдання
    client_id: Optional[str] = None

    # Ідентифікатор кореляції для зв'язування запитів/відповідей
    correlation_id: Optional[str] = None

    # Час створення завдання
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Час призначення воркеру
    assigned_at: Optional[datetime] = None

    # Час початку виконання
    started_at: Optional[datetime] = None

    # Час завершення
    completed_at: Optional[datetime] = None

    # Час експірації
    expires_at: Optional[datetime] = None

    # Поточний стан
    current_status: TaskStatus = TaskStatus.PENDING

    # Попередні стани
    status_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Поточна спроба
    current_attempt: int = 1

    # Історія спроб
    attempt_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Результат виконання
    result: Optional[Dict[str, Any]] = None

    # Помилки
    errors: List[Dict[str, Any]] = Field(default_factory=list)

    # Використані ресурси
    resource_usage: Dict[str, float] = Field(default_factory=dict)

    # Метрики виконання
    execution_metrics: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            set: lambda v: list(v)  # Конвертуємо set в list для JSON серіалізації
        }

    def add_status_change(self, new_status: TaskStatus, message: str = ""):
        """Додавання зміни статусу"""
        self.status_history.append({
            "from_status": self.current_status.value,
            "to_status": new_status.value,
            "timestamp": datetime.utcnow().isoformat(),
            "message": message
        })
        self.current_status = new_status

    def add_attempt(self, worker_id: str, error: str = None):
        """Додавання спроби виконання"""
        self.attempt_history.append({
            "attempt": self.current_attempt,
            "worker_id": worker_id,
            "started_at": datetime.utcnow().isoformat(),
            "error": error
        })
        self.current_attempt += 1

    def add_error(self, error_type: str, error_message: str, error_trace: str = None):
        """Додавання помилки"""
        self.errors.append({
            "error_type": error_type,
            "error_message": error_message,
            "error_trace": error_trace,
            "timestamp": datetime.utcnow().isoformat(),
            "attempt": self.current_attempt
        })

    def get_execution_time(self) -> Optional[float]:
        """Отримання часу виконання в секундах"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def get_total_time(self) -> Optional[float]:
        """Отримання загального часу з моменту створення"""
        end_time = self.completed_at or datetime.utcnow()
        return (end_time - self.created_at).total_seconds()

    def is_expired(self) -> bool:
        """Перевірка чи завдання прострочене"""
        if self.expires_at:
            return datetime.utcnow() > self.expires_at
        return False

    def is_completed(self) -> bool:
        """Перевірка чи завдання завершене"""
        return self.current_status in [
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.TIMEOUT
        ]

    def reset_assignment(self):
        """Скидання призначення воркеру при невдалому надсиланні"""
        self.worker_id = None
        self.assigned_at = None
        self.started_at = None
        self.add_status_change(TaskStatus.PENDING, "Assignment reset due to communication failure")


class Task(BaseModel):
    """Основна модель завдання"""

    # Унікальний ідентифікатор
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Тип завдання
    task_type: TaskType

    # Дані завдання
    data: Dict[str, Any]

    # Пріоритет
    priority: TaskPriority = TaskPriority.NORMAL

    # Максимальний час виконання (секунди)
    timeout: int = 300

    # Максимальна кількість спроб
    max_retries: int = 3

    # Затримка між спробами (секунди)
    retry_delay: int = 5

    # Тип виконавця завдання
    executor_type: ExecutorType = ExecutorType.WORKER

    # Вимоги до воркера
    worker_requirements: List[str] = Field(default_factory=list)

    # Метадані
    metadata: TaskMetadata = Field(default_factory=TaskMetadata)

    # Контекст виконання
    context: TaskContext = Field(default_factory=lambda: TaskContext(task_id=str(uuid.uuid4())))

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            set: lambda v: list(v)  # Конвертуємо set в list для JSON серіалізації
        }

    def __init__(self, **data):
        super().__init__(**data)
        # Синхронізація task_id між завданням і контекстом
        if self.context.task_id != self.task_id:
            self.context.task_id = self.task_id

    @classmethod
    def create(cls, task_type: TaskType, data: Dict[str, Any], **kwargs) -> "Task":
        """Створення нового завдання"""
        task_id = kwargs.get('task_id', str(uuid.uuid4()))
        context = TaskContext(task_id=task_id)

        # Валідація та нормалізація executor_type
        executor_type = kwargs.get('executor_type', ExecutorType.WORKER)
        if isinstance(executor_type, str):
            # Автоматичний мапінг строкових значень
            executor_mapping = {
                'bot': ExecutorType.BOT,
                'worker': ExecutorType.WORKER,
                'worker_api': ExecutorType.WORKER_API,
                'api': ExecutorType.WORKER_API,  # Альтернативна назва
                'api_worker': ExecutorType.WORKER_API  # Альтернативна назва
            }
            
            executor_type_lower = executor_type.lower()
            if executor_type_lower in executor_mapping:
                executor_type = executor_mapping[executor_type_lower]
            else:
                # Невідомий тип - використовуємо WORKER за замовчуванням
                from structlog import get_logger
                logger = get_logger(__name__)
                logger.warning("Unknown executor_type, using WORKER as default",
                             provided_executor_type=executor_type,
                             valid_types=list(executor_mapping.keys()))
                executor_type = ExecutorType.WORKER
        
        # Встановлюємо executor_type в kwargs для передачі в конструктор
        kwargs['executor_type'] = executor_type

        return cls(
            task_id=task_id,
            task_type=task_type,
            data=data,
            context=context,
            **kwargs
        )

    def assign_to_worker(self, worker_id: str):
        """Призначення завдання воркеру"""
        self.context.worker_id = worker_id
        self.context.assigned_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.ASSIGNED, f"Assigned to worker {worker_id}")

    def start_execution(self):
        """Початок виконання завдання"""
        self.context.started_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.PROCESSING, "Task execution started")

    def complete(self, result: Dict[str, Any]):
        """Завершення завдання з успіхом"""
        self.context.result = result
        self.context.completed_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.COMPLETED, "Task completed successfully")

    def fail(self, error_message: str, error_trace: str = None):
        """Завершення завдання з помилкою"""
        self.context.add_error("execution_error", error_message, error_trace)
        self.context.completed_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.FAILED, f"Task failed: {error_message}")

    def mark_timeout(self):
        """Позначити завдання як завершене через таймаут"""
        self.context.completed_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.TIMEOUT, "Task timed out")

    def cancel(self, reason: str = ""):
        """Скасування завдання"""
        self.context.completed_at = datetime.utcnow()
        self.context.add_status_change(TaskStatus.CANCELLED, f"Task cancelled: {reason}")

    def can_retry(self) -> bool:
        """Перевірка чи можна повторити завдання"""
        return (self.metadata.is_retryable and
                self.context.current_attempt <= self.max_retries and
                self.context.current_status in [TaskStatus.FAILED, TaskStatus.TIMEOUT])

    def schedule_retry(self):
        """Планування повторної спроби"""
        if self.can_retry():
            self.context.add_status_change(TaskStatus.RETRY, f"Scheduling retry attempt {self.context.current_attempt}")
            return True
        return False

    def set_expiration(self, expires_in_seconds: int):
        """Встановлення часу експірації"""
        self.context.expires_at = datetime.utcnow() + timedelta(seconds=expires_in_seconds)

    def get_priority_score(self) -> int:
        """Отримання числового пріоритету для сортування"""
        priority_scores = {
            TaskPriority.LOW: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.HIGH: 3,
            TaskPriority.CRITICAL: 4
        }

        score = priority_scores.get(self.priority, 2)

        # Збільшення пріоритету для критичних завдань
        if self.metadata.is_critical:
            score += 10

        # Зменшення пріоритету для старих завдань
        age_minutes = (datetime.utcnow() - self.context.created_at).total_seconds() / 60
        if age_minutes > 60:  # Завдання старше години
            score -= 1

        return max(score, 1)

    def to_dict(self) -> Dict[str, Any]:
        """Конвертація в словник"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "status": self.context.current_status.value,
            "worker_id": self.context.worker_id,
            "client_id": self.context.client_id,
            "created_at": self.context.created_at.isoformat(),
            "started_at": self.context.started_at.isoformat() if self.context.started_at else None,
            "completed_at": self.context.completed_at.isoformat() if self.context.completed_at else None,
            "execution_time": self.context.get_execution_time(),
            "attempt": self.context.current_attempt,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "is_expired": self.context.is_expired(),
            "can_retry": self.can_retry(),
            "task_data": self.data,
            "metadata": self.metadata.model_dump()
        }

    # ====== Storage-friendly serialization for overflow persistence ======
    def to_storage(self) -> Dict[str, Any]:
        """Мінімальне подання для збереження у Redis overflow.

        Не включає контекст виконання; відновлюється як нове PENDING завдання.
        """
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "data": self.data,
            "priority": self.priority.value,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "executor_type": self.executor_type.value if hasattr(self.executor_type, 'value') else str(self.executor_type),
            "worker_requirements": self.worker_requirements,
            # metadata може бути великим, тому зберігаємо лише базові поля
            "metadata": self.metadata.model_dump() if hasattr(self.metadata, 'model_dump') else {}
        }

    @classmethod
    def from_storage(cls, stored: Dict[str, Any]) -> "Task":
        """Відновлення Task з мінімального подання overflow."""
        # Імпорт enum всередині щоб уникнути циклічних залежностей при імпорті
        from models.task import TaskType, TaskPriority, ExecutorType, TaskMetadata
        task_type = stored.get("task_type")
        priority = stored.get("priority", "normal")
        executor_type = stored.get("executor_type", "worker")

        # Нормалізація enumів
        task_type_enum = TaskType(task_type)
        priority_enum = TaskPriority(priority)
        executor_type_enum = ExecutorType(executor_type) if executor_type in [e.value for e in ExecutorType] else ExecutorType.WORKER

        metadata_dict = stored.get("metadata") or {}
        try:
            metadata = TaskMetadata(**metadata_dict)
        except Exception:
            metadata = TaskMetadata()

        return cls(
            task_id=stored.get("task_id"),
            task_type=task_type_enum,
            data=stored.get("data") or {},
            priority=priority_enum,
            timeout=int(stored.get("timeout", 300)),
            max_retries=int(stored.get("max_retries", 3)),
            retry_delay=int(stored.get("retry_delay", 5)),
            executor_type=executor_type_enum,
            worker_requirements=stored.get("worker_requirements") or [],
            metadata=metadata,
        )


class TaskQueue(BaseModel):
    """Черга завдань"""

    # Назва черги
    name: str

    # Максимальний розмір черги
    max_size: int = 10000

    # Завдання у черзі (за пріоритетом)
    tasks: Dict[str, Task] = Field(default_factory=dict)

    # Черга по пріоритетах
    priority_queues: Dict[TaskPriority, deque] = Field(
        default_factory=lambda: {
            TaskPriority.CRITICAL: deque(),
            TaskPriority.HIGH: deque(),
            TaskPriority.NORMAL: deque(),
            TaskPriority.LOW: deque()
        }
    )

    # Статистика
    total_added: int = 0
    total_processed: int = 0
    total_failed: int = 0

    class Config:
        arbitrary_types_allowed = True
        extra = 'allow'

    def add_task(self, task: Task) -> bool:
        """Додавання завдання до черги"""
        if len(self.tasks) >= self.max_size:
            return False

        self.tasks[task.task_id] = task
        self.priority_queues[task.priority].append(task.task_id)
        self.total_added += 1

        return True

    def get_next_task(self, worker_requirements: List[str] = None) -> Optional[Task]:
        """Отримання наступного завдання з черги"""
        # Пошук за пріоритетом
        for priority in [TaskPriority.CRITICAL, TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW]:
            queue = self.priority_queues[priority]

            # Пошук підходящого завдання у черзі пріоритету
            for _ in range(len(queue)):
                task_id = queue.popleft()

                if task_id not in self.tasks:
                    continue

                task = self.tasks[task_id]

                # Перевірка вимог до воркера
                if worker_requirements and task.worker_requirements:
                    if not all(req in worker_requirements for req in task.worker_requirements):
                        queue.append(task_id)  # Повертаємо в кінець черги
                        continue

                # Перевірка експірації
                if task.context.is_expired():
                    self.remove_task(task_id)
                    continue

                return task

        return None

    def remove_task(self, task_id: str) -> Optional[Task]:
        """Видалення завдання з черги"""
        if task_id not in self.tasks:
            return None

        task = self.tasks.pop(task_id)

        # Видалення з черги пріоритетів
        queue = self.priority_queues[task.priority]
        try:
            queue.remove(task_id)
        except ValueError:
            pass  # Завдання вже було видалено або не знайдено

        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """Отримання завдання за ID"""
        return self.tasks.get(task_id)

    def update_task_priority(self, task_id: str, new_priority: TaskPriority) -> bool:
        """Оновлення пріоритету завдання"""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        old_priority = task.priority

        # Видалення зі старої черги
        try:
            self.priority_queues[old_priority].remove(task_id)
        except ValueError:
            pass

        # Додавання до нової черги
        task.priority = new_priority
        self.priority_queues[new_priority].append(task_id)

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики черги"""
        queue_sizes = {
            priority.value: len(queue)
            for priority, queue in self.priority_queues.items()
        }

        return {
            "name": self.name,
            "total_tasks": len(self.tasks),
            "max_size": self.max_size,
            "queue_sizes": queue_sizes,
            "total_added": self.total_added,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "utilization": len(self.tasks) / self.max_size * 100
        }

    def clear_expired_tasks(self) -> int:
        """Очищення прострочених завдань"""
        expired_count = 0
        expired_task_ids = []

        for task_id, task in self.tasks.items():
            if task.context.is_expired():
                expired_task_ids.append(task_id)

        for task_id in expired_task_ids:
            self.remove_task(task_id)
            expired_count += 1

        return expired_count

    def is_full(self) -> bool:
        """Перевірка чи черга заповнена"""
        return len(self.tasks) >= self.max_size

    def is_empty(self) -> bool:
        """Перевірка чи черга порожня"""
        return len(self.tasks) == 0
