"""
Authentication endpoints for TetraCore Hub
"""

import os
import json
import uuid
import hashlib
from datetime import datetime
from typing import Dict, List
import inspect

from fastapi import APIRouter, HTTPException, Depends, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import structlog
import redis

# Імпорт нового менеджера автентифікації
from core.auth_manager import (
    get_auth_manager,
    get_current_user,
    require_permission,
    require_role,
    SERVER_BOOT_ID,
    REFRESH_TOKEN_EXPIRE_DAYS,
)  # pylint: disable=import-error
from core.secrets_manager import get_secrets_manager  # pylint: disable=import-error
from core.network_security import rate_limit  # pylint: disable=import-error
from config import (
    get_settings,
    get_user_role,
    get_user_permissions,
)  # pylint: disable=import-error


# Модель для валідації сесії
class SessionValidation(BaseModel):
    """Модель запиту для валідації сесії."""

    sessionId: str


# Модель для виходу
class LogoutRequest(BaseModel):
    """Модель запиту для виходу з системи."""

    sessionId: str


# Модель для входу з логіном та паролем
class LoginRequest(BaseModel):
    """Модель запиту для входу користувача."""

    username: str
    password: str


# Модель для refresh токена
class RefreshTokenRequest(BaseModel):
    """Модель запиту для оновлення токена доступу."""

    refresh_token: str


# Модель користувача
class User(BaseModel):
    """Модель користувача для відповіді API."""

    id: str
    username: str
    role: str = "admin"
    permissions: List[str] = Field(default_factory=list)
    sessionId: str
    loginTime: datetime
    lastActivity: datetime


logger = structlog.get_logger()

# Security схема для Bearer токенів
security = HTTPBearer()


def get_user_role_and_permissions(user_id: str) -> tuple[str, List[str]]:
    """Визначення ролі та дозволів користувача"""
    settings = get_settings()

    # Для адміна повертаємо відповідну роль та дозволи
    if user_id == "admin":
        return "admin", settings.role_permissions["admin"]

    # Для інших користувачів можна додати логіку
    role = get_user_role(user_id)
    permissions = get_user_permissions(user_id)
    return role, permissions


def get_client_ip(request: Request) -> str:
    """Отримання IP адреси клієнта з урахуванням довірених проксі"""
    trusted_proxies = [
        ip.strip() for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",") if ip.strip()
    ]
    client_host = request.client.host if request.client else None

    # Перевіряємо заголовки тільки якщо запит прийшов від довіреного проксі
    if client_host and client_host in trusted_proxies:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

    # Fallback на безпосередній IP клієнта
    return client_host or "127.0.0.1"


# Router для auth ендпоінтів
auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])


