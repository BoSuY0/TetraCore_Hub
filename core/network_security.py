"""
Network Security Module for TetraCore Hub
Мережева безпека з rate limiting, CORS та захистом від DDoS
"""

import time
import asyncio
import ipaddress
import json
from typing import Dict, Optional, Set, Any, Union
from datetime import datetime
from collections import defaultdict, deque
from functools import wraps
import os

from fastapi import Request, Response, HTTPException, APIRouter
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
# ВАЖЛИВО: CSP конфігурується централізовано у core/security_headers.py.
# Тут не встановлюємо CSP, щоб уникнути перезапису суворіших політик.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
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

        # Керування використанням Redis через ENV
        # За замовчуванням у production вимикаємо Redis-лімітер, щоб зменшити кількість записів
        self.use_redis_for_ratelimit: bool = os.getenv(
            "USE_REDIS_FOR_RATELIMIT", "false"
        ).lower() in ("1", "true", "yes")

        # In-memory storage
        self.rate_limiters: Dict[str, deque] = defaultdict(deque)
        self.blocked_ips: Set[str] = set()
        self.whitelist_ips: Set[str] = set()
        self.whitelist_networks: Set[
            Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
        ] = set()
        self.ip_connections: Dict[str, int] = defaultdict(int)
        self.suspicious_patterns: Dict[str, int] = defaultdict(int)

        # Конфігурація
        self.rate_limit_config = RateLimitConfig()
        # Видалено жорсткий localhost:3000; тепер лише з ALLOWED_ORIGINS або прод-домени
        self.cors_origins = ["https://tetracore.app"]

        # Завантажуємо whitelist
        self._load_whitelist()

        # Запускаємо cleanup task
        self._cleanup_task = None

    def _is_whitelisted(self, ip: str) -> bool:
        """Перевірка IP/мережі на whitelist (підтримує CIDR)."""
        if not ip:
            return False
        if ip in self.whitelist_ips:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.whitelist_networks)

    def _load_whitelist(self):
        """Завантаження IP адрес у whitelist"""
        # Локальні адреси завжди в whitelist
        self.whitelist_ips.update(["127.0.0.1", "::1", "localhost"])

        # Додаткові trusted IP з конфігурації
        raw = os.getenv("WHITELIST_IPS", "").strip()
        file_path = os.getenv("WHITELIST_IPS_FILE", "").strip()

        def add_entry(entry: str) -> None:
            token = (entry or "").strip()
            if not token:
                return
            # CIDR
            if "/" in token:
                try:
                    self.whitelist_networks.add(
                        ipaddress.ip_network(token, strict=False)
                    )
                    return
                except ValueError:
                    logger.warning("Invalid CIDR in WHITELIST_IPS", cidr=token)
                    return
            # IP або hostname
            try:
                ipaddress.ip_address(token)
            except ValueError:
                self.whitelist_ips.add(token)
                return
            self.whitelist_ips.add(token)

        # ENV: comma/newline separated list
        if raw:
            for part in raw.replace("\n", ",").split(","):
                add_entry(part)

        # Optional file: JSON list or newline-separated
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    if content.lstrip().startswith("["):
                        data = json.loads(content)
                        if isinstance(data, list):
                            for item in data:
                                add_entry(str(item))
                    else:
                        for line in content.splitlines():
                            add_entry(line)
            except Exception as e:
                logger.warning(
                    "Failed to load WHITELIST_IPS_FILE",
                    path=file_path,
                    error=str(e),
                )

    def setup_cors(self, app):
        """Налаштування CORS middleware"""
        # У production заборонити wildcard та перевірити ALLOWED_ORIGINS з ENV
        env = os.getenv("ENVIRONMENT", "development").lower()
        env_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
        origins = self.cors_origins
        if env_origins:
            origins = [o.strip() for o in env_origins.split(",") if o.strip()]
        if env == "production":
            # Викидаємо '*' якщо потрапило з конфігурації
            origins = [o for o in origins if o != "*"] or []
            if not origins:
                import structlog

                structlog.get_logger().warning(
                    "ALLOWED_ORIGINS is empty in production; all cross-origin requests will be blocked"
                )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Requested-With",
                "X-Correlation-Id",
            ],
            expose_headers=["X-Total-Count", "X-Page-Count", "X-API-Version"],
            max_age=3600,
        )

    def get_client_ip(self, request: Request) -> str:
        """Отримання реальної IP адреси клієнта.
        Довіряємо X-Forwarded-* тільки якщо запит прийшов від довіреного проксі (TRUSTED_PROXY_IPS).
        """
        trusted = set(
            ip.strip()
            for ip in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
            if ip.strip()
        )
        client_host = request.client.host if request.client else None

        def _validate(ip_str: str) -> bool:
            try:
                ipaddress.ip_address(ip_str)
                return True
            except ValueError:
                return False

        # Якщо запит прийшов від довіреного проксі — читаємо заголовки у пріоритеті
        if client_host and client_host in trusted:
            headers_to_check = [
                "X-Forwarded-For",
                "X-Real-IP",
                "CF-Connecting-IP",
                "True-Client-IP",
                "X-Client-IP",
            ]
            for header in headers_to_check:
                raw = request.headers.get(header)
                if not raw:
                    continue
                ip = (
                    raw.split(",")[0].strip()
                    if header == "X-Forwarded-For"
                    else raw.strip()
                )
                if _validate(ip):
                    return ip

        # Fallback: довіряємо безпосередньому клієнту (не проксі або недовірений проксі)
        return client_host or "unknown"

    async def check_rate_limit(
        self, identifier: str, custom_limit: Optional[int] = None
    ) -> bool:
        """Перевірка rate limit"""
        current_time = time.time()
        limit = custom_limit or self.rate_limit_config.requests_per_minute

        # Збільшуємо ліміт в development режимі
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "development" and custom_limit is None:
            limit = max(limit, 500)  # Мінімум 500 запитів на хвилину в dev

        # Використовуємо Redis тільки якщо явно дозволено через ENV
        if self.redis_client and self.use_redis_for_ratelimit:
            key = f"rate_limit:{identifier}"
            try:
                current_count = self.redis_client.incr(key)
                # Логуємо INCR (значення може бути як int, так і awaitable)
                try:
                    logger.debug(
                        "Redis INCR ratelimit",
                        redis_log=True,
                        key=key,
                        count=(
                            int(current_count)
                            if isinstance(current_count, int)
                            else None
                        ),
                    )
                except Exception:
                    pass
                if current_count == 1:
                    self.redis_client.expire(key, self.rate_limit_config.window_seconds)
                    logger.debug(
                        "Redis EXPIRE ratelimit",
                        redis_log=True,
                        key=key,
                        ttl=self.rate_limit_config.window_seconds,
                    )

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
        if self._is_whitelisted(ip):
            return False

        # Перевірка в Redis
        if self.redis_client:
            blocked_key = f"blocked_ip:{ip}"
            if await self.redis_client.exists(blocked_key):
                logger.debug(
                    "Redis EXISTS blocked_ip",
                    redis_log=True,
                    key=blocked_key,
                    exists=True,
                )
                return True
            else:
                logger.debug(
                    "Redis EXISTS blocked_ip",
                    redis_log=True,
                    key=blocked_key,
                    exists=False,
                )

        # In-memory перевірка
        return ip in self.blocked_ips

    async def block_ip(self, ip: str, duration: int = None, reason: str = None):
        """Блокування IP адреси"""
        if self._is_whitelisted(ip):
            logger.warning("Attempt to block whitelisted IP", ip=ip)
            return

        duration = duration or self.rate_limit_config.block_duration

        # Зберігаємо в Redis
        if self.redis_client:
            blocked_key = f"blocked_ip:{ip}"
            block_info = {
                "blocked_at": datetime.utcnow().isoformat(),
                "duration": duration,
                "reason": reason or "Rate limit exceeded",
            }
            await self.redis_client.setex(blocked_key, duration, json.dumps(block_info))
            logger.debug(
                "Redis SETEX blocked_ip",
                redis_log=True,
                key=blocked_key,
                ttl=duration,
            )

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
        time.time()

        # Пропускаємо перевірку для whitelisted IP (включає localhost)
        if self._is_whitelisted(ip):
            return False

        # Аналіз патернів запитів
        patterns = []

        # 1. Занадто багато запитів з однієї IP
        ip_key = f"ddos_check:{ip}"
        if not await self.check_rate_limit(ip_key, DDOS_THRESHOLD):
            patterns.append("high_request_rate")

        # 2. Підозрілі User-Agent (тільки для не-API запитів)
        user_agent = request.headers.get("User-Agent", "")
        if not request.url.path.startswith("/api/") and (
            not user_agent or len(user_agent) < 10
        ):
            patterns.append("suspicious_user_agent")

        # 3. Відсутні важливі заголовки (тільки для браузерних запитів, не API)
        if not request.url.path.startswith("/api/"):
            required_headers = ["Accept", "Accept-Language"]
            missing_headers = [h for h in required_headers if h not in request.headers]
            if missing_headers:
                patterns.append("missing_headers")

        # 4. Занадто багато з'єднань з IP
        if self.ip_connections.get(ip, 0) > CONNECTION_LIMIT_PER_IP:
            patterns.append("too_many_connections")

        # 5. Підозрілі шляхи (виключаємо legitimate API paths)
        suspicious_paths = [
            "/.env",
            "/wp-admin",
            "/phpmyadmin",
            "/.git",
            "/admin",
            "/backup",
            "/.aws",
            "/config",
        ]
        path_lower = request.url.path.lower()
        if any(path in path_lower for path in suspicious_paths):
            patterns.append("suspicious_path")

        # Оцінка загрози - більш м'яка для development
        threshold = 3 if request.url.path.startswith("/api/") else 2
        if len(patterns) >= threshold:
            logger.warning("DDoS pattern detected", ip=ip, patterns=patterns)
            await self.block_ip(
                ip, DDOS_BLOCK_DURATION, f"DDoS patterns: {', '.join(patterns)}"
            )
            return True

        return False

    async def validate_request(self, request: Request):
        """Валідація запиту на безпеку"""
        client_ip = self.get_client_ip(request)

        # Перевіряємо environment та налаштовуємо відповідні ліміти
        environment = os.getenv("ENVIRONMENT", "development").lower()
        is_development = environment == "development"

        # У development режимі збільшуємо ліміти та спрощуємо перевірки
        if is_development:
            # Більш м'які ліміти для development
            dev_rate_limit = 500  # 500 запитів на хвилину
            logger.debug(
                "Development mode - using relaxed rate limits",
                client_ip=client_ip,
                rate_limit=dev_rate_limit,
            )

            # Тільки базова перевірка rate limit без блокування
            if not await self.check_rate_limit(client_ip, dev_rate_limit):
                logger.warning(
                    "Rate limit exceeded in development mode",
                    client_ip=client_ip,
                    limit=dev_rate_limit,
                )
                raise HTTPException(
                    status_code=429, detail="Too many requests. Please try again later."
                )

            # Пропускаємо DDoS detection та блокування в dev режимі
            return {
                "ip": client_ip,
                "validated": True,
                "timestamp": datetime.utcnow(),
                "environment": "development",
            }

        # Production режим - повна перевірка
        logger.debug(
            "Production mode - using full security validation", client_ip=client_ip
        )

        # 1. Перевірка блокування
        if await self.is_ip_blocked(client_ip):
            raise HTTPException(status_code=403, detail="Access denied")

        # 2. Rate limiting
        if not await self.check_rate_limit(client_ip):
            await self.block_ip(client_ip, reason="Rate limit exceeded")
            raise HTTPException(status_code=429, detail="Too many requests")

        # 3. DDoS detection
        if await self.detect_ddos_pattern(request):
            raise HTTPException(status_code=403, detail="Suspicious activity detected")

        # 4. Розмір запиту
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > REQUEST_SIZE_LIMIT:
            raise HTTPException(status_code=413, detail="Request too large")

        # 5. Реєстрація з'єднання
        self.ip_connections[client_ip] = self.ip_connections.get(client_ip, 0) + 1

        return {
            "ip": client_ip,
            "validated": True,
            "timestamp": datetime.utcnow(),
            "environment": "production",
        }

    def add_security_headers(self, response: Response):
        """Додавання security headers до відповіді"""
        for header, value in SECURITY_HEADERS.items():
            # Не перезаписуємо існуючі заголовки, щоб зберегти налаштування з security_headers_middleware
            if header not in response.headers:
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
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Зберігаємо в Redis для аналізу (з семплінгом, щоб не перевантажувати Redis)
        if self.redis_client:
            try:
                # Семплінг кожного N-го запиту для IP (або всі 4xx/5xx)
                sample_n = int(os.getenv("REQUEST_LOG_SAMPLE_EVERY", "20"))
                sample_key = f"request_log:sample:{ip}"
                c = await self.redis_client.incr(sample_key)
                if c == 1:
                    await self.redis_client.expire(sample_key, 60)
                if (c % sample_n) == 0 or response.status_code >= 400:
                    log_key = f"request_log:{datetime.utcnow().strftime('%Y%m%d')}:{ip}"
                    await self.redis_client.lpush(log_key, json.dumps(log_data))
                    await self.redis_client.expire(log_key, 86400 * 7)
                    logger.debug(
                        "Redis request log stored", redis_log=True, key=log_key
                    )
            except Exception as e:
                logger.debug(
                    "Redis request log store failed", redis_log=True, error=str(e)
                )

    async def get_security_stats(self) -> Dict[str, Any]:
        """Отримання статистики безпеки"""
        stats = {
            "blocked_ips": len(self.blocked_ips),
            "active_connections": sum(self.ip_connections.values()),
            "rate_limiters_active": len(self.rate_limiters),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Додаткова статистика з Redis
        if self.redis_client:
            try:
                # Кількість заблокованих IP в Redis
                blocked_pattern = "blocked_ip:*"
                blocked_count = len(
                    [
                        key
                        async for key in self.redis_client.scan_iter(
                            match=blocked_pattern
                        )
                    ]
                )
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

        # Логування запиту: за замовчуванням у production не логувати кожен запит у Redis
        duration = time.time() - start_time
        environment = os.getenv("ENVIRONMENT", "development").lower()
        slow_threshold = float(os.getenv("REQUEST_LOG_SLOW_THRESHOLD_SECONDS", "5.0"))
        enable_request_logs = os.getenv(
            "ENABLE_REQUEST_LOGS", ("true" if environment == "development" else "false")
        ).lower() in ("1", "true", "yes")

        if (
            enable_request_logs
            or duration > slow_threshold
            or response.status_code >= 400
        ):
            await network_security.log_request(request, response, duration)

        return response

    except HTTPException as http_ex:
        # Логуємо тільки серйозні помилки в development
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment != "development" or http_ex.status_code != 429:
            logger.warning(
                "Security middleware HTTP exception",
                status_code=http_ex.status_code,
                detail=http_ex.detail,
                path=request.url.path,
            )
        raise
    except Exception as e:
        logger.error(
            "Security middleware error", error=str(e), exception_type=type(e).__name__
        )
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
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

            if not await network_security.check_rate_limit(
                endpoint_key, requests_per_minute
            ):
                raise HTTPException(
                    status_code=429, detail="Rate limit exceeded for this endpoint"
                )

            return await func(request, *args, **kwargs)

        return wrapper

    return decorator


def require_ip_whitelist(func):
    """Декоратор для endpoints що вимагають whitelist"""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Шукаємо request в аргументах
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break

        # Або в kwargs
        if not request:
            request = kwargs.get("request")

        if not request:
            raise HTTPException(status_code=500, detail="Request object not found")

        ip = network_security.get_client_ip(request)

        if not network_security._is_whitelisted(ip):
            logger.warning(
                "Access denied for non-whitelisted IP", ip=ip, path=request.url.path
            )
            raise HTTPException(status_code=403, detail="Access denied")

        return await func(*args, **kwargs)

    return wrapper


# API endpoints для управління безпекою
security_router = APIRouter(prefix="/api/security", tags=["security"])


@security_router.get("/stats")
@require_ip_whitelist
async def get_security_stats(request: Request):
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
    token = (ip or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="IP is required")
    if "/" in token:
        try:
            network_security.whitelist_networks.add(
                ipaddress.ip_network(token, strict=False)
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid CIDR")
    else:
        network_security.whitelist_ips.add(token)
    return {"message": f"IP {ip} added to whitelist"}
