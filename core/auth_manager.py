"""
Authentication Manager for TetraCore Hub
Безпечне управління автентифікацією з JWT токенами
"""

import os
import secrets
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List, Any
from functools import wraps
import hashlib
import hmac

import jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Security, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import structlog
import redis
from pydantic import BaseModel, Field, validator
from core.async_optimization import AsyncOptimizer

from core.secrets_manager import get_secrets_manager

logger = structlog.get_logger()

# Константи безпеки
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
SESSION_CLEANUP_INTERVAL = 3600  # 1 година

# Конфігурація для паролів
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()


class TokenPair(BaseModel):
    """Пара токенів для автентифікації"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(default=ACCESS_TOKEN_EXPIRE_MINUTES * 60)


class UserCredentials(BaseModel):
    """Модель для облікових даних користувача"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)

    @validator('username')
    def validate_username(cls, v):
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('Username може містити тільки літери, цифри, _ та -')
        return v.lower()


class TokenData(BaseModel):
    """Дані, що зберігаються в токені"""
    user_id: str
    username: str
    role: str
    permissions: List[str]
    session_id: str
    exp: datetime
    iat: datetime
    token_type: str = "access"


class AuthManager:
    """Менеджер автентифікації з підтримкою JWT токенів"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        logger.info("🔧 Initializing AuthManager", has_redis=bool(redis_client))

        self.redis_client = redis_client
        self.async_optimizer = AsyncOptimizer(max_workers=5)

        # Отримуємо ключі через secrets_manager
        logger.info("🔐 Loading secrets from secrets_manager")
        secrets_mgr = get_secrets_manager()
        try:
            self.secret_key = secrets_mgr.get_jwt_key()
            logger.info("✅ JWT secret key loaded successfully", key_length=len(self.secret_key))
        except ValueError as e:
            # Генеруємо випадковий ключ якщо не задано
            self.secret_key = secrets.token_urlsafe(32)
            logger.warning("⚠️ JWT_SECRET_KEY не встановлено. Використовується тимчасовий ключ.", error=str(e))
            # Зберігаємо згенерований ключ
            secrets_mgr.set_secret("JWT_SECRET_KEY", self.secret_key)

        try:
            self.refresh_secret = secrets_mgr.get_refresh_key()
            logger.info("✅ JWT refresh secret loaded successfully", key_length=len(self.refresh_secret))
        except ValueError as e:
            self.refresh_secret = secrets.token_urlsafe(32)
            logger.warning("⚠️ JWT_REFRESH_SECRET не встановлено. Використовується тимчасовий ключ.", error=str(e))
            secrets_mgr.set_secret("JWT_REFRESH_SECRET", self.refresh_secret)

        # Кеш для заблокованих токенів
        self._blocked_tokens = set()

        # Кеш для спроб входу
        self._login_attempts = {}

        logger.info("✅ AuthManager initialized successfully")

        # Логування стану Redis
        if self.redis_client:
            try:
                self.redis_client.ping()
                logger.info("Redis connection established successfully")
            except Exception as e:
                logger.warning("Redis connection failed, JWT validation will work without session storage", error=str(e))
                self.redis_client = None
        else:
            logger.info("AuthManager initialized without Redis, sessions will not be stored")

    def hash_password(self, password: str) -> str:
        """Хешування пароля з використанням bcrypt"""
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Перевірка пароля"""
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception as e:
            logger.error("Password verification error", error=str(e))
            return False

    def generate_session_id(self) -> str:
        """Генерація унікального ID сесії"""
        return secrets.token_urlsafe(32)

    def create_access_token(self, data: Dict, expires_delta: Optional[timedelta] = None) -> str:
        """Створення access токена"""
        to_encode = data.copy()

        # Якщо session_id вже є (наприклад при refresh), зберігаємо його
        if "session_id" not in to_encode:
            to_encode["session_id"] = self.generate_session_id()

        # Додаємо стандартні claims
        now = datetime.now(timezone.utc)
        expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

        to_encode.update({
            "exp": expire,
            "iat": now,
            "nbf": now,  # Not before
            "jti": secrets.token_urlsafe(16),  # JWT ID для унікальності
            "token_type": "access"
        })

        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=ALGORITHM)
        return encoded_jwt

    def create_refresh_token(self, data: Dict) -> str:
        """Створення JWT refresh токена"""
        to_encode = data.copy()

        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        to_encode.update({
            "exp": expire,
            "iat": now,
            "token_type": "refresh",
            "jti": secrets.token_urlsafe(16)
        })

        encoded_jwt = jwt.encode(to_encode, self.refresh_secret, algorithm=ALGORITHM)
        return encoded_jwt

    async def create_token_pair(self, user_data: Dict) -> TokenPair:
        """Створення пари токенів (access + refresh)"""
        session_id = self.generate_session_id()

        token_data = {
            "user_id": user_data["id"],
            "username": user_data["username"],
            "role": user_data["role"],
            "permissions": user_data.get("permissions", []),
            "session_id": session_id
        }

        access_token = self.create_access_token(token_data)
        refresh_token = self.create_refresh_token(token_data)

        # Зберігаємо сесію в Redis якщо доступний
        if self.redis_client:
            session_key = f"session:{session_id}"
            session_data = {
                **user_data,
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_activity": datetime.now(timezone.utc).isoformat()
            }
            session_data_json = await self.async_optimizer.json_dumps(session_data)
            self.redis_client.setex(
                session_key,
                timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
                session_data_json
            )

        logger.info("Token pair created", user_id=user_data["id"], session_id=session_id)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token
        )

    async def decode_token(self, token: str, token_type: str = "access") -> Dict:
        """Декодування та валідація JWT токена"""
        logger.info("🔓 decode_token called",
                    token_type=token_type,
                    token_preview=token[:20] + "..." if len(token) > 20 else token,
                    has_secret_key=bool(self.secret_key),
                    secret_key_length=len(self.secret_key) if self.secret_key else 0)

        try:
            secret = self.secret_key if token_type == "access" else self.refresh_secret
            logger.info("📋 Using secret for decoding",
                        secret_type=token_type,
                        secret_length=len(secret) if secret else 0)

            payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
            logger.info("✅ JWT decoded successfully",
                        payload_keys=list(payload.keys()),
                        token_type_in_payload=payload.get("token_type"),
                        user_id=payload.get("user_id"))

            # Перевірка типу токена
            if payload.get("token_type") != token_type:
                logger.warning("❌ Invalid token type", expected=token_type, received=payload.get("token_type"))
                raise jwt.InvalidTokenError(f"Invalid token type. Expected {token_type}")

            # Перевірка чи токен не заблокований
            jti = payload.get("jti")
            if jti and jti in self._blocked_tokens:
                logger.warning("❌ Token is revoked", jti=jti)
                raise jwt.InvalidTokenError("Token has been revoked")

            # Перевірка в Redis якщо доступний
            if jti and self.redis_client:
                blocked_key = f"blocked_token:{jti}"
                if self.redis_client.exists(blocked_key):
                    logger.warning("❌ Token is revoked in Redis", jti=jti)
                    raise jwt.InvalidTokenError("Token has been revoked")

            # Перевірка сесії в Redis (опціонально)
            if self.redis_client and "session_id" in payload:
                session_key = f"session:{payload['session_id']}"
                try:
                    if not self.redis_client.exists(session_key):
                        logger.warning("⚠️ Session not found in Redis", session_id=payload['session_id'])
                        # Не викидаємо помилку, просто логуємо - JWT може працювати без Redis
                        logger.info("ℹ️ Continuing validation without Redis session check")
                    else:
                        # Оновлюємо час останньої активності якщо сесія існує
                        await self.update_session_activity(payload['session_id'])
                        logger.info("✅ Redis session updated")
                except Exception as redis_error:
                    logger.warning("⚠️ Redis operation failed during token validation", error=str(redis_error))
                    # Продовжуємо без Redis

            logger.info("✅ Token validation successful", user_id=payload.get("user_id"))
            return payload

        except jwt.ExpiredSignatureError as e:
            logger.warning("❌ Token has expired",
                           token_preview=token[:20] + "..." if len(token) > 20 else token,
                           error=str(e))
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError as e:
            logger.warning("❌ Invalid token",
                           error=str(e),
                           token_preview=token[:20] + "..." if len(token) > 20 else token)
            raise HTTPException(status_code=401, detail="Invalid token")
        except Exception as e:
            logger.error("❌ Token decode error",
                         error=str(e),
                         error_type=type(e).__name__,
                         token_preview=token[:20] + "..." if len(token) > 20 else token)
            raise HTTPException(status_code=401, detail="Could not validate credentials")

    async def refresh_access_token(self, refresh_token: str) -> TokenPair:
        """Оновлення access токена за допомогою refresh токена"""
        payload = await self.decode_token(refresh_token, token_type="refresh")

        # Перевіряємо чи сесія ще активна
        session_id = payload.get("session_id")
        if session_id and self.redis_client:
            session_key = f"session:{session_id}"
            if not self.redis_client.exists(session_key):
                logger.warning("Session not found during refresh", session_id=session_id[:8] + "...")
                raise HTTPException(status_code=401, detail="Session expired")

        # Створюємо новий access токен з тими ж даними
        token_data = {
            "user_id": payload["user_id"],
            "username": payload["username"],
            "role": payload["role"],
            "permissions": payload["permissions"],
            "session_id": session_id  # Зберігаємо існуючий session_id
        }

        new_access_token = self.create_access_token(token_data)

        logger.info("Access token refreshed", user_id=payload["user_id"])

        return TokenPair(
            access_token=new_access_token,
            refresh_token=refresh_token  # Refresh токен залишається той самий
        )

    def revoke_token(self, token: str):
        """Відкликання токена (додавання в чорний список)"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[ALGORITHM])
            jti = payload.get("jti")
            if jti:
                self._blocked_tokens.add(jti)

                # Зберігаємо в Redis з TTL = час життя токена
                if self.redis_client:
                    exp = payload.get("exp", 0)
                    ttl = max(0, exp - datetime.now(timezone.utc).timestamp())
                    if ttl > 0:
                        self.redis_client.setex(f"blocked_token:{jti}", int(ttl), "1")

                logger.info("Token revoked", jti=jti)
        except Exception as e:
            logger.error("Error revoking token", error=str(e))

    def logout(self, session_id: str):
        """Вихід користувача (видалення сесії)"""
        if self.redis_client:
            session_key = f"session:{session_id}"
            self.redis_client.delete(session_key)

        logger.info("User logged out", session_id=session_id)

    def check_login_attempts(self, username: str, ip_address: str) -> bool:
        """Перевірка кількості спроб входу"""
        # Normalize inputs to prevent bypass
        username = self._normalize_username(username)
        ip_address = self._normalize_ip_address(ip_address)

        key = f"{username}:{ip_address}"
        now = datetime.now(timezone.utc)

        # Очищення старих спроб
        if key in self._login_attempts:
            self._login_attempts[key] = [
                attempt for attempt in self._login_attempts[key]
                if now - attempt < timedelta(minutes=LOGIN_ATTEMPT_WINDOW_MINUTES)
            ]

        attempts = self._login_attempts.get(key, [])
        return len(attempts) < MAX_LOGIN_ATTEMPTS

    def record_login_attempt(self, username: str, ip_address: str, success: bool):
        """Запис спроби входу"""
        # Normalize inputs
        username = self._normalize_username(username)
        ip_address = self._normalize_ip_address(ip_address)

        if success:
            # Очищаємо спроби при успішному вході
            key = f"{username}:{ip_address}"
            if key in self._login_attempts:
                del self._login_attempts[key]
        else:
            key = f"{username}:{ip_address}"
            if key not in self._login_attempts:
                self._login_attempts[key] = []
            self._login_attempts[key].append(datetime.now(timezone.utc))

    def _normalize_username(self, username: str) -> str:
        """Normalize username to prevent bypass attempts"""
        if not username:
            return ""
        # Convert to lowercase and strip whitespace
        return username.lower().strip()

    def _normalize_ip_address(self, ip_address: str) -> str:
        """Normalize IP address to prevent bypass attempts"""
        if not ip_address:
            return ""

        try:
            # Parse IP address to normalize format
            import ipaddress
            ip_obj = ipaddress.ip_address(ip_address.strip())
            return str(ip_obj)
        except ValueError:
            # If invalid IP, return as-is but stripped
            return ip_address.strip()

    async def update_session_activity(self, session_id: str):
        """Оновлення часу останньої активності сесії"""
        if self.redis_client:
            session_key = f"session:{session_id}"
            session_data = self.redis_client.get(session_key)
            if session_data:
                data = await self.async_optimizer.json_loads(session_data)
                data["last_activity"] = datetime.now(timezone.utc).isoformat()
                data_json = await self.async_optimizer.json_dumps(data)
                self.redis_client.setex(
                    session_key,
                    timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
                    data_json
                )

    async def get_active_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Отримання активних сесій"""
        sessions = []

        if self.redis_client:
            pattern = f"session:*"
            for key in self.redis_client.scan_iter(match=pattern):
                session_data = self.redis_client.get(key)
                if session_data:
                    data = await self.async_optimizer.json_loads(session_data)
                    if user_id is None or data.get("user_id") == user_id:
                        sessions.append(data)

        return sessions

    def validate_request_signature(self, request_data: str, signature: str, timestamp: str) -> bool:
        """Валідація підпису запиту для додаткової безпеки"""
        # Перевірка часової мітки (не старше 5 хвилин)
        try:
            request_time = datetime.fromisoformat(timestamp)
            if datetime.now(timezone.utc) - request_time > timedelta(minutes=5):
                return False
        except:
            return False

        # Перевірка підпису
        expected_signature = hmac.new(
            self.secret_key.encode() if self.secret_key else b'',
            f"{request_data}{timestamp}".encode(),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(signature, expected_signature)


# Глобальний екземпляр менеджера - lazy initialization
_auth_manager = None

def get_auth_manager() -> AuthManager:
    """Get or create the global auth manager instance"""
    global _auth_manager
    if _auth_manager is None:
        logger.info("🔧 Creating new AuthManager instance")
        _auth_manager = AuthManager()
        logger.info("✅ AuthManager instance created successfully")
    return _auth_manager

# For backward compatibility
auth_manager = None  # Will be set by imports that need it


# Dependency для FastAPI
async def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)) -> Dict:
    """Отримання поточного користувача з токена"""
    logger.info("🔐 get_current_user called",
                has_credentials=bool(credentials),
                token_preview=credentials.credentials[:20] + "..." if credentials and len(credentials.credentials) > 20 else "no_token")

    try:
        token = credentials.credentials
        logger.info("📋 Calling decode_token",
                    token_length=len(token) if token else 0)

        payload = await get_auth_manager().decode_token(token)

        logger.info("✅ Token decoded successfully",
                    user_id=payload.get("user_id"),
                    username=payload.get("username"),
                    role=payload.get("role"),
                    session_id=payload.get("session_id"))

        return {
            "user_id": payload.get("user_id"),
            "username": payload.get("username"),
            "role": payload.get("role"),
            "permissions": payload.get("permissions", []),
            "session_id": payload.get("session_id")
        }
    except Exception as e:
        logger.error("❌ Error in get_current_user",
                     error=str(e),
                     error_type=type(e).__name__)
        raise


def require_permission(permission: str):
    """Декоратор для перевірки дозволів"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: Dict = Depends(get_current_user), **kwargs):
            if permission not in user.get("permissions", []):
                raise HTTPException(
                    status_code=403,
                    detail=f"Permission '{permission}' required"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


def require_role(role: str):
    """Декоратор для перевірки ролі"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, user: Dict = Depends(get_current_user), **kwargs):
            if user.get("role") != role:
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{role}' required"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator
