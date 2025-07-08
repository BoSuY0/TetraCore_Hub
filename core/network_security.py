"""
Network Security Module for TetraCore Hub
Мережева безпека з rate limiting, CORS та захистом від DDoS
"""

import time
import asyncio
import ipaddress
import hashlib
import json
from typing import Dict, List, Optional, Set, Tuple, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
from functools import wraps

from fastapi import Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import redis
from pydantic import BaseModel, Field

logger = structlog.get_logger()

# Константи для rate limiting
DEFAULT_RATE_LIMIT = 100  # Запитів на хвилину
BURST_RATE_LIMIT = 200  # Максимальний burst
RATE_LIMIT_WINDOW = 60  # Вікно в секундах
BLOCK_DURATION = 3600  # Тривалість блокування (1 година)

# Константи для DDoS захисту
DDOS_THRESHOLD = 1000  # Запитів на хвилину для виявлення DDoS
DDOS_BLOCK_DURATION = 86400  # 24 години блокування
CONNECTION_LIMIT_PER_IP = 20  # Максимум одночасних з'єднань з IP
REQUEST_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB максимальний розмір запиту

# Security headers
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline';",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
}


class RateLimitConfig(BaseModel):
    """Конфігурація rate limiting"""
    requests_per_minute: int = Field(default=DEFAULT_RATE_LIMIT)
    burst_limit: int = Field(default=BURST_RATE_LIMIT)
    window_seconds: int = Field(default=RATE_LIMIT_WINDOW)
    block_duration: int = Field(default=BLOCK_DURATION)


class IPInfo(BaseModel):
    """Інформація про IP адресу"""
    ip: str
    request_count: int = 0
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    blocked: bool = False
    blocked_until: Optional[datetime] = None
    suspicious_score: int = 0
    user_agent: Optional[str] = None
    country: Optional[str] = None


