"""
Authentication endpoints for TetraCore Hub
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import structlog

# Імпорт нового менеджера автентифікації
from core.auth_manager import (
    get_auth_manager, get_current_user, UserCredentials,
    TokenPair, require_permission, require_role
)
from core.secrets_manager import get_secrets_manager

# Модель для валідації сесії
class SessionValidation(BaseModel):
    sessionId: str

# Модель для виходу
class LogoutRequest(BaseModel):
    sessionId: str

# Модель для входу з логіном та паролем
class LoginRequest(BaseModel):
    username: str
    password: str

# Модель для refresh токена
class RefreshTokenRequest(BaseModel):
    refresh_token: str

# Модель користувача
class User(BaseModel):
    id: str
    username: str
    role: str = "viewer"
    permissions: List[str] = Field(default_factory=list)
    sessionId: str
    loginTime: datetime
    lastActivity: datetime

logger = structlog.get_logger()

# Імпорт конфігурації авторизації
from config import (
    get_settings,
    get_user_role, get_user_permissions
)

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
    """Отримання IP адреси клієнта"""
    # Перевіряємо заголовки для проксі
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback на client.host
    return request.client.host if request.client else "127.0.0.1"

# Router для auth ендпоінтів
auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])

@auth_router.post("/login")
async def login(request: Request, credentials: LoginRequest):
    """Авторизація користувача з JWT токенами"""

    client_ip = get_client_ip(request)

    # Перевірка rate limiting
    auth_mgr = get_auth_manager()
    if not auth_mgr.check_login_attempts(credentials.username, client_ip):
        logger.warning("Too many login attempts", username=credentials.username, ip=client_ip)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later."
        )

    # Логування для діагностики
    logger.info("Login attempt", username=credentials.username, ip=client_ip)

    # Отримання credentials через secrets manager
    secrets_mgr = get_secrets_manager()
    admin_username = secrets_mgr.get_secret("ADMIN_USERNAME")
    admin_password = secrets_mgr.get_secret("ADMIN_PASSWORD")

    # Логування для діагностики
    logger.info("Checking credentials",
               stored_username=admin_username,
               stored_password_length=len(admin_password) if admin_password else 0,
               input_username=credentials.username,
               input_password_length=len(credentials.password))

    if not admin_username or not admin_password:
        logger.error("Admin credentials not configured")
        raise HTTPException(status_code=500, detail="Сервер не налаштований для авторизації")

    # Тимчасова перевірка (потім буде замінено на БД)
    login_successful = False
    if credentials.username.lower() == admin_username.lower():
        # Для демо використовуємо просту перевірку
        # В продакшені має бути: auth_manager.verify_password(credentials.password, stored_hash)
        logger.info("Username match found, checking password",
                   expected_password=admin_password,
                   received_password=credentials.password)
        if credentials.password == admin_password:
            login_successful = True

    # Записуємо спробу входу
    auth_mgr.record_login_attempt(credentials.username, client_ip, login_successful)

    if login_successful:
        # Отримуємо роль та дозволи
        role, permissions = get_user_role_and_permissions("admin")

        user_data = {
            "id": "admin",
            "username": credentials.username,
            "role": role,
            "permissions": permissions
        }

        # Створюємо токени
        token_pair = await auth_mgr.create_token_pair(user_data)

        logger.info("Login successful", username=credentials.username, ip=client_ip)

        return {
            "success": True,
            "message": "Авторизація успішна",
            "user": user_data,
            "tokens": token_pair.dict()
        }
    else:
        logger.warning("Login failed - invalid credentials", username=credentials.username, ip=client_ip)
        raise HTTPException(status_code=401, detail="Невірний логін або пароль")

@auth_router.post("/validate")
async def validate_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Валідація JWT токена"""

    logger.info("🔍 Token validation started",
                has_credentials=bool(credentials),
                token_preview=credentials.credentials[:20] + "..." if credentials and len(credentials.credentials) > 20 else "no_token")

    try:
        token = credentials.credentials
        logger.info("📋 Extracting token from credentials",
                    token_length=len(token) if token else 0)

        user_data = await get_current_user(credentials)

        logger.info("✅ Token validated successfully",
                    user_id=user_data["user_id"],
                    username=user_data["username"],
                    role=user_data["role"])

        return {
            "valid": True,
            "user": user_data
        }

    except HTTPException as he:
        logger.error("❌ HTTP Exception during token validation",
                     status_code=he.status_code,
                     detail=he.detail)
        raise
    except Exception as e:
        logger.error("❌ Unexpected error during token validation",
                     error=str(e),
                     error_type=type(e).__name__,
                     token_preview=credentials.credentials[:20] + "..." if credentials and len(credentials.credentials) > 20 else "no_token")
        raise HTTPException(status_code=500, detail=f"Token validation failed: {str(e)}")

