"""
TetraCore StreamHub Rate Limiter

Модуль для обмеження частоти запитів до API.
Використовує Redis для зберігання лічильників та sliding window.
"""

import time
import asyncio
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import structlog
import orjson

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Rate limiter з sliding window алгоритмом"""

    def __init__(self, redis_client=None, default_window_seconds: int = 60, default_limit: int = 100):
        """
        Ініціалізація rate limiter
        
        Args:
            redis_client: Redis клієнт для зберігання стану
            default_window_seconds: Розмір вікна в секундах
            default_limit: Максимальна кількість запитів у вікні
        """
        self.redis_client = redis_client
        self.default_window_seconds = default_window_seconds
        self.default_limit = default_limit
        
        # Fallback in-memory storage якщо Redis недоступний
        self.memory_storage: Dict[str, Dict[str, Any]] = {}
        
        self.logger = logger

    async def is_allowed(
        self,
        key: str,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        cost: int = 1
    ) -> Dict[str, Any]:
        """
        Перевіряє чи дозволено виконати запит
        
        Args:
            key: Унікальний ключ (наприклад, IP адреса або user ID)
            limit: Максимальна кількість запитів
            window_seconds: Розмір вікна в секундах
            cost: Вартість запиту (за замовчуванням 1)
            
        Returns:
            Dict з результатом перевірки та метаданими
        """
        limit = limit or self.default_limit
        window_seconds = window_seconds or self.default_window_seconds
        
        if self.redis_client:
            return await self._check_redis(key, limit, window_seconds, cost)
        else:
            return await self._check_memory(key, limit, window_seconds, cost)

    async def _check_redis(self, key: str, limit: int, window_seconds: int, cost: int) -> Dict[str, Any]:
        """Перевірка з використанням Redis"""
        try:
            current_time = time.time()
            redis_key = f"rate_limit:{key}"
            
            # Використовуємо Redis pipeline для атомарності
            pipe = self.redis_client.pipeline()
            
            # Видаляємо застарілі записи
            pipe.zremrangebyscore(redis_key, 0, current_time - window_seconds)
            
            # Отримуємо поточну кількість запитів
            pipe.zcard(redis_key)
            
            # Додаємо новий запит
            pipe.zadd(redis_key, {str(current_time): current_time})
            
            # Встановлюємо TTL
            pipe.expire(redis_key, window_seconds + 1)
            
            results = await pipe.execute()
            current_count = results[1]
            
            # Перевіряємо ліміт
            allowed = (current_count + cost) <= limit
            remaining = max(0, limit - current_count - cost)
            
            if not allowed:
                # Видаляємо додану запис якщо перевищено ліміт
                await self.redis_client.zrem(redis_key, str(current_time))
            
            # Розраховуємо час до скидання ліміту
            oldest_request = await self.redis_client.zrange(redis_key, 0, 0, withscores=True)
            reset_at = current_time + window_seconds
            if oldest_request:
                reset_at = oldest_request[0][1] + window_seconds
            
            return {
                "allowed": allowed,
                "limit": limit,
                "remaining": remaining,
                "reset_at": reset_at,
                "retry_after": reset_at - current_time if not allowed else 0,
                "current_count": current_count,
                "window_seconds": window_seconds
            }
            
        except Exception as e:
            self.logger.error("Redis rate limit check failed", error=str(e), key=key)
            # Fallback до memory storage
            return await self._check_memory(key, limit, window_seconds, cost)

    async def _check_memory(self, key: str, limit: int, window_seconds: int, cost: int) -> Dict[str, Any]:
        """Fallback перевірка в пам'яті"""
        current_time = time.time()
        
        if key not in self.memory_storage:
            self.memory_storage[key] = {"requests": [], "last_cleanup": current_time}
        
        storage = self.memory_storage[key]
        
        # Очищаємо застарілі записи
        cutoff_time = current_time - window_seconds
        storage["requests"] = [req_time for req_time in storage["requests"] if req_time > cutoff_time]
        
        current_count = len(storage["requests"])
        allowed = (current_count + cost) <= limit
        remaining = max(0, limit - current_count - cost)
        
        if allowed:
            storage["requests"].append(current_time)
        
        # Розраховуємо час до скидання
        reset_at = current_time + window_seconds
        if storage["requests"]:
            reset_at = min(storage["requests"]) + window_seconds
        
        return {
            "allowed": allowed,
            "limit": limit,
            "remaining": remaining,
            "reset_at": reset_at,
            "retry_after": reset_at - current_time if not allowed else 0,
            "current_count": current_count,
            "window_seconds": window_seconds
        }

    async def reset(self, key: str):
        """Скидання лічильника для ключа"""
        if self.redis_client:
            try:
                await self.redis_client.delete(f"rate_limit:{key}")
            except Exception as e:
                self.logger.error("Failed to reset rate limit in Redis", error=str(e), key=key)
        
        if key in self.memory_storage:
            del self.memory_storage[key]

    async def get_status(self, key: str, window_seconds: Optional[int] = None) -> Dict[str, Any]:
        """Отримання поточного статусу без зміни лічильника"""
        window_seconds = window_seconds or self.default_window_seconds
        
        if self.redis_client:
            try:
                current_time = time.time()
                redis_key = f"rate_limit:{key}"
                
                # Видаляємо застарілі записи
                await self.redis_client.zremrangebyscore(redis_key, 0, current_time - window_seconds)
                
                # Отримуємо поточну кількість
                current_count = await self.redis_client.zcard(redis_key)
                
                # Розраховуємо час до скидання
                oldest_request = await self.redis_client.zrange(redis_key, 0, 0, withscores=True)
                reset_at = current_time + window_seconds
                if oldest_request:
                    reset_at = oldest_request[0][1] + window_seconds
                
                return {
                    "current_count": current_count,
                    "reset_at": reset_at,
                    "window_seconds": window_seconds
                }
                
            except Exception as e:
                self.logger.error("Failed to get rate limit status from Redis", error=str(e), key=key)
        
        # Fallback до memory
        if key in self.memory_storage:
            storage = self.memory_storage[key]
            current_time = time.time()
            cutoff_time = current_time - window_seconds
            
            current_requests = [req_time for req_time in storage["requests"] if req_time > cutoff_time]
            reset_at = current_time + window_seconds
            if current_requests:
                reset_at = min(current_requests) + window_seconds
            
            return {
                "current_count": len(current_requests),
                "reset_at": reset_at,
                "window_seconds": window_seconds
            }
        
        return {
            "current_count": 0,
            "reset_at": time.time() + window_seconds,
            "window_seconds": window_seconds
        }

    async def cleanup_expired(self):
        """Очищення застарілих записів (для memory storage)"""
        current_time = time.time()
        expired_keys = []
        
        for key, storage in self.memory_storage.items():
            # Очищаємо якщо немає запитів останні 2 вікна
            if current_time - storage.get("last_cleanup", 0) > self.default_window_seconds * 2:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.memory_storage[key]
        
        if expired_keys:
            self.logger.debug("Cleaned up expired rate limit entries", count=len(expired_keys))


# Глобальний інстанс rate limiter
rate_limiter = None


def get_rate_limiter() -> RateLimiter:
    """Отримання глобального інстансу rate limiter"""
    global rate_limiter
    if rate_limiter is None:
        rate_limiter = RateLimiter()
    return rate_limiter


def init_rate_limiter(redis_client=None, **kwargs):
    """Ініціалізація глобального rate limiter"""
    global rate_limiter
    rate_limiter = RateLimiter(redis_client=redis_client, **kwargs)
    return rate_limiter 