"""
TetraCore Stream Hub Configuration

Централізована конфігурація для StreamHub з підтримкою різних середовищ
та змінних оточення для розгортання на Heroku.
"""

import os
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass


class Environment(str, Enum):
    """Типи середовищ розгортання"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LogLevel(str, Enum):
    """Рівні логування"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class Settings:
    """Основні налаштування StreamHub"""

    # Основні параметри додатка
    app_name: str = "TetraCore StreamHub"
    app_version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # Мережеві налаштування
    host: str = "0.0.0.0"
    port: int = 8000

    # WebSocket налаштування
    websocket_path: str = "/ws"
    websocket_timeout: int = 60
    websocket_heartbeat_interval: int = 30
    max_connections: int = 1000

    # Redis налаштування
    redis_enabled: bool = True
    redis_url: str = "redis://localhost:6379"
    redis_max_connections: int = 20
    redis_retry_on_timeout: bool = True
    redis_health_check_interval: int = 30

    # Pub/Sub канали
    redis_task_channel: str = "tetra:tasks"
    redis_result_channel: str = "tetra:results"
    redis_broadcast_channel: str = "tetra:broadcast"
    redis_health_channel: str = "tetra:health"

    # Налаштування балансування
    task_timeout: int = 300
    max_retries: int = 3
    retry_delay: int = 5
    worker_selection_strategy: str = "round_robin"

    # Логування
    log_level: LogLevel = LogLevel.INFO
    log_format: str = "json"
    log_file: Optional[str] = None

    # Моніторинг та метрики
    enable_metrics: bool = True
    metrics_port: int = 9090
    health_check_endpoint: str = "/health"

    # Безпека
    allowed_origins: List[str] = None
    auth_token: Optional[str] = None
    rate_limit_requests: int = 1000

    # Оптимізація продуктивності
    enable_compression: bool = True
    message_queue_size: int = 10000
    worker_pool_size: int = 10

    def __post_init__(self):
        """Ініціалізація після створення"""
        if self.allowed_origins is None:
            self.allowed_origins = ["*"]

        # Завантаження з змінних середовища
        self._load_from_env()

    def _load_from_env(self):
        """Завантаження налаштувань зі змінних середовища"""
        self.redis_enabled = os.getenv("REDIS_ENABLED", str(self.redis_enabled)).lower() in ("true", "1", "yes")
        self.redis_url = os.getenv("REDIS_URL", self.redis_url)
        self.port = int(os.getenv("PORT", self.port))
        self.host = os.getenv("HOST", self.host)
        self.debug = os.getenv("DEBUG", str(self.debug)).lower() in ("true", "1", "yes")
        self.auth_token = os.getenv("AUTH_TOKEN", self.auth_token)

        env_name = os.getenv("ENVIRONMENT", self.environment.value)
        try:
            self.environment = Environment(env_name)
        except ValueError:
            pass

        log_level_name = os.getenv("LOG_LEVEL", self.log_level.value)
        try:
            self.log_level = LogLevel(log_level_name)
        except ValueError:
            pass

    def is_production(self) -> bool:
        """Перевірка чи це продакшн середовище"""
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        """Перевірка чи це девелопмент середовище"""
        return self.environment == Environment.DEVELOPMENT

    def is_testing(self) -> bool:
        """Перевірка чи це тестове середовище"""
        return self.environment == Environment.TESTING

    def get_redis_config(self) -> dict:
        """Отримання конфігурації Redis"""
        return {
            "enabled": self.redis_enabled,
            "url": self.redis_url,
            "max_connections": self.redis_max_connections,
            "retry_on_timeout": self.redis_retry_on_timeout,
            "health_check_interval": self.redis_health_check_interval,
        }

    def get_websocket_config(self) -> dict:
        """Отримання конфігурації WebSocket"""
        return {
            "path": self.websocket_path,
            "timeout": self.websocket_timeout,
            "heartbeat_interval": self.websocket_heartbeat_interval,
            "max_connections": self.max_connections,
        }


# Глобальний екземпляр налаштувань
settings = Settings()


def get_settings() -> Settings:
    """Отримання поточних налаштувань"""
    return settings


def update_settings(**kwargs) -> Settings:
    """Оновлення налаштувань"""
    global settings
    for key, value in kwargs.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return settings


# Налаштування для різних середовищ
DEVELOPMENT_OVERRIDES = {
    "debug": True,
    "log_level": LogLevel.DEBUG,
    "redis_enabled": False,  # Для локальної розробки Redis не обов'язковий
    "redis_url": "redis://localhost:6379",
    "enable_metrics": True,
}

PRODUCTION_OVERRIDES = {
    "debug": False,
    "log_level": LogLevel.INFO,
    "enable_metrics": True,
    "enable_compression": True,
}

TESTING_OVERRIDES = {
    "debug": True,
    "log_level": LogLevel.DEBUG,
    "redis_url": "redis://localhost:6379/1",  # Окрема база для тестів
    "enable_metrics": False,
}


def configure_for_environment(env: Environment):
    """Конфігурація для конкретного середовища"""
    overrides = {}

    if env == Environment.DEVELOPMENT:
        overrides = DEVELOPMENT_OVERRIDES
    elif env == Environment.PRODUCTION:
        overrides = PRODUCTION_OVERRIDES
    elif env == Environment.TESTING:
        overrides = TESTING_OVERRIDES

    update_settings(**overrides)


# Автоматична конфігурація при імпорті
if settings.environment:
    configure_for_environment(settings.environment)