class NetworkSecurityManager:
    """Менеджер мережевої безпеки"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        self.redis_client = redis_client

        # In-memory storage
        self.rate_limiters: Dict[str, deque] = defaultdict(deque)
        self.blocked_ips: Set[str] = set()
        self.whitelist_ips: Set[str] = set()
        self.ip_connections: Dict[str, int] = defaultdict(int)
        self.suspicious_patterns: Dict[str, int] = defaultdict(int)

        # Конфігурація
        self.rate_limit_config = RateLimitConfig()
        self.cors_origins = ["http://localhost:3000", "https://tetracore.app"]

        # Завантажуємо whitelist
        self._load_whitelist()

        # Запускаємо cleanup task
        self._cleanup_task = None

    def _load_whitelist(self):
        """Завантаження IP адрес у whitelist"""
        # Локальні адреси завжди в whitelist
        self.whitelist_ips.update([
            "127.0.0.1",
            "::1",
            "localhost"
        ])

        # Додаткові trusted IP з конфігурації
        # TODO: Завантажити з конфігурації або БД

    def setup_cors(self, app):
        """Налаштування CORS middleware"""
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-Total-Count", "X-Page-Count"],
            max_age=3600
        )

    def get_client_ip(self, request: Request) -> str:
        """Отримання реальної IP адреси клієнта"""
        # Перевіряємо заголовки в порядку пріоритету
        headers_to_check = [
            "X-Real-IP",
            "X-Forwarded-For",
            "CF-Connecting-IP",  # Cloudflare
            "True-Client-IP",    # Cloudflare Enterprise
            "X-Client-IP"
        ]

        for header in headers_to_check:
            ip = request.headers.get(header)
            if ip:
                # X-Forwarded-For може містити список IP
                if header == "X-Forwarded-For":
                    ip = ip.split(",")[0].strip()

                # Валідація IP
                try:
                    ipaddress.ip_address(ip)
                    return ip
                except ValueError:
                    continue

        # Fallback на request.client
        if request.client:
            return request.client.host

        return "unknown"

    async def check_rate_limit(self, identifier: str, custom_limit: Optional[int] = None) -> bool:
        """Перевірка rate limit"""
        current_time = time.time()
        limit = custom_limit or self.rate_limit_config.requests_per_minute

        # Використовуємо Redis якщо доступний
        if self.redis_client:
            key = f"rate_limit:{identifier}"
            try:
                current_count = self.redis_client.incr(key)
                if current_count == 1:
                    self.redis_client.expire(key, self.rate_limit_config.window_seconds)

                return current_count <= limit
            except Exception as e:
                logger.error("Redis rate limit error", error=str(e))
                # Fallback на in-memory

        # In-memory rate limiting
        requests = self.rate_limiters[identifier]

        # Видаляємо старі записи
        cutoff_time = current_time - self.rate_limit_config.window_seconds
        while requests and requests[0] < cutoff_time:
            requests.popleft()

        # Перевіряємо ліміт
        if len(requests) >= limit:
            return False

        requests.append(current_time)
        return True

    async def is_ip_blocked(self, ip: str) -> bool:
        """Перевірка чи IP заблокована"""
        # Whitelist завжди дозволений
        if ip in self.whitelist_ips:
            return False

        # Перевірка в Redis
        if self.redis_client:
            blocked_key = f"blocked_ip:{ip}"
            if self.redis_client.exists(blocked_key):
                return True

        # In-memory перевірка
        return ip in self.blocked_ips

    async def block_ip(self, ip: str, duration: int = None, reason: str = None):
        """Блокування IP адреси"""
        if ip in self.whitelist_ips:
            logger.warning("Attempt to block whitelisted IP", ip=ip)
            return

        duration = duration or self.rate_limit_config.block_duration

        # Зберігаємо в Redis
        if self.redis_client:
            blocked_key = f"blocked_ip:{ip}"
            block_info = {
                "blocked_at": datetime.utcnow().isoformat(),
                "duration": duration,
                "reason": reason or "Rate limit exceeded"
            }
            self.redis_client.setex(blocked_key, duration, json.dumps(block_info))

        # In-memory блокування
        self.blocked_ips.add(ip)

        logger.warning("IP blocked", ip=ip, duration=duration, reason=reason)

        # Запускаємо таймер для розблокування
        asyncio.create_task(self._unblock_ip_after(ip, duration))

    async def _unblock_ip_after(self, ip: str, duration: int):
        """Розблокування IP після таймауту"""
        await asyncio.sleep(duration)
        self.blocked_ips.discard(ip)
        logger.info("IP unblocked", ip=ip)

    async def detect_ddos_pattern(self, request: Request) -> bool:
        """Виявлення патернів DDoS атаки"""
        ip = self.get_client_ip(request)
        current_time = time.time()

        # Аналіз патернів запитів
        patterns = []

        # 1. Занадто багато запитів з однієї IP
        ip_key = f"ddos_check:{ip}"
        if not await self.check_rate_limit(ip_key, DDOS_THRESHOLD):
            patterns.append("high_request_rate")

        # 2. Підозрілі User-Agent
        user_agent = request.headers.get("User-Agent", "")
        if not user_agent or len(user_agent) < 10:
            patterns.append("suspicious_user_agent")

        # 3. Відсутні важливі заголовки
        required_headers = ["Accept", "Accept-Language"]
        missing_headers = [h for h in required_headers if h not in request.headers]
        if missing_headers:
            patterns.append("missing_headers")

        # 4. Занадто багато з'єднань з IP
        if self.ip_connections.get(ip, 0) > CONNECTION_LIMIT_PER_IP:
            patterns.append("too_many_connections")

        # 5. Підозрілі шляхи
        suspicious_paths = [
            "/.env", "/wp-admin", "/phpmyadmin", "/.git",
            "/admin", "/backup", "/.aws", "/config"
        ]
        if any(path in request.url.path.lower() for path in suspicious_paths):
            patterns.append("suspicious_path")

        # Оцінка загрози
        if len(patterns) >= 2:
            logger.warning("DDoS pattern detected", ip=ip, patterns=patterns)
            await self.block_ip(ip, DDOS_BLOCK_DURATION, f"DDoS patterns: {', '.join(patterns)}")
            return True

        return False

    async def validate_request(self, request: Request) -> Dict[str, Any]:
        """Комплексна валідація запиту"""
        ip = self.get_client_ip(request)

        # 1. Перевірка блокування
        if await self.is_ip_blocked(ip):
            raise HTTPException(status_code=403, detail="Access denied")

        # 2. Rate limiting
        if not await self.check_rate_limit(ip):
            await self.block_ip(ip, reason="Rate limit exceeded")
            raise HTTPException(status_code=429, detail="Too many requests")

        # 3. DDoS detection
        if await self.detect_ddos_pattern(request):
            raise HTTPException(status_code=403, detail="Suspicious activity detected")

        # 4. Розмір запиту
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > REQUEST_SIZE_LIMIT:
            raise HTTPException(status_code=413, detail="Request too large")

        # 5. Реєстрація з'єднання
        self.ip_connections[ip] = self.ip_connections.get(ip, 0) + 1

        return {
            "ip": ip,
            "validated": True,
            "timestamp": datetime.utcnow()
        }

    def add_security_headers(self, response: Response):
        """Додавання security headers до відповіді"""
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value

    async def log_request(self, request: Request, response: Response, duration: float):
        """Логування запиту для аналізу"""
        ip = self.get_client_ip(request)

        log_data = {
            "ip": ip,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration": duration,
            "user_agent": request.headers.get("User-Agent", ""),
            "timestamp": datetime.utcnow().isoformat()
        }

        # Зберігаємо в Redis для аналізу
        if self.redis_client:
            log_key = f"request_log:{datetime.utcnow().strftime('%Y%m%d')}:{ip}"
            self.redis_client.lpush(log_key, json.dumps(log_data))
            self.redis_client.expire(log_key, 86400 * 7)  # Зберігаємо 7 днів

    async def get_security_stats(self) -> Dict[str, Any]:
        """Отримання статистики безпеки"""
        stats = {
            "blocked_ips": len(self.blocked_ips),
            "active_connections": sum(self.ip_connections.values()),
            "rate_limiters_active": len(self.rate_limiters),
            "timestamp": datetime.utcnow().isoformat()
        }

        # Додаткова статистика з Redis
        if self.redis_client:
            try:
                # Кількість заблокованих IP в Redis
                blocked_pattern = "blocked_ip:*"
                blocked_count = len(list(self.redis_client.scan_iter(match=blocked_pattern)))
                stats["total_blocked_ips"] = blocked_count + len(self.blocked_ips)
            except Exception as e:
                logger.error("Error getting Redis stats", error=str(e))

        return stats

    async def cleanup_connections(self, ip: str):
        """Очищення з'єднань для IP"""
        if ip in self.ip_connections:
            self.ip_connections[ip] = max(0, self.ip_connections[ip] - 1)
            if self.ip_connections[ip] == 0:
                del self.ip_connections[ip]


