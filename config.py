"""
TetraCore Stream Hub Configuration

Централізована конфігурація для StreamHub з підтримкою різних середовищ,
змінних оточення та системи автентифікації.
"""

import os
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass, field

# Redis конфігурація тепер через змінні середовища (.env файл)


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


def is_heroku_environment() -> bool:
    """Перевіряє чи код запущено на Heroku"""
    return bool(os.getenv("DYNO") or os.getenv("PORT") and os.getenv("HOME") == "/app")


# Завантаження змінних з .env файлу
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv не обов'язкова залежність


@dataclass
class Settings:
    """Основні налаштування StreamHub"""

    # Основні параметри додатка
    app_name: str = "TetraCore StreamHub"
    app_version: str = "2.0.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    require_authentication: bool = True

    # Мережеві налаштування
    host: str = "0.0.0.0"
    port: int = 8000
    custom_domain: str = "hub.tetra-core.website"

    # WebSocket налаштування
    websocket_path: str = "/ws"
    websocket_timeout: int = 600  # Збільшено з 120 до 600 секунд (10 хвилин)
    websocket_heartbeat_interval: int = 60  # Збільшено з 30 до 60 секунд
    max_connections: int = 1000

    # Автентифікація та безпека
    admin_username: str = None
    admin_password: str = None
    session_duration_hours: int = 24
    cleanup_interval_minutes: int = 60
    require_username: bool = False
    require_photo: bool = False

    # Role-based permissions
    role_permissions: dict = None

    # Redis налаштування (Redis завжди увімкнений)
    redis_enabled: bool = True
    redis_url: str = ""  # Має бути встановлено через REDIS_URL
    redis_tls_enabled: bool = True  # За замовчуванням TLS для продакшн
    redis_ssl_cert_reqs: str = "required"
    redis_max_connections: int = (
        50  # Збільшено з 10 до 50 для вирішення "Too many connections"
    )
    redis_retry_on_timeout: bool = True
    redis_health_check_interval: int = 120  # Збільшено до 2 хвилин для Upstash
    # Дозволити старт без Redis у продакшені (керується через ENV)
    allow_start_without_redis: bool = False

    # Redis Sentinel налаштування
    redis_sentinel_urls: List[str] = field(default_factory=list)
    redis_sentinel_service_name: str = "tetracore-master"

    # Redis Cluster налаштування
    redis_cluster_nodes: List[str] = field(default_factory=list)

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
    auth_token_active: Optional[str] = None
    auth_token_next: Optional[str] = None
    enable_token_rotation: bool = False
    token_rotation_interval_minutes: int = 1440
    rate_limit_requests: int = 1000

    # Оптимізація продуктивності
    enable_compression: bool = True
    message_queue_size: int = 10000
    worker_pool_size: int = 10

    def __post_init__(self):
        """Ініціалізація після створення"""
        if self.allowed_origins is None:
            self.allowed_origins = ["*"]

        if self.role_permissions is None:
            self.role_permissions = {
                "admin": [
                    # Основні права дашборду
                    "dashboard.view",
                    "dashboard.manage",
                    # Права на клієнтів
                    "clients.view",
                    "clients.manage",
                    "clients.create",
                    "clients.delete",
                    # Права на завдання
                    "tasks.view",
                    "tasks.manage",
                    "tasks.create",
                    "tasks.delete",
                    "tasks.execute",
                    # Права на налаштування
                    "settings.view",
                    "settings.manage",
                    "settings.update",
                    # Права на логи
                    "logs.view",
                    "logs.manage",
                    "logs.export",
                    # Права на авторизацію
                    "auth.manage",
                    "auth.view",
                    "auth.sessions",
                    # Права на метрики та моніторинг
                    "metrics.view",
                    "metrics.manage",
                    "metrics.export",
                    "monitoring.view",
                    "monitoring.manage",
                    # Права на систему
                    "system.view",
                    "system.manage",
                    "system.restart",
                    "system.config",
                    # Права на Redis
                    "redis.view",
                    "redis.manage",
                    # Права на WebSocket
                    "websocket.view",
                    "websocket.manage",
                    # Права на API
                    "api.view",
                    "api.manage",
                    "api.debug",
                    # Права на безпеку
                    "security.view",
                    "security.manage",
                    # Права на звіти
                    "reports.view",
                    "reports.create",
                    "reports.export",
                    # Повний доступ
                    "*",  # Універсальне право для адміна
                ]
            }

        # Завантаження з змінних середовища
        self._load_from_env()
        self._setup_auth()

    def _load_from_env(self):
        """Завантаження налаштувань зі змінних середовища"""
        # СПОЧАТКУ завантажуємо ENVIRONMENT з змінних середовища
        env_name = os.getenv("ENVIRONMENT", self.environment.value)
        try:
            self.environment = Environment(env_name)
        except ValueError:
            pass

        # ПОТІМ перевіряємо Heroku тільки якщо ENVIRONMENT не встановлено явно
        if env_name == self.environment.value and is_heroku_environment():
            self.environment = Environment.PRODUCTION
            # Redis завжди увімкнений; наявність URL визначає працездатність клієнта
            self.redis_enabled = True
            self.debug = False

        # Інші налаштування
        # Ігноруємо REDIS_ENABLED: Redis завжди увімкнений
        self.redis_enabled = True

        # Підтримка REDIS_TLS_URL (пріоритетніше за REDIS_URL якщо задано)
        redis_tls_url = os.getenv("REDIS_TLS_URL")
        if redis_tls_url:
            self.redis_url = redis_tls_url
        else:
            self.redis_url = os.getenv("REDIS_URL", self.redis_url)
        self.redis_tls_enabled = os.getenv(
            "REDIS_TLS_ENABLED", str(self.redis_tls_enabled)
        ).lower() in ("true", "1", "yes")
        self.redis_ssl_cert_reqs = os.getenv(
            "REDIS_SSL_CERT_REQS", self.redis_ssl_cert_reqs
        )

        # Дозвіл на старт без Redis (для підвищення живучості сервісу)
        self.allow_start_without_redis = os.getenv(
            "ALLOW_START_WITHOUT_REDIS", str(self.allow_start_without_redis)
        ).lower() in ("true", "1", "yes")

        # Завантаження Sentinel URLs
        sentinel_urls = os.getenv("REDIS_SENTINEL_URLS")
        if sentinel_urls:
            self.redis_sentinel_urls = [url.strip() for url in sentinel_urls.split(",")]

        # Завантаження Cluster nodes
        cluster_nodes = os.getenv("REDIS_CLUSTER_NODES")
        if cluster_nodes:
            self.redis_cluster_nodes = [
                node.strip() for node in cluster_nodes.split(",")
            ]

        self.port = int(os.getenv("PORT", self.port))
        self.host = os.getenv("HOST", self.host)
        self.debug = os.getenv("DEBUG", str(self.debug)).lower() in ("true", "1", "yes")
        self.auth_token = os.getenv("AUTH_TOKEN", self.auth_token)
        # Dual-token ротація
        self.auth_token_active = os.getenv("AUTH_TOKEN_ACTIVE", self.auth_token_active)
        self.auth_token_next = os.getenv("AUTH_TOKEN_NEXT", self.auth_token_next)
        self.enable_token_rotation = os.getenv(
            "ENABLE_TOKEN_ROTATION", str(self.enable_token_rotation)
        ).lower() in ("true", "1", "yes")
        try:
            self.token_rotation_interval_minutes = int(
                os.getenv(
                    "TOKEN_ROTATION_INTERVAL_MINUTES",
                    str(self.token_rotation_interval_minutes),
                )
            )
        except Exception:
            pass
        self.require_authentication = os.getenv(
            "REQUIRE_AUTHENTICATION", str(self.require_authentication)
        ).lower() in ("true", "1", "yes")

        log_level_name = os.getenv("LOG_LEVEL", self.log_level.value)
        try:
            self.log_level = LogLevel(log_level_name)
        except ValueError:
            pass

        # Динамічні CORS налаштування
        self._setup_cors_origins()

    def _setup_auth(self):
        """Налаштування автентифікації"""
        self.admin_username = os.getenv("ADMIN_USERNAME")
        self.admin_password = os.getenv("ADMIN_PASSWORD")

        # Перевірка та налаштування дефолтних значень для розробки
        if not self.admin_username or not self.admin_password:
            if self.environment == Environment.PRODUCTION:
                raise ValueError(
                    "ADMIN_USERNAME та ADMIN_PASSWORD мають бути встановлені в продакшені!"
                )
            # В development також вимагаємо встановлення через змінні оточення
            # для підвищення безпеки

    def _setup_cors_origins(self):
        """Налаштування CORS origins залежно від середовища"""
        origins = []

        # Production domains
        if is_heroku_environment() or self.environment == Environment.PRODUCTION:
            origins.extend(
                [
                    "https://hub.tetra-core.website",
                    "https://tetra-core-hub-29fb6c8b7947.herokuapp.com",
                ]
            )

        # Локальні URL для розробки
        if self.environment == Environment.DEVELOPMENT:
            origins.extend(
                [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "http://localhost:8000",
                    "http://127.0.0.1:8000",
                ]
            )

        # Додаткові origins з змінних середовища
        extra_origins = os.getenv("ALLOWED_ORIGINS")
        if extra_origins:
            origins.extend([origin.strip() for origin in extra_origins.split(",")])

        # Якщо нічого не налаштовано, дозволяємо все для розробки
        if not origins and self.environment == Environment.DEVELOPMENT:
            origins = ["*"]

        self.allowed_origins = origins

    # Utility methods
    def is_production(self) -> bool:
        """Перевірка чи це продакшн середовище"""
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        """Перевірка чи це девелопмент середовище"""
        return self.environment == Environment.DEVELOPMENT

    def is_testing(self) -> bool:
        """Перевірка чи це тестове середовище"""
        return self.environment == Environment.TESTING

    # Configuration getters
    def get_redis_config(self) -> dict:
        """Отримання конфігурації Redis"""
        return {
            "enabled": True,
            "url": self.redis_url,
            "tls_enabled": self.redis_tls_enabled,
            "ssl_cert_reqs": self.redis_ssl_cert_reqs,
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

    def get_auth_config(self) -> dict:
        """Отримання конфігурації автентифікації"""
        return {
            "admin_username": self.admin_username,
            "admin_password": self.admin_password,
            "session_duration_hours": self.session_duration_hours,
            "cleanup_interval_minutes": self.cleanup_interval_minutes,
            "require_username": self.require_username,
            "require_photo": self.require_photo,
            "role_permissions": self.role_permissions,
        }

    # URL getters
    def get_app_url(self) -> str:
        """Отримання URL додатку (Heroku або локальний)"""
        # В development режимі завжди використовуємо localhost
        if self.environment == Environment.DEVELOPMENT:
            return f"http://localhost:{self.port}"

        # В production режимі перевіряємо Heroku
        if is_heroku_environment():
            return "https://hub.tetra-core.website"

        return f"http://localhost:{self.port}"

    def get_frontend_url(self) -> str:
        """Отримання URL frontend"""
        # В development режимі frontend завжди на 3000
        if self.environment == Environment.DEVELOPMENT:
            return "http://localhost:3000"

        # В production режимі використовуємо той самий URL що і backend
        if is_heroku_environment():
            return self.get_app_url()

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

    # Auth utility methods
    def get_user_role(self, user_id: str = None) -> str:
        """Визначення ролі користувача"""
        return "admin"  # Поки що тільки адміністратор

    def get_user_permissions(self, user_id: str = None) -> List[str]:
        """Отримання дозволів користувача"""
        return self.role_permissions.get("admin", [])

    def validate_auth_config(self) -> List[str]:
        """Валідація конфігурації автентифікації"""
        errors = []

        if not self.admin_username:
            errors.append("ADMIN_USERNAME not configured")
        if not self.admin_password:
            errors.append("ADMIN_PASSWORD not configured")

        if self.admin_username and len(self.admin_username) < 3:
            errors.append("ADMIN_USERNAME must be at least 3 characters long")
        if self.admin_password and len(self.admin_password) < 8:
            errors.append("ADMIN_PASSWORD must be at least 8 characters long")

        return errors

    def diagnose_environment(self) -> dict:
        """Діагностика середовища виконання"""
        from datetime import datetime
        import sys
        import socket

        info = {
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version,
            "platform": sys.platform,
            "environment": {
                "is_heroku": is_heroku_environment(),
                "dyno": os.getenv("DYNO"),
                "port": os.getenv("PORT"),
                "home": os.getenv("HOME"),
                "environment": self.environment.value,
                "debug": self.debug,
                "log_level": self.log_level.value,
            },
            "urls": {
                "backend": self.get_backend_url(),
                "frontend": self.get_frontend_url(),
                "dashboard": self.get_dashboard_url(),
                "websocket": self.get_websocket_url(),
            },
            "redis": {"enabled": True, "url_safe": self._safe_redis_url()},
            "auth": {
                "require_authentication": self.require_authentication,
                "admin_configured": bool(self.admin_username and self.admin_password),
            },
        }

        try:
            info["hostname"] = socket.gethostname()
        except Exception:
            info["hostname"] = "<unknown>"

        return info

    def _safe_redis_url(self) -> str:
        """Повертає Redis URL з прихованим паролем"""
        if not self.redis_url:
            return "not configured"

        if "@" in self.redis_url:
            parts = self.redis_url.split("@")
            if len(parts) > 1:
                protocol_part = parts[0].split("//")[0]
                return f"{protocol_part}//<***hidden***>@{parts[1]}"
        return "<***hidden***>"


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
    "redis_enabled": True,
    "enable_metrics": True,
}

PRODUCTION_OVERRIDES = {
    "debug": False,
    "log_level": LogLevel.WARNING,
    "enable_metrics": True,
    "enable_compression": True,
    "redis_enabled": True,
}

TESTING_OVERRIDES = {
    "debug": True,
    "log_level": LogLevel.DEBUG,
    "redis_enabled": True,
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


# Backward compatibility aliases
def get_user_role(user_id: str = None) -> str:
    """Backward compatibility for auth_config.py"""
    return settings.get_user_role(user_id)


def get_user_permissions(user_id: str = None) -> List[str]:
    """Backward compatibility for auth_config.py"""
    return settings.get_user_permissions(user_id)


# Constants for backward compatibility (deprecated - use settings directly)
# ADMIN_USERNAME and ADMIN_PASSWORD removed for security - use environment variables
SESSION_DURATION_HOURS = settings.session_duration_hours
CLEANUP_INTERVAL_MINUTES = settings.cleanup_interval_minutes
REQUIRE_USERNAME = settings.require_username
REQUIRE_PHOTO = settings.require_photo
ROLE_PERMISSIONS = settings.role_permissions
