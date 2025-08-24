"""
HTTPS/WSS Enforcement Module for TetraCore Hub
Примусове використання безпечних протоколів в production
"""

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
import structlog

from core.auth_manager import get_current_user, require_permission

logger = structlog.get_logger()

# Константи
HSTS_MAX_AGE = 31536000  # 1 рік
REDIRECT_STATUS_CODE = 301  # Permanent redirect
SECURE_SCHEMES = {"https", "wss"}
INSECURE_SCHEMES = {"http", "ws"}

# Виключення для health checks та внутрішніх сервісів
EXCLUDED_PATHS = {"/health", "/api/health", "/_health", "/metrics", "/_internal"}

# User agents що не підтримують redirect (для WebSocket)
WS_USER_AGENTS = ["websocket", "ws-client", "tetracore-worker"]


class HTTPSEnforcer:  # pylint: disable=too-many-instance-attributes
    """Клас для примусового використання HTTPS/WSS"""

    def __init__(
        self,
        *,
        enabled: bool = True,
        environment: str = "production",
        redirect_enabled: bool = True,
        hsts_enabled: bool = True,
        hsts_max_age: int = HSTS_MAX_AGE,
        hsts_include_subdomains: bool = True,
        hsts_preload: bool = False,
        exclude_paths: Optional[List[str]] = None,
        trusted_proxies: Optional[List[str]] = None,
    ):  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self.enabled = enabled and environment == "production"
        self.environment = environment
        self.redirect_enabled = redirect_enabled
        self.hsts_enabled = hsts_enabled
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.hsts_preload = hsts_preload
        self.exclude_paths = set(exclude_paths or []) | EXCLUDED_PATHS
        self.trusted_proxies = set(trusted_proxies or ["127.0.0.1", "::1"])

        # Статистика
        self.stats = {
            "total_requests": 0,
            "secure_requests": 0,
            "redirected_requests": 0,
            "blocked_requests": 0,
        }

    def is_secure_request(self, request: Request) -> bool:
        """Перевірка чи запит використовує безпечний протокол"""
        # Перевірка заголовків від проксі
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        if forwarded_proto in SECURE_SCHEMES:
            return True

        # Cloudflare specific
        cf_visitor = request.headers.get("CF-Visitor")
        if cf_visitor:
            try:
                visitor_data = json.loads(cf_visitor)
                if visitor_data.get("scheme") in SECURE_SCHEMES:
                    return True
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        # Перевірка схеми URL
        if request.url.scheme in SECURE_SCHEMES:
            return True

        # Перевірка порту (443 для HTTPS)
        if request.url.port == 443:
            return True

        # Heroku specific
        if request.headers.get("X-Forwarded-Proto") == "https":
            return True

        return False

    def is_websocket_request(self, request: Request) -> bool:
        """Перевірка чи це WebSocket запит"""
        upgrade = request.headers.get("Upgrade", "").lower()
        connection = request.headers.get("Connection", "").lower()

        return upgrade == "websocket" and "upgrade" in connection

    def is_excluded_path(self, path: str) -> bool:
        """Перевірка чи шлях виключений з перевірки"""
        # Точне співпадіння
        if path in self.exclude_paths:
            return True

        # Префікс співпадіння
        for excluded in self.exclude_paths:
            if path.startswith(excluded):
                return True

        return False

    def is_trusted_proxy(self, request: Request) -> bool:
        """Перевірка чи запит від довіреного проксі"""
        client_host = request.client.host if request.client else None
        if not client_host:
            return False

        return client_host in self.trusted_proxies

    def get_secure_url(self, request: Request) -> str:
        """Отримання безпечної версії URL"""
        url_parts = list(urlparse(str(request.url)))

        # Заміна схеми
        if url_parts[0] == "http":
            url_parts[0] = "https"
        elif url_parts[0] == "ws":
            url_parts[0] = "wss"

        # Видалення порту якщо стандартний
        if url_parts[1].endswith(":80") or url_parts[1].endswith(":443"):
            url_parts[1] = url_parts[1].rsplit(":", 1)[0]

        return urlunparse(url_parts)

    def build_hsts_header(self) -> str:
        """Побудова HSTS header"""
        parts = [f"max-age={self.hsts_max_age}"]

        if self.hsts_include_subdomains:
            parts.append("includeSubDomains")

        if self.hsts_preload:
            parts.append("preload")

        return "; ".join(parts)

    async def process_request(self, request: Request) -> Optional[Response]:
        """Обробка запиту для примусового HTTPS"""
        self.stats["total_requests"] += 1

        # Якщо вимкнено, нічого не робимо
        if not self.enabled:
            return None

        # Перевірка виключень
        if self.is_excluded_path(request.url.path):
            logger.debug("Path excluded from HTTPS enforcement", path=request.url.path)
            return None

        # Перевірка чи запит безпечний
        is_secure = self.is_secure_request(request)

        if is_secure:
            self.stats["secure_requests"] += 1
            return None

        # Обробка небезпечних запитів
        is_websocket = self.is_websocket_request(request)

        # WebSocket запити не можуть бути перенаправлені
        if is_websocket:
            self.stats["blocked_requests"] += 1
            logger.warning(
                "Insecure WebSocket connection blocked",
                path=request.url.path,
                client=request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=426,  # Upgrade Required
                content={
                    "error": "Secure WebSocket connection required",
                    "detail": "Please use WSS protocol instead of WS",
                },
                headers={"Upgrade": "websocket", "Connection": "Upgrade"},
            )

        # HTTP запити можуть бути перенаправлені
        if self.redirect_enabled:
            self.stats["redirected_requests"] += 1
            secure_url = self.get_secure_url(request)

            logger.info(
                "Redirecting to HTTPS",
                from_url=str(request.url),
                to_url=secure_url,
                client=request.client.host if request.client else "unknown",
            )

            return RedirectResponse(url=secure_url, status_code=REDIRECT_STATUS_CODE)

        # Якщо redirect вимкнено, блокуємо запит
        self.stats["blocked_requests"] += 1
        logger.warning(
            "Insecure request blocked",
            path=request.url.path,
            client=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=426,
            detail="HTTPS required",  # Upgrade Required
        )

    def add_security_headers(self, response: Response, is_secure: bool):
        """Додавання security headers до відповіді"""
        if is_secure and self.hsts_enabled:
            response.headers["Strict-Transport-Security"] = self.build_hsts_header()

        # Додаткові headers для безпеки
        if is_secure:
            response.headers["Content-Security-Policy"] = response.headers.get(
                "Content-Security-Policy", ""
            ).replace("http:", "https:")

    def get_stats(self) -> Dict[str, Any]:
        """Отримання статистики"""
        total = self.stats["total_requests"] or 1  # Уникнення ділення на 0

        return {
            "enabled": self.enabled,
            "environment": self.environment,
            "total_requests": self.stats["total_requests"],
            "secure_requests": self.stats["secure_requests"],
            "redirected_requests": self.stats["redirected_requests"],
            "blocked_requests": self.stats["blocked_requests"],
            "secure_percentage": round(
                (self.stats["secure_requests"] / total) * 100, 2
            ),
            "redirect_percentage": round(
                (self.stats["redirected_requests"] / total) * 100, 2
            ),
        }

    def reset_stats(self):
        """Скидання статистики"""
        self.stats = {
            "total_requests": 0,
            "secure_requests": 0,
            "redirected_requests": 0,
            "blocked_requests": 0,
        }


