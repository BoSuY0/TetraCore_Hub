#!/usr/bin/env python3
"""
Скрипт для тестування всіх режимів hub_launcher.py
Автоматично тестує dev, fast, prod та build режими
"""

import os
import sys
import time
import signal
import subprocess
import threading
import requests
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Додаємо project root до Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

class Colors:
    """ANSI кольори для виводу"""
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

class LauncherTester:
    """Тестер для hub_launcher.py"""

    def __init__(self, verbose: bool = False):
        self.project_root = project_root
        self.launcher_path = self.project_root / "hub_launcher.py"
        self.verbose = verbose
        self.test_results = {}
        self.current_process = None

        # Перевірка що лаунчер існує
        if not self.launcher_path.exists():
            self.error(f"Лаунчер не знайдено: {self.launcher_path}")
            sys.exit(1)

    def log(self, message: str, color: str = Colors.WHITE):
        """Виводить повідомлення з кольором"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"{color}[{timestamp}] {message}{Colors.END}")

    def success(self, message: str):
        """Виводить успішне повідомлення"""
        self.log(f"✅ {message}", Colors.GREEN)

    def error(self, message: str):
        """Виводить помилку"""
        self.log(f"❌ {message}", Colors.RED)

    def warning(self, message: str):
        """Виводить попередження"""
        self.log(f"⚠️ {message}", Colors.YELLOW)

    def info(self, message: str):
        """Виводить інформацію"""
        self.log(f"ℹ️ {message}", Colors.CYAN)

    def print_header(self, title: str):
        """Виводить заголовок секції"""
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}{title:^60}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

    def run_command(self, cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
        """Виконує команду з таймаутом"""
        try:
            if self.verbose:
                self.info(f"Виконання: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.project_root
            )

            self.current_process = process

            try:
                stdout, stderr = process.communicate(timeout=timeout)
                return process.returncode, stdout, stderr
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                return -1, stdout, f"Timeout after {timeout}s\n{stderr}"

        except Exception as e:
            return -1, "", str(e)
        finally:
            self.current_process = None

    def check_server_health(self, url: str = "http://localhost:8000/health", timeout: int = 30) -> bool:
        """Перевіряє доступність сервера"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)

        return False

    def kill_server_processes(self):
        """Вбиває всі процеси лаунчера"""
        try:
            subprocess.run(["pkill", "-f", "hub_launcher.py"], capture_output=True)
            subprocess.run(["pkill", "-f", "start_hub.py"], capture_output=True)
            time.sleep(2)
        except:
            pass

    def test_build_mode(self) -> bool:
        """Тестує режим збірки"""
        self.info("Тестування build режиму...")

        # Очищуємо попередню збірку
        build_dir = self.project_root / "frontend" / "build"
        if build_dir.exists():
            import shutil
            shutil.rmtree(build_dir)

        # Запускаємо збірку
        returncode, stdout, stderr = self.run_command([
            "python", "hub_launcher.py", "build"
        ], timeout=300)  # 5 хвилин на збірку

        if returncode == 0:
            # Перевіряємо що збірка створена
            if build_dir.exists() and (build_dir / "index.html").exists():
                self.success("Build режим працює")
                return True
            else:
                self.error("Build режим не створив необхідні файли")
                return False
        else:
            self.error(f"Build режим завершився з помилкою: {stderr}")
            return False

    def test_fast_mode(self) -> bool:
        """Тестує fast режим"""
        self.info("Тестування fast режиму...")

        # Запускаємо в background
        process = subprocess.Popen([
            "python", "hub_launcher.py", "fast"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.project_root)

        self.current_process = process

        try:
            # Чекаємо запуск сервера
            time.sleep(5)

            if self.check_server_health():
                self.success("Fast режим запущено успішно")
                return True
            else:
                self.error("Fast режим не запустив сервер")
                return False

        finally:
            # Завершуємо процес
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.kill_server_processes()

    def test_prod_mode(self) -> bool:
        """Тестує production режим"""
        self.info("Тестування production режиму...")

        # Запускаємо в background
        process = subprocess.Popen([
            "python", "hub_launcher.py", "prod"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.project_root)

        self.current_process = process

        try:
            # Чекаємо запуск сервера (довше для production)
            time.sleep(10)

            if self.check_server_health():
                self.success("Production режим запущено успішно")
                return True
            else:
                self.error("Production режим не запустив сервер")
                return False

        finally:
            # Завершуємо процес
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.kill_server_processes()

    def test_dev_mode(self) -> bool:
        """Тестує development режим"""
        self.info("Тестування development режиму...")

        # Запускаємо в background
        process = subprocess.Popen([
            "python", "hub_launcher.py", "dev"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.project_root)

        self.current_process = process

        try:
            # Чекаємо запуск сервера
            time.sleep(8)

            if self.check_server_health():
                self.success("Development режим запущено успішно")
                return True
            else:
                self.error("Development режим не запустив сервер")
                return False

        finally:
            # Завершуємо процес
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            self.kill_server_processes()

    def test_help_and_version(self) -> bool:
        """Тестує допомогу та версію"""
        self.info("Тестування --help...")

        returncode, stdout, stderr = self.run_command([
            "python", "hub_launcher.py", "--help"
        ], timeout=10)

        if returncode == 0 and "usage:" in stdout:
            self.success("--help працює")
            return True
        else:
            self.error("--help не працює")
            return False

    def check_dependencies(self) -> bool:
        """Перевіряє наявність залежностей"""
        self.info("Перевірка залежностей...")

        # Перевіряємо Python модулі
        required_modules = ["fastapi", "uvicorn", "redis", "structlog"]
        missing_modules = []

        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                missing_modules.append(module)

        if missing_modules:
            self.error(f"Відсутні модулі: {', '.join(missing_modules)}")
            return False

        # Перевіряємо Node.js
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True)
            if result.returncode == 0:
                self.success(f"Node.js знайдено: {result.stdout.strip()}")
            else:
                self.warning("Node.js не знайдено")
        except FileNotFoundError:
            self.warning("Node.js не знайдено")

        self.success("Основні залежності перевірено")
        return True

    def run_all_tests(self) -> Dict[str, bool]:
        """Запускає всі тести"""
        self.print_header("🧪 ТЕСТУВАННЯ HUB_LAUNCHER.PY")

        # Початкова перевірка
        if not self.check_dependencies():
            self.error("Не вдалося перевірити залежності")
            return {}

        # Очищуємо процеси
        self.kill_server_processes()

        tests = [
            ("help", self.test_help_and_version),
            ("build", self.test_build_mode),
            ("fast", self.test_fast_mode),
            ("prod", self.test_prod_mode),
            ("dev", self.test_dev_mode),
        ]

        results = {}

        for test_name, test_func in tests:
            self.print_header(f"🧪 ТЕСТ: {test_name.upper()}")

            try:
                results[test_name] = test_func()
            except KeyboardInterrupt:
                self.warning("Тест перервано користувачем")
                results[test_name] = False
                break
            except Exception as e:
                self.error(f"Помилка в тесті {test_name}: {e}")
                results[test_name] = False

            # Пауза між тестами
            if test_name != "help":
                time.sleep(3)

        return results

    def print_summary(self, results: Dict[str, bool]):
        """Виводить підсумок тестування"""
        self.print_header("📊 ПІДСУМОК ТЕСТУВАННЯ")

        passed = sum(results.values())
        total = len(results)

        for test_name, result in results.items():
            status = "✅ ПРОЙДЕНО" if result else "❌ ПРОВАЛЕНО"
            color = Colors.GREEN if result else Colors.RED
            self.log(f"{test_name.upper():<15} {status}", color)

        print(f"\n{Colors.BOLD}Результат: {passed}/{total} тестів пройдено{Colors.END}")

        if passed == total:
            self.success("🎉 Всі тести пройшли успішно!")
            return True
        else:
            self.error(f"💥 {total - passed} тестів провалилися")
            return False

    def cleanup(self):
        """Очищує ресурси"""
        if self.current_process:
            try:
                self.current_process.terminate()
                self.current_process.wait(timeout=5)
            except:
                try:
                    self.current_process.kill()
                except:
                    pass

        self.kill_server_processes()

def signal_handler(signum, frame, tester):
    """Обробка сигналів"""
    print(f"\n{Colors.YELLOW}Отримано сигнал {signum}, завершення тестування...{Colors.END}")
    tester.cleanup()
    sys.exit(0)

def main():
    """Головна функція"""
    import argparse

    parser = argparse.ArgumentParser(description="Тестер для hub_launcher.py")
    parser.add_argument("--verbose", "-v", action="store_true", help="Детальні логи")
    parser.add_argument("--test", "-t", choices=["help", "build", "fast", "prod", "dev"],
                       help="Запустити конкретний тест")

    args = parser.parse_args()

    tester = LauncherTester(verbose=args.verbose)

    # Встановлюємо обробку сигналів
    signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, tester))
    signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s, f, tester))

    try:
        if args.test:
            # Запускаємо конкретний тест
            test_methods = {
                "help": tester.test_help_and_version,
                "build": tester.test_build_mode,
                "fast": tester.test_fast_mode,
                "prod": tester.test_prod_mode,
                "dev": tester.test_dev_mode,
            }

            if args.test in test_methods:
                result = test_methods[args.test]()
                sys.exit(0 if result else 1)
        else:
            # Запускаємо всі тести
            results = tester.run_all_tests()
            success = tester.print_summary(results)
            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Тестування перервано користувачем{Colors.END}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Критична помилка: {e}{Colors.END}")
        sys.exit(1)
    finally:
        tester.cleanup()

if __name__ == "__main__":
    main()
