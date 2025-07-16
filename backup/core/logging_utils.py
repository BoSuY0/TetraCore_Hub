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