# Глобальний екземпляр - ВІДКЛЮЧЕНО ДЛЯ DEVELOPMENT
https_enforcer = HTTPSEnforcer(
    enabled=False,  # Вимкнуто за замовчуванням
    environment="development",  # Development за замовчуванням
    redirect_enabled=False,  # Вимкнуто редіректи
    hsts_enabled=False,  # Вимкнуто HSTS
)


# Middleware для FastAPI
async def https_enforcement_middleware(request: Request, call_next):
    """Middleware для примусового HTTPS"""
    # Обробка запиту
    redirect_response = await https_enforcer.process_request(request)
    if redirect_response:
        return redirect_response

    # Виклик наступного middleware
    response = await call_next(request)

    # Додавання HSTS header якщо потрібно
    is_secure = https_enforcer.is_secure_request(request)
    https_enforcer.add_security_headers(response, is_secure)

    return response


# Допоміжні функції
def configure_https_enforcement(
    app, enabled: Optional[bool] = None, environment: Optional[str] = None, **kwargs
):
    """Налаштування HTTPS enforcement для додатка"""

    # Оновлення конфігурації якщо потрібно
    if enabled is not None:
        https_enforcer.enabled = enabled
    if environment is not None:
        https_enforcer.environment = environment

    # Оновлення інших параметрів
    for key, value in kwargs.items():
        if hasattr(https_enforcer, key):
            setattr(https_enforcer, key, value)

    # Додавання middleware
    app.middleware("http")(https_enforcement_middleware)

    logger.info(
        "HTTPS enforcement configured",
        enabled=https_enforcer.enabled,
        environment=https_enforcer.environment,
    )


# API endpoints для моніторингу
https_router = APIRouter(prefix="/api/security/https", tags=["security"])


@https_router.get("/stats")
@require_permission("settings.view")
async def get_https_stats(_user: Dict = Depends(get_current_user)):
    """Отримання статистики HTTPS enforcement"""
    return https_enforcer.get_stats()


@https_router.post("/reset-stats")
@require_permission("settings.manage")
async def reset_https_stats(_user: Dict = Depends(get_current_user)):
    """Скидання статистики HTTPS enforcement"""
    https_enforcer.reset_stats()
    return {"message": "Stats reset successfully"}


@https_router.get("/config")
@require_permission("settings.view")
async def get_https_config(_user: Dict = Depends(get_current_user)):
    """Отримання конфігурації HTTPS enforcement"""
    return {
        "enabled": https_enforcer.enabled,
        "environment": https_enforcer.environment,
        "redirect_enabled": https_enforcer.redirect_enabled,
        "hsts_enabled": https_enforcer.hsts_enabled,
        "hsts_max_age": https_enforcer.hsts_max_age,
        "hsts_include_subdomains": https_enforcer.hsts_include_subdomains,
        "hsts_preload": https_enforcer.hsts_preload,
        "exclude_paths": list(https_enforcer.exclude_paths),
    }
