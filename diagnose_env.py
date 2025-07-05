#!/usr/bin/env python3
"""
Діагностичний скрипт для перевірки середовища запуску TetraCore Hub

Використання:
    python diagnose_env.py
"""

import os
import sys
import socket
from datetime import datetime

def print_section(title):
    """Друкує розділ з заголовком"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_environment():
    """Перевіряє та виводить інформацію про середовище"""

    print_section("ЗАГАЛЬНА ІНФОРМАЦІЯ")
    print(f"Дата/час: {datetime.now()}")
    print(f"Python версія: {sys.version}")
    print(f"Платформа: {sys.platform}")

    try:
        hostname = socket.gethostname()
        print(f"Hostname: {hostname}")
    except:
        print("Hostname: <не вдалося отримати>")

    print_section("ВИЗНАЧЕННЯ СЕРЕДОВИЩА")

    # Heroku змінні
    is_heroku = bool(os.getenv("DYNO"))
    print(f"Heroku DYNO: {os.getenv('DYNO', '<не встановлено>')}")
    print(f"Heroku PORT: {os.getenv('PORT', '<не встановлено>')}")
    print(f"Heroku HOME: {os.getenv('HOME', '<не встановлено>')}")
    print(f"Це Heroku?: {'ТАК' if is_heroku else 'НІ'}")

    print_section("HEROKU APP ІНФОРМАЦІЯ")

    # Різні способи отримання app name
    heroku_app_name = os.getenv("HEROKU_APP_NAME")
    heroku_app_id = os.getenv("HEROKU_APP_ID")
    heroku_slug_id = os.getenv("HEROKU_SLUG_ID")
    heroku_slug_commit = os.getenv("HEROKU_SLUG_COMMIT")

    print(f"HEROKU_APP_NAME: {heroku_app_name or '<не встановлено>'}")
    print(f"HEROKU_APP_ID: {heroku_app_id or '<не встановлено>'}")
    print(f"HEROKU_SLUG_ID: {heroku_slug_id or '<не встановлено>'}")
    print(f"HEROKU_SLUG_COMMIT: {heroku_slug_commit or '<не встановлено>'}")

    # Спроба визначити app name
    detected_name = None
    if heroku_app_name:
        detected_name = heroku_app_name
    elif heroku_app_id:
        detected_name = heroku_app_id
    elif is_heroku and hostname:
        # На Heroku hostname може містити app name
        if '.' in hostname:
            potential_name = hostname.split('.')[0]
            if not potential_name.startswith(('web.', 'worker.')):
                detected_name = potential_name

    print(f"\nВизначене ім'я додатку: {detected_name or '<не вдалося визначити>'}")

    print_section("КОНФІГУРАЦІЯ СЕРЕДОВИЩА")

    print(f"ENVIRONMENT: {os.getenv('ENVIRONMENT', '<не встановлено>')}")
    print(f"DEBUG: {os.getenv('DEBUG', '<не встановлено>')}")
    print(f"LOG_LEVEL: {os.getenv('LOG_LEVEL', '<не встановлено>')}")

    print_section("МЕРЕЖЕВА КОНФІГУРАЦІЯ")

    print(f"HOST: {os.getenv('HOST', '<не встановлено>')}")
    print(f"PORT: {os.getenv('PORT', '<не встановлено>')}")
    print(f"WEBAPP_HOST: {os.getenv('WEBAPP_HOST', '<не встановлено>')}")
    print(f"WEBAPP_PORT: {os.getenv('WEBAPP_PORT', '<не встановлено>')}")

    print_section("REDIS КОНФІГУРАЦІЯ")

    redis_url = os.getenv("REDIS_URL", "<не встановлено>")
    redis_enabled = os.getenv("REDIS_ENABLED", "<не встановлено>")

    print(f"REDIS_ENABLED: {redis_enabled}")
    if redis_url != "<не встановлено>":
        # Приховуємо пароль в URL
        if "@" in redis_url:
            parts = redis_url.split("@")
            if len(parts) > 1:
                redis_url_safe = parts[0].split("//")[0] + "//<credentials>@" + parts[1]
            else:
                redis_url_safe = redis_url
        else:
            redis_url_safe = redis_url
        print(f"REDIS_URL: {redis_url_safe}")
    else:
        print(f"REDIS_URL: {redis_url}")

    print_section("СФОРМОВАНІ URL")

    # Імітуємо логіку з config.py
    if is_heroku:
        if detected_name:
            app_url = f"https://{detected_name}.herokuapp.com"
        else:
            app_url = "https://YOUR-APP-NAME.herokuapp.com"
    else:
        port = os.getenv("PORT", "8000")
        app_url = f"http://localhost:{port}"

    print(f"Backend URL: {app_url}")
    print(f"Frontend URL: {app_url}")
    print(f"Dashboard URL: {app_url}/dashboard")
    print(f"WebSocket URL: {app_url.replace('http', 'ws')}/ws")

    print_section("РЕКОМЕНДАЦІЇ")

    if is_heroku and not detected_name:
        print("⚠️  Ви на Heroku, але не вдалося визначити назву додатку!")
        print("   Рекомендовано встановити змінну HEROKU_APP_NAME:")
        print("   heroku config:set HEROKU_APP_NAME=ваш-додаток")

    if not is_heroku and os.getenv("HOST") == "0.0.0.0":
        print("ℹ️  Локальне середовище з HOST=0.0.0.0")
        print("   Це нормально для розробки, але URL будуть показувати localhost")

    print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    check_environment()
