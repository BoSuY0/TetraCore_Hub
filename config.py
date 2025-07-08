"""
TetraCore Stream Hub Configuration

Централізована конфігурація для StreamHub з підтримкою різних середовищ
та змінних оточення для розгортання на Heroku.
"""

import os
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass
import socket


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


# Функція detect_heroku_app_name видалена - використовуємо статичний домен


def is_heroku_environment() -> bool:
    """Перевіряє чи код запущено на Heroku"""
    return bool(os.getenv("DYNO") or os.getenv("PORT") and os.getenv("HOME") == "/app")


@dataclass
class Settings:
    """Основні налаштування StreamHub"""

    # Основні параметри додатка
    app_name: str = "TetraCore StreamHub"
    app_version: str = "1.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    require_authentication: bool = True

    # Мережеві налаштування
    host: str = "0.0.0.0"
    port: int = 8000
    custom_domain: str = "hub.tetra-core.website"

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

    # Redis Sentinel налаштування
    redis_sentinel_urls: List[str] = None  # ["host1:26379", "host2:26379"]
    redis_sentinel_service_name: str = "tetracore-master"

    # Redis Cluster налаштування
    redis_cluster_nodes: List[str] = None  # ["host1:7000", "host2:7001"]

    # Pipeline налаштування
    redis_pipeline_enabled: bool = True
    redis_pipeline_batch_size: int = 100
    redis_pipeline_flush_interval: float = 0.1

    # TTL налаштування (в секундах)
    redis_default_ttl: int = 86400  # 24 години
    redis_cleanup_interval: int = 3600  # 1 година

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

        # Завантаження Sentinel URLs
        sentinel_urls = os.getenv("REDIS_SENTINEL_URLS")
        if sentinel_urls:
            self.redis_sentinel_urls = [url.strip() for url in sentinel_urls.split(",")]

        # Завантаження Cluster nodes
        cluster_nodes = os.getenv("REDIS_CLUSTER_NODES")
        if cluster_nodes:
            self.redis_cluster_nodes = [node.strip() for node in cluster_nodes.split(",")]

        self.port = int(os.getenv("PORT", self.port))
        self.host = os.getenv("HOST", self.host)
        self.debug = os.getenv("DEBUG", str(self.debug)).lower() in ("true", "1", "yes")
        self.auth_token = os.getenv("AUTH_TOKEN", self.auth_token)
        self.require_authentication = os.getenv("REQUIRE_AUTHENTICATION", str(self.require_authentication)).lower() in ("true", "1", "yes")

        # Автоматичне визначення Heroku середовища
        if is_heroku_environment():
            self.environment = Environment.PRODUCTION
            self.redis_enabled = True  # На Heroku зазвичай використовуємо Redis
            self.debug = False

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

        # Динамічні CORS налаштування
        self._setup_cors_origins()

    def _setup_cors_origins(self):
        """Налаштування CORS origins залежно від середовища"""
        origins = []

        # Production domains
        if is_heroku_environment() or self.environment == Environment.PRODUCTION:
            # Custom domain
            origins.extend([
                "https://hub.tetra-core.website",
                "https://tetra-core-hub-29fb6c8b7947.herokuapp.com"
            ])

        # Локальні URL для розробки
        if self.environment == Environment.DEVELOPMENT:
            origins.extend([
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:8000",
                "http://127.0.0.1:8000"
            ])

        # Додаткові origins з змінних середовища
        extra_origins = os.getenv("ALLOWED_ORIGINS")
        if extra_origins:
            origins.extend([origin.strip() for origin in extra_origins.split(",")])

        # Якщо нічого не налаштовано, дозволяємо все для розробки
        if not origins and self.environment == Environment.DEVELOPMENT:
            origins = ["*"]

        self.allowed_origins = origins

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
            "sentinel_urls": self.redis_sentinel_urls,
            "cluster_nodes": self.redis_cluster_nodes,
            "pipeline_enabled": self.redis_pipeline_enabled,
            "pipeline_batch_size": self.redis_pipeline_batch_size,
            "pipeline_flush_interval": self.redis_pipeline_flush_interval,
            "default_ttl": self.redis_default_ttl,
        }

    def get_websocket_config(self) -> dict:
        """Отримання конфігурації WebSocket"""
        return {
            "path": self.websocket_path,
            "timeout": self.websocket_timeout,
            "heartbeat_interval": self.websocket_heartbeat_interval,
            "max_connections": self.max_connections,
        }

    def get_app_url(self) -> str:
        """Отримання URL додатку (Heroku або локальний)"""
        # Перевіряємо чи це Heroku
        if is_heroku_environment():
            # Використовуємо кастомний домен
            return "https://hub.tetra-core.website"

        # Для локальної розробки
        if self.environment == Environment.DEVELOPMENT:
            return f"http://localhost:{self.port}"

        # Для production без Heroku
        return f"http://localhost:{self.port}"

    def get_frontend_url(self) -> str:
        """Отримання URL frontend"""
        # На Heroku frontend та backend на одному домені
        if is_heroku_environment():
            return self.get_app_url()

        # Для локальної розробки frontend на порту 3000
        if self.environment == Environment.DEVELOPMENT:
            return "http://localhost:3000"

        return self.get_app_url()

    def get_backend_url(self) -> str:
        """Отримання URL backend"""
        return self.get_app_url()

    def get_dashboard_url(self) -> str:
        """Отримання URL dashboard"""
        return f"{self.get_app_url()}/dashboard"

    def get_websocket_url(self) -> str:
        """Отримання WebSocket URL"""
        app_url = self.get_app_url()
        protocol = "wss" if app_url.startswith("https") else "ws"
        domain = app_url.replace("https://", "").replace("http://", "")
        return f"{protocol}://{domain}/ws"


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
    "enable_metrics": True
}

PRODUCTION_OVERRIDES = {
    "debug": False,
    "log_level": LogLevel.WARNING,  # Змінено з INFO на WARNING для зменшення логів
    "enable_metrics": True,
    "enable_compression": True,
    "redis_enabled": True,  # Redis увімкнений в продакшені
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
