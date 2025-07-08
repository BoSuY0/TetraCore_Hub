#!/usr/bin/env python3
"""
Setup Script for Heroku Secrets
Скрипт для налаштування секретів для TetraCore Hub на Heroku
"""

import os
import secrets
import string
import base64
import subprocess
import sys
from typing import Dict, Any


def generate_strong_password(length: int = 16) -> str:
    """Генерує міцний пароль з літерами, цифрами та спецсимволами"""
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    
    # Забезпечуємо наявність всіх типів символів
    password = [
        secrets.choice(lowercase),
        secrets.choice(uppercase),
        secrets.choice(digits),
        secrets.choice(special)
    ]
    
    # Заповнюємо решту випадковими символами
    all_chars = lowercase + uppercase + digits + special
    for _ in range(length - 4):
        password.append(secrets.choice(all_chars))
    
    # Перемішуємо пароль
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)


def generate_jwt_secret(length: int = 64) -> str:
    """Генерує безпечний JWT секрет"""
    return secrets.token_urlsafe(length)


def generate_encryption_key() -> str:
    """Генерує ключ для шифрування"""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')


def run_heroku_command(command: list, check_output: bool = False) -> str:
    """Виконує команду Heroku CLI"""
    try:
        if check_output:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        else:
            subprocess.run(command, check=True)
            return ""
    except subprocess.CalledProcessError as e:
        print(f"❌ Помилка виконання команди: {' '.join(command)}")
        print(f"   Вихід: {e.stderr if e.stderr else e.stdout}")
        return ""
    except FileNotFoundError:
        print("❌ Heroku CLI не знайдено. Переконайтесь, що воно встановлене:")
        print("   Інструкції: https://devcenter.heroku.com/articles/heroku-cli")
        sys.exit(1)


def check_heroku_auth():
    """Перевіряє авторизацію в Heroku"""
    try:
        result = subprocess.run(['heroku', 'auth:whoami'], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ Авторизований як: {result.stdout.strip()}")
            return True
        else:
            print("❌ Не авторизований в Heroku")
            print("   Виконайте: heroku login")
            return False
    except FileNotFoundError:
        print("❌ Heroku CLI не знайдено")
        return False


def get_heroku_app_name():
    """Отримує назву Heroku додатку"""
    try:
        result = subprocess.run(['heroku', 'apps:info', '--json'], capture_output=True, text=True)
        if result.returncode == 0:
            import json
            app_info = json.loads(result.stdout)
            return app_info.get('name', 'tetra-core-hub')
    except:
        pass
    
    # Спробуємо отримати з git remote
    try:
        result = subprocess.run(['git', 'remote', 'get-url', 'heroku'], capture_output=True, text=True)
        if result.returncode == 0:
            url = result.stdout.strip()
            if 'heroku.com' in url:
                # Витягуємо назву додатку з URL
                app_name = url.split('/')[-1].replace('.git', '')
                return app_name
    except:
        pass
    
    return input("Введіть назву Heroku додатку: ").strip()


def setup_heroku_secrets():
    """Налаштовує всі необхідні секрети для Heroku"""
    print("🔧 Налаштування секретів для TetraCore Hub на Heroku")
    print("="*60)
    
    # Перевірка Heroku CLI
    if not check_heroku_auth():
        sys.exit(1)
    
    # Отримання назви додатку
    app_name = get_heroku_app_name()
    if not app_name:
        print("❌ Не вдалося визначити назву Heroku додатку")
        sys.exit(1)
    
    print(f"📱 Додаток: {app_name}")
    print()
    
    # Генерація секретів
    print("🔐 Генерація секретів...")
    
    secrets_config = {
        'JWT_SECRET_KEY': generate_jwt_secret(),
        'JWT_REFRESH_SECRET': generate_jwt_secret(),
        'ADMIN_USERNAME': 'admin',
        'ADMIN_PASSWORD': generate_strong_password(16),
        'ENCRYPTION_KEY': generate_encryption_key(),
        'ENVIRONMENT': 'production',
        'DEBUG': 'false',
        'LOG_LEVEL': 'INFO',
        'REQUIRE_AUTHENTICATION': 'true',
        'REDIS_ENABLED': 'true'
    }
    
    # Показуємо згенеровані секрети
    print("🔑 Згенеровані секрети:")
    for key, value in secrets_config.items():
        if 'PASSWORD' in key or 'SECRET' in key or 'KEY' in key:
            print(f"   {key}: {value[:10]}...")
        else:
            print(f"   {key}: {value}")
    
    print()
    
    # Запитуємо підтвердження
    confirm = input("Встановити ці секрети на Heroku? (y/N): ").lower().strip()
    if confirm not in ['y', 'yes']:
        print("❌ Скасовано")
        sys.exit(0)
    
    # Встановлення секретів
    print("📤 Встановлення секретів на Heroku...")
    
    success_count = 0
    for key, value in secrets_config.items():
        print(f"   Встановлюю {key}...")
        result = run_heroku_command([
            'heroku', 'config:set', f'{key}={value}',
            '--app', app_name
        ])
        if result is not None:
            success_count += 1
        else:
            print(f"   ❌ Помилка встановлення {key}")
    
    print()
    
    if success_count == len(secrets_config):
        print("✅ Всі секрети успішно встановлені!")
        
        # Збереження інформації для адміністратора
        save_admin_credentials(secrets_config['ADMIN_USERNAME'], secrets_config['ADMIN_PASSWORD'])
        
        # Перевірка статусу
        print("🔍 Перевірка налаштувань...")
        run_heroku_command(['heroku', 'config', '--app', app_name], check_output=False)
        
        print()
        print("🎉 Налаштування завершено!")
        print(f"🌐 Ваш додаток: https://{app_name}.herokuapp.com")
        print("📝 Дані для входу збережені в admin_credentials.txt")
        
    else:
        print(f"⚠️  Встановлено {success_count}/{len(secrets_config)} секретів")
        print("   Перевірте помилки вище")


def save_admin_credentials(username: str, password: str):
    """Зберігає облікові дані адміністратора"""
    with open('admin_credentials.txt', 'w', encoding='utf-8') as f:
        f.write("TetraCore Hub - Облікові дані адміністратора\n")
        f.write("="*50 + "\n\n")
        f.write(f"Користувач: {username}\n")
        f.write(f"Пароль: {password}\n\n")
        f.write("⚠️  ВАЖЛИВО: Зберігайте ці дані в безпечному місці!\n")
        f.write("⚠️  Не додавайте цей файл до git репозиторію!\n")
    
    print("💾 Дані адміністратора збережені в admin_credentials.txt")


def main():
    """Головна функція"""
    if len(sys.argv) > 1 and sys.argv[1] == '--help':
        print("Використання: python setup_heroku_secrets.py")
        print("Налаштовує всі необхідні секрети для TetraCore Hub на Heroku")
        return
    
    setup_heroku_secrets()


if __name__ == '__main__':
    main() 