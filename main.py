#!/usr/bin/env python3
"""
TetraCore StreamHub - Main Entry Point

Головна точка входу для FastAPI додатку.
Забезпечує сумісність та простий інтерфейс для запуску.
"""

import asyncio
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

# Додаємо поточну директорію до Python path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
import structlog
import uvicorn

from core.hub import StreamHub
from config import get_settings

# Глобальна змінна для зберігання екземпляру StreamHub
_hub_instance: Optional[StreamHub] = None

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управління життєвим циклом додатку"""
    global _hub_instance

    # Startup
    logger.info("🚀 Запуск TetraCore StreamHub...")

    try:
        # Створюємо та ініціалізуємо StreamHub
        hub = StreamHub()
        await hub.initialize()

        # Зберігаємо в app state та глобально
        app.state.hub = hub
        _hub_instance = hub

        logger.info("✅ StreamHub успішно запущено")

        yield

    finally:
        # Shutdown
        logger.info("🛑 Зупинка StreamHub...")

        if _hub_instance:
            try:
                await _hub_instance.shutdown()
            except Exception as e:
                logger.error(f"Помилка при зупинці StreamHub: {e}")
            finally:
                _hub_instance = None

        logger.info("👋 StreamHub зупинено")


def create_application() -> FastAPI:
    """
    Створює та налаштовує FastAPI додаток

    Returns:
        FastAPI: Налаштований додаток
    """
    settings = get_settings()

    # Створюємо тимчасовий hub для отримання app
    hub = StreamHub(settings)
    app = hub.get_app()

    # Встановлюємо lifespan
    if hasattr(app, 'router') and hasattr(app.router, 'lifespan_context'):
        app.router.lifespan_context = lifespan
    else:
        # Для старіших версій FastAPI
        new_app = FastAPI(
            title="TetraCore StreamHub",
            description="Централізований хаб для маршрутизації завдань",
            version="2.0.0",
            lifespan=lifespan
        )
        # Копіюємо всі роути
        new_app.mount("/", app)
        app = new_app

    return app


def get_hub() -> Optional[StreamHub]:
    """
    Отримує поточний екземпляр StreamHub

    Returns:
        StreamHub або None якщо hub не ініціалізовано
    """
    return _hub_instance


# Створюємо додаток
app = create_application()


if __name__ == "__main__":
    """Запуск через python main.py"""
    settings = get_settings()

    # Налаштування логування
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Запускаємо сервер
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if settings.DEBUG else "warning",
        access_log=settings.DEBUG,
        use_colors=True,
        loop="asyncio"
    )