@auth_router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest):
    """Оновлення access токена за допомогою refresh токена"""

    try:
        token_pair = await get_auth_manager().refresh_access_token(request.refresh_token)

        return {
            "success": True,
            "tokens": token_pair.dict()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token refresh error", error=str(e))
        raise HTTPException(status_code=401, detail="Could not refresh token")

@auth_router.post("/logout")
async def logout(
    user: Dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Security(security)
):
    """Вихід з системи"""

    try:
        auth_mgr = get_auth_manager()

        # Відкликаємо токен
        auth_mgr.revoke_token(credentials.credentials)

        # Видаляємо поточну сесію
        auth_mgr.logout(user["session_id"])

        # Додатково очищаємо всі можливі сесії користувача
        if auth_mgr.redis_client:
            # Шукаємо всі сесії користувача
            pattern = f"session:*"
            for key in auth_mgr.redis_client.scan_iter(match=pattern):
                try:
                    session_data = auth_mgr.redis_client.get(key)
                    if session_data:
                        session = json.loads(session_data)
                        if session.get("user_id") == user["user_id"]:
                            auth_mgr.redis_client.delete(key)
                            logger.info("Deleted user session", key=key, user_id=user["user_id"])
                except Exception as e:
                    logger.error("Error deleting session", key=key, error=str(e))

        logger.info("User logged out",
                   user_id=user["user_id"],
                   session_id=user["session_id"])

        return {"success": True, "message": "Logged out successfully"}

    except Exception as e:
        logger.error("Logout error", error=str(e))
        return {"success": True, "message": "Logged out"}  # Завжди успішно

@auth_router.get("/sessions")
@require_permission("auth.manage")
async def get_active_sessions(user: Dict = Depends(get_current_user)):
    """Отримання списку активних сесій (тільки для адмінів)"""

    try:
        sessions = get_auth_manager().get_active_sessions()

        sessions_info = []
        for session in sessions:
            sessions_info.append({
                "sessionId": session["session_id"][:8] + "...",  # Обрізаємо для безпеки
                "username": session["username"],
                "role": session["role"],
                "createdAt": session.get("created_at", "N/A"),
                "lastActivity": session.get("last_activity", "N/A")
            })

        return {
            "total": len(sessions),
            "sessions": sessions_info
        }
    except Exception as e:
        logger.error("Error getting sessions", error=str(e))
        return {
            "total": 0,
            "sessions": []
        }

@auth_router.get("/me")
async def get_current_user_info(user: Dict = Depends(get_current_user)):
    """Отримання інформації про поточного користувача"""

    return {
        "user": {
            "id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "permissions": user["permissions"]
        }
    }

@auth_router.get("/permissions")
async def get_permissions(user: Dict = Depends(get_current_user)):
    """Отримання списку дозволів поточного користувача"""

    return {
        "permissions": user["permissions"]
    }

@auth_router.get("/debug")
async def debug_auth():
    """Debug endpoint для перевірки авторизації (тільки в development)"""
    import os
    if os.getenv("ENVIRONMENT", "development") != "development":
        raise HTTPException(status_code=404, detail="Not found")

    secrets_mgr = get_secrets_manager()
    admin_username = secrets_mgr.get_secret("ADMIN_USERNAME")
    admin_password = secrets_mgr.get_secret("ADMIN_PASSWORD")

    from config import settings

    return {
        "secrets_manager": {
            "admin_username": admin_username,
            "admin_password": admin_password,
            "admin_password_length": len(admin_password) if admin_password else 0
        },
        "config_settings": {
            "admin_username": settings.admin_username,
            "admin_password": settings.admin_password,
            "admin_password_length": len(settings.admin_password) if settings.admin_password else 0
        },
        "environment": {
            "ADMIN_USERNAME": os.getenv("ADMIN_USERNAME"),
            "ADMIN_PASSWORD": os.getenv("ADMIN_PASSWORD"),
            "ENVIRONMENT": os.getenv("ENVIRONMENT", "development")
        }
    }

# Health check endpoint
@auth_router.get("/health")
async def auth_health():
    """Перевірка стану сервісу автентифікації"""

    return {
        "status": "ok",
        "service": "authentication",
        "timestamp": datetime.utcnow().isoformat()
    }