@auth_router.post("/login")
async def login(request: Request, credentials: LoginRequest):
    """Авторизація користувача з JWT токенами"""
    # pylint: disable=too-many-locals

    client_ip = get_client_ip(request)

    # Перевірка rate limiting
    auth_mgr = get_auth_manager()
    if not auth_mgr.check_login_attempts(credentials.username, client_ip):
        logger.warning(
            "Too many login attempts", username=credentials.username, ip=client_ip
        )
        raise HTTPException(
            status_code=429, detail="Too many login attempts. Please try again later."
        )
    # Перевірка lockout
    if (
        get_settings().environment == get_settings().environment.PRODUCTION
        and await auth_mgr.is_locked(credentials.username, client_ip)
    ):
        raise HTTPException(
            status_code=429, detail="Account temporarily locked due to failed attempts"
        )

    # Логування для діагностики
    logger.info(
        "Login attempt",
        username_present=bool(credentials.username),
        ip=client_ip,
        server_boot_id=SERVER_BOOT_ID[:8] + "...",
    )
    # Додатковий DEBUG-контекст (без секретів)
    logger.debug(
        "Auth debug context",
        environment=os.getenv("ENVIRONMENT", "development").lower(),
        pytest=bool(os.getenv("PYTEST_CURRENT_TEST")),
        secrets_force_refresh=os.getenv("SECRETS_FORCE_ENV_REFRESH", "0"),
    )

    # Отримання credentials через secrets manager
    secrets_mgr = get_secrets_manager()
    admin_username = secrets_mgr.get_secret("ADMIN_USERNAME")
    admin_password = secrets_mgr.get_secret("ADMIN_PASSWORD")

    # Мінімальне логування без чутливих даних
    logger.info(
        "Checking credentials",
        has_admin_username=bool(admin_username),
        has_admin_password=bool(admin_password),
        input_username_present=bool(credentials.username),
    )

    if not admin_username or not admin_password:
        logger.error("Admin credentials not configured")
        raise HTTPException(
            status_code=500, detail="Сервер не налаштований для авторизації"
        )

    # Перевірка пароля: підтримка bcrypt-хешу або plain у development
    login_successful = False
    if credentials.username.lower() == admin_username.lower():
        auth_mgr = get_auth_manager()
        # Визначаємо чи ADMIN_PASSWORD є bcrypt-хешем
        is_bcrypt_hash = isinstance(admin_password, str) and admin_password.startswith(
            "$2"
        )
        environment = os.getenv("ENVIRONMENT", "development").lower()
        logger.debug(
            "Password verification path decision",
            is_bcrypt_hash=is_bcrypt_hash,
            environment=environment,
        )

        if is_bcrypt_hash:
            # Безпечна перевірка через bcrypt
            logger.debug("Using bcrypt verification method")
            login_successful = auth_mgr.verify_password(
                credentials.password, admin_password
            )
            logger.debug(
                "Password verification result",
                method="bcrypt",
                success=bool(login_successful),
            )
        else:
            # У продакшені вимагаємо хешований пароль
            if environment == "production":
                logger.warning(
                    "Plain ADMIN_PASSWORD detected in production - login blocked"
                )
                login_successful = False
            else:
                # Dev режим: дозволяємо просте порівняння без логування секретів
                logger.debug("Using plain-text comparison (dev only)")
                login_successful = credentials.password == admin_password

    # Записуємо спробу входу
    auth_mgr.record_login_attempt(credentials.username, client_ip, login_successful)

    if login_successful:
        # Отримуємо роль та дозволи
        role, permissions = get_user_role_and_permissions("admin")

        # Побудова fingerprint (IP + UA hash)
        user_agent = request.headers.get("User-Agent", "")
        fingerprint = hashlib.sha256(
            f"{client_ip}|{user_agent}".encode("utf-8")
        ).hexdigest()

        user_data = {
            "id": "admin",
            "username": credentials.username,
            "role": role,
            "permissions": permissions,
            "fingerprint": fingerprint,
        }

        # Створюємо токени
        token_pair = await auth_mgr.create_token_pair(user_data)

        logger.info(
            "Login successful",
            username_present=True,
            ip=client_ip,
            server_boot_id=SERVER_BOOT_ID[:8] + "...",
        )

        # Виставляємо httpOnly cookie з refresh токеном і CSRF cookie для double-submit
        # Secure cookie виставляємо лише коли схема запиту HTTPS або за X-Forwarded-Proto=https
        # Це уникає ситуації, коли в non-TLS середовищах (локальні/тести) cookie не відправляється
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        request_scheme = (request.url.scheme or "").lower()
        secure_cookie = forwarded_proto == "https" or request_scheme == "https"
        csrf_token = uuid.uuid4().hex

        response = JSONResponse(
            {
                "success": True,
                "message": "Авторизація успішна",
                "user": user_data,
                # Повертаємо тільки access токен у тілі відповіді
                "tokens": {
                    "access_token": token_pair.access_token,
                    "token_type": "bearer",
                    "expires_in": token_pair.expires_in,
                },
            }
        )

        # Refresh токен у httpOnly cookie
        response.set_cookie(
            key="rt",
            value=token_pair.refresh_token,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            path="/",  # Доступний для всього сайту
        )

        # CSRF токен у доступній cookie (не httpOnly)
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,
            secure=secure_cookie,
            samesite="lax",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            path="/",  # Доступний для всього сайту
        )

        return response
    logger.warning(
        "Login failed - invalid credentials",
        username_present=bool(credentials.username),
        ip=client_ip,
    )
    # Застосувати lockout якщо перевищено ліміт
    await auth_mgr.apply_lockout_if_needed(credentials.username, client_ip)
    raise HTTPException(status_code=401, detail="Невірний логін або пароль")


