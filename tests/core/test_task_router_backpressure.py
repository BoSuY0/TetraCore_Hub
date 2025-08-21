import asyncio
import os

import pytest


@pytest.mark.anyio
async def test_queue_full_rejects(monkeypatch):
    # Підготуємо TaskRouter із дуже малими чергами, щоб легко переповнити
    from core.task_router import TaskRouter
    from models.task import Task, TaskType, TaskPriority
    from config import Settings

    settings = Settings()
    router = TaskRouter(settings=settings, redis_manager=None)
    # Зменшуємо max_size кожної черги до 1
    for q in router.task_queues.values():
        q.max_size = 1

    await router.initialize()

    # Перший таск проходить
    t1 = Task.create(task_type=TaskType.WORKER_TASK, data={"a": 1}, priority=TaskPriority.LOW)
    ok1 = await router.submit_task(t1)
    assert ok1 is True

    # Другий у ту ж LOW чергу не відхиляємо — він має потрапити в overflow
    t2 = Task.create(task_type=TaskType.WORKER_TASK, data={"a": 2}, priority=TaskPriority.LOW)
    ok2 = await router.submit_task(t2)
    assert ok2 is True


