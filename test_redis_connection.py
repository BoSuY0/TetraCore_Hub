#!/usr/bin/env python3
"""
Тест підключення до Redis з продакшен даними
"""

import asyncio
import json
import os
import sys
from datetime import datetime

import redis.asyncio as redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError


async def test_redis_connection():
    """Тестування підключення до Redis"""
    
    # Продакшен Redis URL
    redis_url = "redis://default:yiyAwEptyrnORRT5QQY4Zum3m7j5c4Aj@redis-14708.c78.eu-west-1-2.ec2.redns.redis-cloud.com:14708"
    
    print(f"🔗 Тестування підключення до Redis...")
    print(f"📍 URL: {redis_url}")
    print("-" * 50)
    
    try:
        # Створення клієнта
        client = redis.from_url(
            redis_url,
            max_connections=10,
            retry_on_timeout=True,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=10
        )
        
        # Тест підключення
        print("🔄 Тестування ping...")
        ping_result = await client.ping()
        print(f"✅ Ping успішний: {ping_result}")
        
        # Тест запису/читання
        print("\n🔄 Тестування запису/читання...")
        test_key = f"tetra:test:{datetime.utcnow().timestamp()}"
        test_value = {
            "message": "Тест з TetraCore Hub",
            "timestamp": datetime.utcnow().isoformat(),
            "source": "test_redis_connection.py"
        }
        
        # Запис
        await client.set(test_key, json.dumps(test_value, ensure_ascii=False), ex=60)
        print(f"✅ Запис успішний: {test_key}")
        
        # Читання
        stored_value = await client.get(test_key)
        parsed_value = json.loads(stored_value)
        print(f"✅ Читання успішне: {parsed_value['message']}")
        
        # Тест Pub/Sub
        print("\n🔄 Тестування Pub/Sub...")
        pubsub = client.pubsub()
        
        test_channel = "tetra:test:channel"
        await pubsub.subscribe(test_channel)
        print(f"✅ Підписка на канал: {test_channel}")
        
        # Публікація повідомлення
        test_message = {
            "type": "test",
            "content": "Тестове повідомлення",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        subscribers = await client.publish(test_channel, json.dumps(test_message, ensure_ascii=False))
        print(f"✅ Повідомлення опубліковано для {subscribers} підписників")
        
        # Отримання повідомлення
        message = await pubsub.get_message(timeout=5.0)
        if message and message['type'] == 'message':
            received_data = json.loads(message['data'])
            print(f"✅ Повідомлення отримано: {received_data['content']}")
        
        # Очищення
        await pubsub.unsubscribe(test_channel)
        await client.delete(test_key)
        
        # Інформація про сервер
        print("\n📊 Інформація про Redis сервер:")
        info = await client.info()
        print(f"   Версія Redis: {info.get('redis_version', 'Невідома')}")
        print(f"   Режим: {info.get('redis_mode', 'Невідомий')}")
        print(f"   Підключені клієнти: {info.get('connected_clients', 0)}")
        print(f"   Використана пам'ять: {info.get('used_memory_human', 'Невідомо')}")
        
        await client.close()
        
        print("\n🎉 Всі тести пройшли успішно!")
        print("✅ Redis готовий для використання в продакшені")
        
        return True
        
    except ConnectionError as e:
        print(f"❌ Помилка підключення: {e}")
        return False
    except TimeoutError as e:
        print(f"❌ Таймаут підключення: {e}")
        return False
    except RedisError as e:
        print(f"❌ Помилка Redis: {e}")
        return False
    except Exception as e:
        print(f"❌ Несподівана помилка: {e}")
        return False


async def test_redis_manager():
    """Тестування Redis через RedisManager"""
    print("\n" + "="*50)
    print("🔧 Тестування через RedisManager")
    print("="*50)
    
    try:
        # Встановлення змінних середовища
        os.environ['REDIS_URL'] = "redis://default:yiyAwEptyrnORRT5QQY4Zum3m7j5c4Aj@redis-14708.c78.eu-west-1-2.ec2.redns.redis-cloud.com:14708"
        os.environ['REDIS_ENABLED'] = "true"
        os.environ['ENVIRONMENT'] = "production"
        
        # Імпорт після встановлення змінних
        from config import get_settings
        from core.redis_manager import RedisManager
        
        settings = get_settings()
        print(f"📍 Redis URL з налаштувань: {settings.redis_url}")
        
        # Створення менеджера
        redis_manager = RedisManager(settings)
        
        # Ініціалізація
        print("🔄 Ініціалізація RedisManager...")
        await redis_manager.initialize()
        print("✅ RedisManager ініціалізовано")
        
        # Тест здоров'я
        is_healthy = await redis_manager.is_healthy()
        print(f"✅ Стан здоров'я: {is_healthy}")
        
        # Тест публікації
        test_data = {
            "message_id": f"test_{datetime.utcnow().timestamp()}",
            "content": "Тест через RedisManager",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        success = await redis_manager.publish("tetra:test", test_data)
        print(f"✅ Публікація: {success}")
        
        # Статистика
        stats = redis_manager.get_stats()
        print(f"📊 Статистика RedisManager:")
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        # Зупинка
        await redis_manager.shutdown()
        print("✅ RedisManager зупинено")
        
        return True
        
    except Exception as e:
        print(f"❌ Помилка RedisManager: {e}")
        return False


if __name__ == "__main__":
    print("🚀 Запуск тестування Redis підключення")
    print("="*50)
    
    # Основний тест
    success1 = asyncio.run(test_redis_connection())
    
    # Тест через RedisManager
    success2 = asyncio.run(test_redis_manager())
    
    if success1 and success2:
        print("\n🎉 Всі тести пройшли успішно!")
        sys.exit(0)
    else:
        print("\n❌ Деякі тести не пройшли")
        sys.exit(1) 