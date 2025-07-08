#!/usr/bin/env python3
"""
Швидкий тест для hub_launcher.py
Перевіряє основні функції без запуску серверів
"""

import os
import sys
import subprocess
import time
from pathlib import Path

# Кольори для виводу
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'

def log(message, color=Colors.BLUE):
    print(f"{color}{message}{Colors.END}")

def success(message):
    log(f"✅ {message}", Colors.GREEN)

def error(message):
    log(f"❌ {message}", Colors.RED)

def warning(message):
    log(f"⚠️ {message}", Colors.YELLOW)

def test_launcher_exists():
    """Перевіряє що лаунчер існує"""
    launcher_path = Path("hub_launcher.py")
    if launcher_path.exists():
        success("hub_launcher.py знайдено")
        return True
    else:
        error("hub_launcher.py не знайдено")
        return False

def test_help():
    """Тестує --help"""
    try:
        result = subprocess.run([
            sys.executable, "hub_launcher.py", "--help"
        ], capture_output=True, text=True, timeout=10)

        if result.returncode == 0 and "usage:" in result.stdout:
            success("--help працює")
            return True
        else:
            error("--help не працює")
            return False
    except Exception as e:
        error(f"Помилка тесту --help: {e}")
        return False

def test_syntax():
    """Перевіряє синтаксис файлу"""
    try:
        result = subprocess.run([
            sys.executable, "-m", "py_compile", "hub_launcher.py"
        ], capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            success("Синтаксис правильний")
            return True
        else:
            error(f"Синтаксична помилка: {result.stderr}")
            return False
    except Exception as e:
        error(f"Помилка перевірки синтаксису: {e}")
        return False

def test_imports():
    """Перевіряє імпорти"""
    try:
        result = subprocess.run([
            sys.executable, "-c", "import hub_launcher; print('OK')"
        ], capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            success("Імпорти працюють")
            return True
        else:
            error(f"Помилка імпорту: {result.stderr}")
            return False
    except Exception as e:
        error(f"Помилка тесту імпорту: {e}")
        return False

def test_modes():
    """Перевіряє що всі режими розпізнаються"""
    modes = ["dev", "fast", "prod", "build"]

    for mode in modes:
        try:
            # Запускаємо з --help щоб не стартувати сервер
            result = subprocess.run([
                sys.executable, "hub_launcher.py", mode, "--help"
            ], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                success(f"Режим {mode} розпізнається")
            else:
                error(f"Режим {mode} не розпізнається")
                return False
        except Exception as e:
            error(f"Помилка тесту режиму {mode}: {e}")
            return False

    return True

def test_old_launchers():
    """Перевіряє що старі лаунчери працюють як обгортки"""
    old_launchers = ["start_hub.py", "secure_launcher.py"]
    all_passed = True

    for launcher in old_launchers:
        if Path(launcher).exists():
            try:
                result = subprocess.run([
                    sys.executable, launcher, "--help"
                ], capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    success(f"{launcher} працює як обгортка")
                else:
                    warning(f"{launcher} може мати проблеми")
                    all_passed = False
            except Exception as e:
                warning(f"Помилка тесту {launcher}: {e}")
                all_passed = False
        else:
            warning(f"{launcher} не знайдено")
            all_passed = False

    return all_passed

def main():
    """Головна функція тестування"""
    log("🧪 Швидкий тест hub_launcher.py")
    log("=" * 50)

    tests = [
        ("Існування файлу", test_launcher_exists),
        ("Синтаксис", test_syntax),
        ("Імпорти", test_imports),
        ("Help", test_help),
        ("Режими", test_modes),
        ("Старі лаунчери", test_old_launchers),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        log(f"\n🔍 Тест: {test_name}")
        try:
            result = test_func()
            if result:
                passed += 1
        except Exception as e:
            error(f"Критична помилка в тесті {test_name}: {e}")

    # Підсумок
    log(f"\n{'='*50}")
    log(f"📊 Результат: {passed}/{total} тестів пройдено")

    if passed == total:
        success("🎉 Всі тести пройшли!")
        return True
    else:
        error(f"💥 {total - passed} тестів не пройшли")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