@auth_router.post("/validate")
async def validate_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    """Валідація JWT токена"""

    # Діагностичний лог лише за прапорцем, щоб уникати шуму
    if os.getenv("LOG_AUTH_EVENTS", "false").lower() in ("1", "true", "yes"):
        logger.info("🔍 Token validation started", has_credentials=bool(credentials))

    try:
        logger.debug("📋 Credentials received")

        user_data = await get_current_user(credentials)

        if os.getenv("LOG_AUTH_EVENTS", "false").lower() in ("1", "true", "yes"):
            logger.info("✅ Token validated successfully")

        return {"valid": True, "user": user_data}

    except HTTPException as he:
        # Не логуємо на error рівні для очікуваних помилок автентифікації
        if he.status_code == 401:
            logger.debug(
                "🔒 Authentication failed (expected for invalid tokens)",
                status_code=he.status_code,
                detail=he.detail,
            )
        else:
            logger.error(
                "❌ HTTP Exception during token validation",
                status_code=he.status_code,
                detail=he.detail,
            )
        raise
    except Exception as e:
        logger.error(
            "❌ Unexpected error during token validation",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise HTTPException(
            status_code=500, detail=f"Token validation failed: {str(e)}"
        ) from e


@auth_router.post("/refresh")
@rate_limit(requests_per_minute=30)
async def refresh_token(request: Request):
    """Оновлення access токена за допомогою refresh токена з httpOnly cookie та CSRF перевіркою"""

    # Double-submit CSRF: порівняння заголовка і cookie
    csrf_header = request.headers.get("X-CSRF-Token")
    csrf_cookie = request.cookies.get("csrf_token")
    if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
        raise HTTPException(status_code=403, detail="CSRF validation failed")

    refresh_cookie = request.cookies.get("rt")
    if not refresh_cookie:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        token_pair = await get_auth_manager().refresh_access_token(refresh_cookie)

        # Ротація refresh токена може відбутися всередині.
        # Оновимо cookie, якщо token_pair.refresh_token змінився
        secure_cookie = os.getenv("ENVIRONMENT", "development").lower() == "production"
        response = JSONResponse(
            {
                "success": True,
                "tokens": {
                    "access_token": token_pair.access_token,
                    "token_type": "bearer",
                    "expires_in": token_pair.expires_in,
                },
            }
        )
        # Якщо refresh токен повернувся (можлива ротація) — оновити cookie
        if token_pair.refresh_token:
            response.set_cookie(
                key="rt",
                value=token_pair.refresh_token,
                httponly=True,
                secure=secure_cookie,
                samesite="lax",
                max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
                path="/api/auth",
            )
        return response

    except HTTPException as he:
        logger.info(
            "❌ Token refresh failed", status_code=he.status_code, detail=he.detail
        )
        raise
    except Exception as e:
        logger.error("❌ Token refresh error", error=str(e))
        raise HTTPException(status_code=401, detail="Could not refresh token") from e


@auth_router.post("/logout")
async def logout(
    user: Dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    """Вихід з системи"""

    try:
        auth_mgr = get_auth_manager()

        # Відкликаємо токен (синхронний виклик, виконує асинхронну частину у фоні за потреби)
        auth_mgr.revoke_token(credentials.credentials)

        # Видаляємо поточну сесію. Якщо Redis-клієнт асинхронний і цикл подій вже запущений,
        # метод поверне asyncio.Task — дочекаємось його завершення без падіння, інакше ігноруємо
        logout_result = auth_mgr.logout(user["session_id"])
        try:
            import asyncio

            if isinstance(logout_result, asyncio.Task):
                await logout_result
        except Exception:
            pass

        # Додатково очищаємо всі можливі сесії користувача
        if auth_mgr.redis_client:
            # Видаляємо всі сесії користувача через індекс user_sessions:{user_id}
            try:
                index_key = f"user_sessions:{user['user_id']}"
                members_res = auth_mgr.redis_client.smembers(index_key)
                members = (
                    await members_res if inspect.isawaitable(members_res) else members_res
                )
                if members:
                    for sid_bytes in members:
                        try:
                            sid = (
                                sid_bytes.decode("utf-8")
                                if isinstance(sid_bytes, (bytes, bytearray))
                                else str(sid_bytes)
                            )
                            del_res = auth_mgr.redis_client.delete(f"session:{sid}")
                            if inspect.isawaitable(del_res):
                                await del_res
                            logger.info(
                                "Deleted user session",
                                key=f"session:{sid}",
                                user_id=user["user_id"],
                            )
                        except Exception as e:
                            logger.error(
                                "Error deleting session via index",
                                key=f"session:{sid}",
                                error=str(e),
                            )
                    # Очищаємо індекс
                    del_index_res = auth_mgr.redis_client.delete(index_key)
                    if inspect.isawaitable(del_index_res):
                        await del_index_res
            except Exception as e:
                logger.error("Error deleting user sessions index", error=str(e))

        # Маскуємо session_id у логах
        sid = user.get("session_id", "")
        sid_masked = (sid[:8] + "...") if isinstance(sid, str) and len(sid) > 8 else sid
        logger.info(
            "User logged out", user_id=user.get("user_id"), session_id=sid_masked
        )

        # Очищуємо refresh та csrf cookie
        response = JSONResponse({"success": True, "message": "Logged out successfully"})
        # Очищаємо cookie на кореневому шляху, щоб гарантовано видалити їх для всіх маршрутів
        response.set_cookie("rt", "", max_age=0, path="/")
        response.set_cookie("csrf_token", "", max_age=0, path="/")
        return response

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Logout error", error=str(e))
        return {"success": True, "message": "Logged out"}  # Завжди успішно


@auth_router.get("/sessions")
@require_permission("auth.manage")
async def get_active_sessions(_user: Dict = Depends(get_current_user)):
    """Отримання списку активних сесій (тільки для адмінів)"""

    try:
        sessions = await get_auth_manager().get_active_sessions()

        sessions_info = []
        for session in sessions:
            sessions_info.append(
                {
                    "sessionId": session["session_id"][:8]
                    + "...",  # Обрізаємо для безпеки
                    "username": session["username"],
                    "role": session["role"],
                    "createdAt": session.get("created_at", "N/A"),
                    "lastActivity": session.get("last_activity", "N/A"),
                }
            )

        return {"total": len(sessions), "sessions": sessions_info}
    except (
        redis.exceptions.RedisError,
        ValueError,
        TypeError,
        KeyError,
    ) as e:
        logger.error("Error getting sessions", error=str(e))
        return {"total": 0, "sessions": []}


@auth_router.get("/me")
async def get_current_user_info(user: Dict = Depends(get_current_user)):
    """Отримання інформації про поточного користувача"""

    return {
        "user": {
            "id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "permissions": user["permissions"],
        }
    }


@auth_router.get("/permissions")
async def get_permissions(user: Dict = Depends(get_current_user)):
    """Отримання списку дозволів поточного користувача"""

    return {"permissions": user["permissions"]}


@auth_router.get("/debug")
@require_role("admin")
async def debug_auth(_user: Dict = Depends(get_current_user)):
    """Debug endpoint для перевірки авторизації (тільки в development)"""
    if os.getenv("ENVIRONMENT", "development") != "development":
        raise HTTPException(status_code=404, detail="Not found")

    secrets_mgr = get_secrets_manager()
    admin_username = secrets_mgr.get_secret("ADMIN_USERNAME")
    admin_password = secrets_mgr.get_secret("ADMIN_PASSWORD")

    # Повертаємо тільки не-чутливу діагностику
    return {
        "secrets_manager": {
            "admin_username_present": bool(admin_username),
            "admin_password_configured": bool(admin_password),
            "admin_password_length": len(admin_password) if admin_password else 0,
        },
        "environment": {"environment": os.getenv("ENVIRONMENT", "development")},
    }


# Health check endpoint
@auth_router.get("/health")
async def auth_health():
    """Перевірка стану сервісу автентифікації"""

    return {
        "status": "ok",
        "service": "authentication",
        "timestamp": datetime.utcnow().isoformat(),
    }
