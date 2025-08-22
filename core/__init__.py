"""
TetraCore StreamHub Core Module

Основний модуль StreamHub, який забезпечує централізовану маршрутизацію
завдань між ботом і воркерами з мінімальною затримкою.
"""

from core.hub import StreamHub
from core.client_manager import ClientManager
from core.task_router import TaskRouter
from core.redis_manager import RedisManager
from core.websocket_manager import WebSocketManager
from core.health_monitor import HealthMonitor
from core.metrics_collector import MetricsCollector

__all__ = [
    "StreamHub",
    "ClientManager",
    "TaskRouter",
    "RedisManager",
    "WebSocketManager",
    "HealthMonitor",
    "MetricsCollector",
]

__version__ = "1.0.0"
__author__ = "TetraCore Team"
__description__ = "Централізований Stream Hub для TetraCore"
