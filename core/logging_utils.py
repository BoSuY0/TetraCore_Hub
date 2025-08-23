"""logging_utils.py – допоміжні утиліти для налаштування логування

Містить процесор `RateLimiterProcessor`, який відфільтровує повторювані
повідомлення, що зʼявляються частіше ніж раз на `min_interval` секунд.
Це дозволяє залишити детальне логування без спаму.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any, Dict

import structlog


class RateLimiterProcessor:  # pragma: no cover – простий допоміжний клас
    """Процесор structlog, що відкидає повторювані події.

    Подія визначається ключем *key*
    (за замовчуванням береться з поля *event* / *msg* у `event_dict`).
    Якщо з моменту попереднього логування з тим самим ключем
    пройшло менше `min_interval` секунд, подія буде пропущена.
    """

    def __init__(self, min_interval: float = 10.0):
        self.min_interval = float(min_interval)
        self._last: Dict[str, float] = defaultdict(float)
        self._lock = Lock()

    # Інтерфейс structlog: processor(logger, method_name, event_dict) -> event_dict
    def __call__(self, _: Any, __: str, event_dict: Dict[str, Any]):  # type: ignore[override]
        key = str(event_dict.get("event") or event_dict.get("msg") or "<no_event_key>")
        now = time.time()
        with self._lock:
            last_time = self._last[key]
            if now - last_time < self.min_interval:
                # Пропускаємо подію – занадто часто
                raise structlog.DropEvent
            self._last[key] = now
        # Пропускаємо event_dict далі в конвеєр
        return event_dict


class RedactSecretsProcessor:  # pragma: no cover – простий допоміжний клас
    """Процесор structlog, що маскує секретні поля в логах.

    Маскує:
    - Заголовок Authorization (Bearer ...)
    - Поля з ключами на кшталт: auth, token, secret, password (регістр неважливий)
    """

    SENSITIVE_KEYS = ("authorization", "auth", "token", "secret", "password")

    def __call__(self, _: Any, __: str, event_dict: Dict[str, Any]):  # type: ignore[override]
        def _redact_value(value: Any) -> Any:
            if isinstance(value, dict):
                out = {}
                for k, v in value.items():
                    if self._is_sensitive_key(k):
                        out[k] = self._redact(v)
                    elif k in ("task_data", "data") and isinstance(v, dict):
                        # Робимо превʼю ключів замість повного дампу
                        out[k + "_preview"] = list(v.keys())[:10]
                        out[k] = "<hidden>"
                    else:
                        out[k] = _redact_value(v)
                return out
            if isinstance(value, (list, tuple)):
                t = type(value)
                return t(_redact_value(v) for v in value)
            return value

        # Маскуємо Authorization та інші чутливі ключі у корені event_dict
        for key in list(event_dict.keys()):
            if self._is_sensitive_key(key):
                event_dict[key] = self._redact(event_dict.get(key))
            else:
                event_dict[key] = _redact_value(event_dict[key])

        return event_dict

    def _is_sensitive_key(self, key: str) -> bool:
        k = key.lower()
        return any(s in k for s in self.SENSITIVE_KEYS)

    def _redact(self, value: Any) -> str:
        try:
            if isinstance(value, str) and value.lower().startswith("bearer "):
                return "Bearer <redacted>"
            return "<redacted>"
        except Exception:
            return "<redacted>"


class SampleInfoProcessor:  # pragma: no cover – простий допоміжний клас
    """Відкидає частину INFO логів за семпл-рейтом для зменшення шуму.

    Увімкнення: LOG_INFO_SAMPLE_RATE (0.0-1.0, за замовчуванням 1.0 – не відкидати)
    """

    def __init__(self):
        import os
        import random

        self.random = random
        try:
            self.rate = float(os.getenv("LOG_INFO_SAMPLE_RATE", "1.0"))
        except Exception:
            self.rate = 1.0

    def __call__(self, logger, method_name, event_dict):  # type: ignore[override]
        if method_name.lower() == "info" and self.rate < 1.0:
            if self.random.random() > self.rate:
                raise structlog.DropEvent
        return event_dict
