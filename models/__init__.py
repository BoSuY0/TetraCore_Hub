"""
TetraCore StreamHub Protocol Models

Модулі для визначення структури повідомлень та протоколу комунікації
між ботом, воркерами та StreamHub.
"""

from models.messages import (
    BaseMessage,
    ClientRegistration,
    TaskMessage,
    TaskResult,
    HealthCheck,
    BroadcastMessage,
    ErrorMessage,
    MessageType,
    ClientType,
    TaskStatus,
    TaskPriority,
    parse_message,
    create_message
)

from models.client import (
    Client,
    ClientInfo,
    WorkerCapabilities,
    ClientStats,
    ConnectionStatus,
    WorkerStatus
)

from models.task import (
    Task,
    TaskType,
    TaskContext,
    TaskMetadata,
    TaskQueue
)

__all__ = [
    # Messages
    "BaseMessage",
    "ClientRegistration",
    "TaskMessage",
    "TaskResult",
    "HealthCheck",
    "BroadcastMessage",
    "ErrorMessage",
    "MessageType",
    "ClientType",
    "TaskStatus",
    "TaskPriority",
    "parse_message",
    "create_message",

    # Client
    "Client",
    "ClientInfo",
    "WorkerCapabilities",
    "ClientStats",
    "ConnectionStatus",
    "WorkerStatus",

    # Task
    "Task",
    "TaskType",
    "TaskContext",
    "TaskMetadata",
    "TaskQueue"
]