# Глобальний екземпляр
network_security = NetworkSecurityManager()


# Middleware для FastAPI
async def security_middleware(request: Request, call_next):
    """Security middleware для всіх запитів"""
    start_time = time.time()

    try:
        # Валідація запиту
        await network_security.validate_request(request)

        # Обробка запиту
        response = await call_next(request)

        # Додавання security headers
        network_security.add_security_headers(response)

        # Логування
        duration = time.time() - start_time
        await network_security.log_request(request, response, duration)

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Security middleware error", error=str(e))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    finally:
        # Очищення з'єднання
        ip = network_security.get_client_ip(request)
        await network_security.cleanup_connections(ip)


# Декоратори для специфічних endpoints
def rate_limit(requests_per_minute: int = None):
    """Декоратор для кастомного rate limiting"""
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            ip = network_security.get_client_ip(request)
            endpoint_key = f"{ip}:{request.url.path}"

            if not await network_security.check_rate_limit(endpoint_key, requests_per_minute):
                raise HTTPException(status_code=429, detail="Rate limit exceeded for this endpoint")

            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_ip_whitelist(func):
    """Декоратор для endpoints що вимагають whitelist"""
    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        ip = network_security.get_client_ip(request)

        if ip not in network_security.whitelist_ips:
            logger.warning("Access denied for non-whitelisted IP", ip=ip, path=request.url.path)
            raise HTTPException(status_code=403, detail="Access denied")

        return await func(request, *args, **kwargs)
    return wrapper


# API endpoints для управління безпекою
from fastapi import APIRouter

security_router = APIRouter(prefix="/api/security", tags=["security"])


@security_router.get("/stats")
@require_ip_whitelist
async def get_security_stats():
    """Отримання статистики безпеки"""
    return await network_security.get_security_stats()


@security_router.post("/block-ip")
@require_ip_whitelist
async def block_ip_endpoint(ip: str, duration: int = 3600, reason: str = None):
    """Ручне блокування IP"""
    await network_security.block_ip(ip, duration, reason)
    return {"message": f"IP {ip} blocked for {duration} seconds"}


@security_router.post("/whitelist-ip")
@require_ip_whitelist
async def whitelist_ip_endpoint(ip: str):
    """Додавання IP до whitelist"""
    network_security.whitelist_ips.add(ip)
    return {"message": f"IP {ip} added to whitelist"}
