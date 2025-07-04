#!/usr/bin/env python3
"""
Тест функції parse_message з повідомленням реєстрації.
"""

import json
import sys
from datetime import datetime

try:
    from models.messages import parse_message, MessageType, ClientType
    print("✅ Модулі успішно імпортовані")
except ImportError as e:
    print(f"❌ Помилка імпорту: {e}")
    sys.exit(1)

def test_parse_message():
    """Тест парсингу повідомлення реєстрації"""
    print("🔍 ТЕСТ ФУНКЦІЇ PARSE_MESSAGE")
    print("=" * 50)
    
    # Точне повідомлення з нашого тесту
    registration_data = {
        "message_id": "5e69030f-f122-4132-a6fb-204e44475799",
        "message_type": "client_registration",
        "timestamp": "2025-07-04T13:47:52.632818",
        "sender_id": "tetracore_bot_ff524e51",
        "client_type": "bot",
        "client_id": "tetracore_bot_ff524e51",
        "client_name": "Exact HubClient Test",
        "client_version": "1.0.0",
        "capabilities": [],
        "max_concurrent_tasks": 1,
        "auth_token": None,
        "client_info": {
            "platform": "TetraCore",
            "version": "1.0.0",
            "capabilities": [
                "task_submission",
                "health_monitoring"
            ]
        }
    }
    
    print("📤 Дані для парсингу:")
    print(json.dumps(registration_data, indent=2, ensure_ascii=False))
    print()
    
    try:
        # Спроба парсингу
        print("🔄 Спроба парсингу повідомлення...")
        message = parse_message(registration_data)
        
        print("✅ Повідомлення успішно розпарсено!")
        print(f"📋 Тип повідомлення: {message.message_type}")
        print(f"🤖 Тип клієнта: {message.client_type}")
        print(f"🆔 ID клієнта: {message.client_id}")
        print(f"👤 Ім'я клієнта: {message.client_name}")
        print(f"📦 Версія клієнта: {message.client_version}")
        print(f"⚡ Можливості: {message.capabilities}")
        print(f"🔢 Макс. завдань: {message.max_concurrent_tasks}")
        print(f"🔐 Токен авторизації: {message.auth_token}")
        print(f"ℹ️ Інформація про клієнта: {message.client_info}")
        
        # Перевірка типів
        print("\n📊 ПЕРЕВІРКА ТИПІВ:")
        print(f"message_type == MessageType.CLIENT_REGISTRATION: {message.message_type == MessageType.CLIENT_REGISTRATION}")
        print(f"client_type == ClientType.BOT: {message.client_type == ClientType.BOT}")
        
        return True
        
    except Exception as e:
        print(f"❌ Помилка парсингу: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enum_values():
    """Тест значень enum'ів"""
    print("\n🔍 ТЕСТ ЗНАЧЕНЬ ENUM'ІВ")
    print("-" * 30)
    
    print(f"MessageType.CLIENT_REGISTRATION = {MessageType.CLIENT_REGISTRATION}")
    print(f"MessageType.CLIENT_REGISTRATION.value = {MessageType.CLIENT_REGISTRATION.value}")
    print(f"ClientType.BOT = {ClientType.BOT}")
    print(f"ClientType.BOT.value = {ClientType.BOT.value}")
    
    # Перевірка порівняння
    print(f"'client_registration' == MessageType.CLIENT_REGISTRATION: {'client_registration' == MessageType.CLIENT_REGISTRATION}")
    print(f"'bot' == ClientType.BOT: {'bot' == ClientType.BOT}")

if __name__ == "__main__":
    test_enum_values()
    success = test_parse_message()
    
    print("\n" + "=" * 50)
    print(f"🏁 Результат тесту: {'✅ УСПІХ' if success else '❌ НЕВДАЧА'}")
    sys.exit(0 if success else 1) 