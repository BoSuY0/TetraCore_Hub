"""
Security Integration Module for TetraCore Hub
Інтеграція всіх компонентів безпеки в додаток
"""

import os
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Depends
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import structlog
import redis

from core.auth_manager import get_auth_manager, get_current_user
from core.network_security import network_security, security_middleware
from core.websocket_security import ws_security_manager
from core.input_validator import InputValidator
from core.security_headers import security_headers, security_headers_middleware, security_headers_router
from core.https_enforcement import https_enforcer, https_enforcement_middleware, https_router
from web.auth import auth_router

logger = structlog.get_logger()


class SecurityIntegration:
    """Клас для інтеграції всіх компонентів безпеки"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client
        self.initialized = False

        # Ініціалізація компонентів з Redis
        if redis_client:
            get_auth_manager().redis_client = redis_client
            network_security.redis_client = redis_client
            ws_security_manager.redis_client = redis_client

        logger.info("Security integration initialized",
                   redis_enabled=redis_client is not None)

    def setup_app_security(self, app: FastAPI):
        """Налаштування безпеки для FastAPI додатка"""

        # 1. HTTPS enforcement (має бути першим)
        app.middleware("http")(https_enforcement_middleware)

        # 2. Базові security headers через middleware
        @app.middleware("http")
        async def add_security_headers(request: Request, call_next):
            response = await call_next(request)
            network_security.add_security_headers(response)
            return response

        # 3. Network security middleware (rate limiting, DDoS protection)
        app.middleware("http")(security_middleware)

        # 4. Security headers middleware (CSP, permissions policy, etc)
        app.middleware("http")(security_headers_middleware)

        # 5. Trusted host middleware - виправлено для Heroku
        self._setup_trusted_host_middleware(app)

        # 6. CORS налаштування
        network_security.setup_cors(app)

        # 7. Exception handlers
        @app.exception_handler(429)
        async def rate_limit_handler(request: Request, exc):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )

        @app.exception_handler(403)
        async def forbidden_handler(request: Request, exc):
            return JSONResponse(
                status_code=403,
                content={"detail": "Access forbidden"}
            )

        # 8. Додавання auth router
        app.include_router(auth_router)

        # 9. Додавання security management endpoints (тільки для адмінів)
        if os.getenv("ENABLE_SECURITY_ENDPOINTS", "false").lower() == "true":
            from core.network_security import security_router
            app.include_router(security_router)
            app.include_router(security_headers_router)
            app.include_router(https_router)

        logger.info("App security configured")

        self.initialized = True

    def _setup_trusted_host_middleware(self, app: FastAPI):
        """Налаштування TrustedHostMiddleware з підтримкою Heroku"""
        environment = os.getenv("ENVIRONMENT", "development")
        
        # Базові дозволені хости
        allowed_hosts = []
        
        # Для development
        if environment == "development":
            allowed_hosts.extend([
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "localhost:3000",
                "localhost:8000",
                "127.0.0.1:3000", 
                "127.0.0.1:8000"
            ])
        
        # Для Heroku production
        if os.getenv("DYNO") or environment == "production":
            # Додаємо домени Heroku
            allowed_hosts.extend([
                "hub.tetra-core.website",
                "tetracore-hub-29fb6c8b7947.herokuapp.com",
                "*.herokuapp.com",  # Для різних додатків Heroku
                "*.tetra-core.website"  # Для subdomains
            ])
        
        # Дозволені хости з змінних оточення
        env_hosts = os.getenv("ALLOWED_HOSTS", "")
        if env_hosts:
            allowed_hosts.extend([host.strip() for host in env_hosts.split(",") if host.strip()])
        
        # Логування налаштувань
        logger.info("TrustedHostMiddleware configuration", 
                   environment=environment,
                   allowed_hosts=allowed_hosts,
                   is_heroku=bool(os.getenv("DYNO")))
        
        # Додавання middleware тільки якщо є обмеження хостів
        if allowed_hosts and "*" not in allowed_hosts:
            app.add_middleware(
                TrustedHostMiddleware,
                allowed_hosts=allowed_hosts
            )
            logger.info("TrustedHostMiddleware enabled", allowed_hosts=allowed_hosts)
        else:
            logger.info("TrustedHostMiddleware disabled - no host restrictions")

    def get_websocket_authenticator(self):
        """Повертає функцію для автентифікації WebSocket"""
        return ws_security_manager.authenticate_websocket

    def get_websocket_validator(self):
        """Повертає функцію для валідації WebSocket повідомлень"""
        return ws_security_manager.validate_message

    async def validate_api_request(self, request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
        """Валідація даних API запиту"""
        # Перевірка на небезпечні патерни
        for key, value in data.items():
            if isinstance(value, str):
                # SQL injection check
                if InputValidator.check_sql_injection(value):
                    raise ValueError(f"Invalid characters in {key}")

                # XSS check
                if InputValidator.check_xss(value):
                    raise ValueError(f"Invalid HTML content in {key}")

                # Path traversal check
                if InputValidator.check_path_traversal(value):
                    raise ValueError(f"Invalid path in {key}")

        return data

    async def cleanup_expired_sessions(self):
        """Періодичне очищення застарілих сесій"""
        if not self.redis_client:
            return

        try:
            # Очищення JWT токенів з чорного списку
            pattern = "blocked_token:*"
            for key in self.redis_client.scan_iter(match=pattern):
                # Redis автоматично видалить по TTL
                pass

            # Очищення старих сесій
            pattern = "session:*"
            current_time = datetime.now(timezone.utc)
            cleaned = 0

            for key in self.redis_client.scan_iter(match=pattern):
                session_data = self.redis_client.get(key)
                if session_data:
                    try:
                        data = json.loads(session_data)
                        last_activity = datetime.fromisoformat(data.get("last_activity", ""))

                        # Видаляємо сесії старші 7 днів
                        if (current_time - last_activity).days > 7:
                            self.redis_client.delete(key)
                            cleaned += 1
                    except:
                        # Видаляємо пошкоджені сесії
                        self.redis_client.delete(key)
                        cleaned += 1

            if cleaned > 0:
                logger.info("Cleaned expired sessions", count=cleaned)

        except Exception as e:
            logger.error("Session cleanup error", error=str(e))

    def get_security_status(self) -> Dict[str, Any]:
        """Отримання статусу безпеки системи"""
        status = {
            "initialized": self.initialized,
            "redis_enabled": self.redis_client is not None,
            "components": {
                "auth_manager": "active",
                "network_security": "active",
                "websocket_security": "active",
                "input_validator": "active",
                "security_headers": "active",
                "https_enforcement": "active" if https_enforcer.enabled else "disabled"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Додаткова статистика якщо доступна
        if self.redis_client:
            try:
                # Кількість активних сесій
                sessions = len(list(self.redis_client.scan_iter(match="session:*")))
                status["active_sessions"] = sessions

                # Кількість заблокованих IP
                blocked_ips = len(list(self.redis_client.scan_iter(match="blocked_ip:*")))
                status["blocked_ips"] = blocked_ips

            except Exception as e:
                logger.error("Error getting security stats", error=str(e))

        return status


# Глобальний екземпляр для легкої інтеграції
security_integration = SecurityIntegration()


# Middleware для перевірки автентифікації на всіх endpoints
async def require_auth_middleware(request: Request, call_next):
    """Middleware що вимагає автентифікацію для всіх endpoints крім публічних"""
    if request.method == "OPTIONS":
        return await call_next(request)

    # Публічні endpoints що не потребують автентифікації
    public_paths = [
        "/api/auth/login",
        "/api/auth/refresh",
        "/health",  # Виправлено: endpoint реально на /health, а не /api/health
        "/metrics",  # Додано metrics endpoint
        "/config",   # Додано config endpoint для frontend
        "/docs",
        "/openapi.json",
        "/favicon.ico"
    ]

    # Dashboard API endpoints (потребують автентифікації але обробляються окремо)
    dashboard_paths = [
        "/dashboard/api/",
        "/api/auth/validate"
    ]

    # Статичні файли також публічні
    if request.url.path.startswith("/static/") or request.url.path == "/":
        return await call_next(request)

    # Перевірка чи шлях публічний - змінено на точне співпадіння для коротких шляхів
    if request.url.path in public_paths or any(request.url.path.startswith(path) for path in public_paths if len(path) > 10):
        return await call_next(request)

    # WebSocket має свою автентифікацію
    if request.url.path.startswith("/ws"):  # Виправлено: видалено зайвий слеш
        return await call_next(request)

    # Dashboard та auth API мають свою обробку автентифікації
    if any(request.url.path.startswith(path) for path in dashboard_paths):
        return await call_next(request)

    # Пропускаємо OPTIONS запити для CORS preflight
    if request.method == "OPTIONS":
        return await call_next(request)

    # Для всіх інших endpoints потрібна автентифікація
    try:
        # Перевірка Bearer token
        authorization = request.headers.get("Authorization")
        if not authorization or not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"}
            )

        token = authorization.split(" ")[1]
        user_data = await get_auth_manager().decode_token(token)

        # Додаємо user data до state для використання в endpoints
        request.state.user = user_data

    except Exception as e:
        logger.warning("Authentication failed", path=request.url.path, error=str(e))
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid authentication credentials"}
        )

    response = await call_next(request)
    return response


# Функція для швидкої інтеграції в існуючий додаток
def integrate_security(
    app: FastAPI,
    redis_client: Optional[redis.Redis] = None,
    require_auth: bool = True
) -> SecurityIntegration:
    """
    Швидка інтеграція всіх security компонентів в FastAPI додаток

    Args:
        app: FastAPI додаток
        redis_client: Redis клієнт для сесій та rate limiting
        require_auth: Чи вимагати автентифікацію для всіх endpoints

    Returns:
        SecurityIntegration екземпляр
    """

    # Створюємо або використовуємо глобальний екземпляр
    global security_integration
    if redis_client:
        security_integration = SecurityIntegration(redis_client)

    # Налаштовуємо безпеку додатка
    security_integration.setup_app_security(app)

    # Додаємо middleware для автентифікації якщо потрібно
    if require_auth:
        app.middleware("http")(require_auth_middleware)

    logger.info("Security fully integrated",
               redis_enabled=redis_client is not None,
               auth_required=require_auth)

    return security_integration


# Додаткові залежності для endpoints
async def get_authenticated_user(request: Request) -> Dict[str, Any]:
    """Dependency для отримання автентифікованого користувача з request.state"""
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return request.state.user


# Приклад використання в endpoints:
# @app.get("/api/protected")
# async def protected_endpoint(user: Dict = Depends(get_authenticated_user)):
#     return {"message": f"Hello {user['username']}"}


import json
from datetime import datetime, timezone
from fastapi import HTTPException
