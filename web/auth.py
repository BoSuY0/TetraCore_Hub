"""
Authentication endpoints for TetraCore Hub
"""

import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import structlog

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

# Модель користувача
class User(BaseModel):
    id: str
    username: str
    firstName: str
    lastName: Optional[str] = None
    photoUrl: Optional[str] = None
    role: str = "viewer"
    permissions: List[str] = Field(default_factory=list)
    sessionId: str
    loginTime: datetime
    lastActivity: datetime

# Зберігання сесій в пам'яті (для продакшн потрібна база даних)
active_sessions: Dict[str, Dict] = {}
user_permissions: Dict[str, Dict[str, any]] = {}

logger = structlog.get_logger()

# Імпорт конфігурації авторизації
from auth_config import (
    SESSION_DURATION_HOURS,
    get_user_role, get_user_permissions,
    ADMIN_USERNAME, ADMIN_PASSWORD, ROLE_PERMISSIONS
)


def get_user_role_and_permissions(user_id: int) -> tuple[str, List[str]]:
    """Визначення ролі та дозволів користувача"""
    role = get_user_role(user_id)
    permissions = get_user_permissions(user_id)
    return role, permissions

def create_session(user_data: Dict) -> Dict:
    """Створення нової сесії користувача"""
    
    session_id = str(uuid.uuid4())
    current_time = datetime.utcnow()
    expires_at = current_time + timedelta(days=1)
    
    # Додаємо sessionId та loginTime до user об'єкта для фронтенду
    user_data_with_session = user_data.copy()
    user_data_with_session["sessionId"] = session_id
    user_data_with_session["loginTime"] = current_time.isoformat()
    
    session = {
        "sessionId": session_id,
        "user": user_data_with_session,
        "createdAt": current_time.isoformat(),
        "expiresAt": expires_at.isoformat(),
        "ipAddress": "127.0.0.1"  # Заглушка для IP
    }
    
    # Збереження сесії в пам'яті (замінити на Redis або БД в продакшн)
    active_sessions[session_id] = session
    
    logger.info("Session created", session_id=session_id, username=user_data.get("username"), expires_at=expires_at.isoformat())
    logger.info("Total active sessions after creation", count=len(active_sessions))
    
    return session

def get_user_from_session(session_id: str) -> Optional[Dict]:
    """Отримання користувача за ID сесії"""
    return active_sessions.get(session_id)

def cleanup_expired_sessions():
    """Очищення застарілих сесій"""
    current_time = datetime.utcnow()
    expired_sessions = []
    
    for session_id, session in active_sessions.items():
        # Сесія застаріла якщо current_time більше ніж expiresAt
        expires_at = datetime.fromisoformat(session["expiresAt"])
        if current_time > expires_at:
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        del active_sessions[session_id]
        logger.info("Expired session removed", session_id=session_id)

# Router для auth ендпоінтів
auth_router = APIRouter(prefix="/api/auth", tags=["authentication"])

@auth_router.post("/login")
async def login(request: LoginRequest):
    """Авторизація користувача"""
    
    # Логування для діагностики
    logger.info("Login attempt", username=request.username)
    
    # Перевірка чи встановлені credentials
    if ADMIN_USERNAME is None or ADMIN_PASSWORD is None:
        logger.error("Admin credentials not configured", 
                    admin_username_set=ADMIN_USERNAME is not None,
                    admin_password_set=ADMIN_PASSWORD is not None)
        raise HTTPException(status_code=500, detail="Сервер не налаштований для авторизації")
    
    if request.username == ADMIN_USERNAME and request.password == ADMIN_PASSWORD:
        user_data = {
            "id": "admin",
            "username": request.username,
            "firstName": request.username,  # Використовуємо username як firstName
            "lastName": None,
            "photoUrl": None,
            "role": "admin",
            "permissions": ROLE_PERMISSIONS["admin"]
        }
        session = create_session(user_data)
        logger.info("Login successful", username=request.username, session_id=session["sessionId"])
        return {
            "success": True,
            "message": "Авторизація успішна",
            "session": session
        }
    else:
        logger.warning("Login failed - invalid credentials", username=request.username)
        raise HTTPException(status_code=401, detail="Невірний логін або пароль")

@auth_router.post("/validate")
async def validate_session(validation: SessionValidation):
    """Валідація сесії користувача"""
    
    logger.info("Session validation request", session_id=validation.sessionId)
    logger.info("Active sessions count", count=len(active_sessions))
    
    # Очищення застарілих сесій перед перевіркою
    cleanup_expired_sessions()
    
    try:
        session = get_user_from_session(validation.sessionId)
        
        if not session:
            logger.warning("Session not found", session_id=validation.sessionId, active_sessions=list(active_sessions.keys()))
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Оновлення часу останньої активності
        session["expiresAt"] = (datetime.utcnow() + timedelta(days=1)).isoformat()
        active_sessions[validation.sessionId] = session
        
        return {
            "valid": True,
            "user": session["user"],
            "expiresAt": session["expiresAt"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Session validation error", error=str(e))
        raise HTTPException(status_code=500, detail="Session validation failed")

@auth_router.post("/logout")
async def logout(logout_request: LogoutRequest):
    """Вихід з системи"""
    
    try:
        if logout_request.sessionId in active_sessions:
            del active_sessions[logout_request.sessionId]
            
            logger.info("User logged out", 
                       session_id=logout_request.sessionId)
        
        return {"success": True, "message": "Logged out successfully"}
        
    except Exception as e:
        logger.error("Logout error", error=str(e))
        return {"success": True, "message": "Logged out"}  # Завжди успішно

@auth_router.get("/sessions")
async def get_active_sessions():
    """Отримання списку активних сесій (тільки для адмінів)"""
    
    # Тут потрібно додати перевірку прав адміністратора
    # Для простоти поки що повертаємо базову інформацію
    
    cleanup_expired_sessions()
    
    sessions_info = []
    for session_id, session in active_sessions.items():
        sessions_info.append({
            "sessionId": session_id[:8] + "...",  # Обрізаємо для безпеки
            "username": session["user"]["username"],
            "role": session["user"]["role"],
            "createdAt": session["createdAt"],
            "expiresAt": session["expiresAt"]
        })
    
    return {
        "total": len(active_sessions),
        "sessions": sessions_info
    }

@auth_router.get("/user-info/{session_id}")
async def get_user_info(session_id: str):
    """Отримання інформації про користувача за сесією"""
    
    session = get_user_from_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "user": session["user"],
        "expiresAt": session["expiresAt"]
    }

# Middleware для автоматичного оновлення активності
async def update_user_activity(session_id: str):
    """Оновлення часу останньої активності користувача"""
    if session_id in active_sessions:
        active_sessions[session_id]["expiresAt"] = (datetime.utcnow() + timedelta(days=1)).isoformat()