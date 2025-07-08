#!/usr/bin/env python3
"""
TetraCore StreamHub - Unified Secure Launcher

Об'єднує функціональність start_hub.py та secure_launcher.py.
Підтримує різні режими запуску з автоматичним визначенням середовища
та додатковими заходами безпеки.
"""

import os
import sys
import json
import time
import signal
import asyncio
import subprocess
import logging
import shutil
import shlex
import secrets
import hashlib
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional, Tuple

# Додавання поточної директорії до Python path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

import structlog
import uvicorn
from fastapi import FastAPI

# Константи безпеки
MAX_PATH_LENGTH = 4096
MAX_COMMAND_LENGTH = 8192
ALLOWED_NODE_COMMANDS = ['node', 'npm', 'npx']
ALLOWED_NPM_SCRIPTS = ['install', 'ci', 'build', 'start', 'test']
DEFAULT_TIMEOUT = 300  # 5 хвилин
MAX_TIMEOUT = 3600  # 1 година
SAFE_ENV_VARS = [
    'PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'NODE_ENV',
    'NPM_CONFIG_LOGLEVEL', 'CI', 'FORCE_COLOR'
]


class SecurityError(Exception):
    """Помилка безпеки при валідації"""
    pass


class SecurePath:
    """Безпечна робота з шляхами"""

    def __init__(self, base_path: Path):
        self.base_path = base_path.absolute()

    def validate_path(self, path: str) -> Path:
        """Валідує та нормалізує шлях"""
        if len(path) > MAX_PATH_LENGTH:
            raise SecurityError(f"Шлях занадто довгий: {len(path)} > {MAX_PATH_LENGTH}")

        # Конвертуємо в Path об'єкт
        try:
            path_obj = Path(path).resolve()
        except Exception as e:
            raise SecurityError(f"Некоректний шлях: {e}")

        # Перевіряємо, чи шлях в межах base_path
        try:
            path_obj.relative_to(self.base_path)
        except ValueError:
            raise SecurityError(f"Шлях за межами проекту: {path_obj}")

        # Перевіряємо на небезпечні компоненти
        parts = path_obj.parts
        dangerous_parts = ['..', '.git', '__pycache__', 'node_modules']
        for part in parts:
            if part in dangerous_parts or part.startswith('.'):
                raise SecurityError(f"Небезпечний компонент шляху: {part}")

        return path_obj


class SecureCommand:
    """Безпечне виконання команд"""

    def __init__(self):
        self.allowed_commands = set(ALLOWED_NODE_COMMANDS)

    def validate_command(self, command: List[str]) -> List[str]:
        """Валідує команду перед виконанням"""
        if not command:
            raise SecurityError("Порожня команда")

        # Перевірка довжини команди
        cmd_str = ' '.join(command)
        if len(cmd_str) > MAX_COMMAND_LENGTH:
            raise SecurityError(f"Команда занадто довга: {len(cmd_str)} > {MAX_COMMAND_LENGTH}")

        # Перевірка дозволених команд
        base_cmd = os.path.basename(command[0])
        if base_cmd not in self.allowed_commands:
            raise SecurityError(f"Недозволена команда: {base_cmd}")

        # Валідація npm scripts
        if base_cmd == 'npm' and len(command) > 1:
            if command[1] not in ['run'] + ALLOWED_NPM_SCRIPTS:
                raise SecurityError(f"Недозволений npm script: {command[1]}")

        return command

    def create_safe_env(self) -> Dict[str, str]:
        """Створює безпечне оточення для виконання команд"""
        env = {}

        # Копіюємо тільки безпечні змінні оточення
        for var in SAFE_ENV_VARS:
            if var in os.environ:
                env[var] = os.environ[var]

        # Додаємо безпечні значення за замовчуванням
        env.update({
            'NODE_ENV': os.getenv('NODE_ENV', 'production'),
            'NPM_CONFIG_LOGLEVEL': 'warn',
            'CI': 'true',
            'FORCE_COLOR': '0'
        })

        # Видаляємо потенційно небезпечні змінні
        dangerous_vars = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH']
        for var in dangerous_vars:
            env.pop(var, None)

        return env

    async def run_safe(self, command: List[str], cwd: Path,
                      timeout: int = DEFAULT_TIMEOUT) -> Tuple[int, str, str]:
        """Безпечне виконання команди"""
        # Валідація
        command = self.validate_command(command)

        if timeout > MAX_TIMEOUT:
            timeout = MAX_TIMEOUT

        # Створюємо безпечне оточення
        env = self.create_safe_env()

        # Виконуємо команду
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=self._limit_resources if sys.platform != 'win32' else None
            )

            # Очікуємо завершення з таймаутом
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise SecurityError(f"Команда перевищила таймаут: {timeout}s")

            return (
                process.returncode,
                stdout.decode('utf-8', errors='replace'),
                stderr.decode('utf-8', errors='replace')
            )

        except Exception as e:
            if isinstance(e, SecurityError):
                raise
            raise SecurityError(f"Помилка виконання команди: {e}")

    def _limit_resources(self):
        """Обмеження ресурсів процесу (тільки для Unix)"""
        try:
            import resource

            # Обмеження CPU часу
            resource.setrlimit(resource.RLIMIT_CPU, (300, 300))

            # Обмеження пам'яті (1GB)
            resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))

            # Обмеження кількості процесів
            resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))

        except Exception:
            pass  # Ігноруємо помилки на системах без resource


class StreamHubLauncher:
    """Універсальний безпечний лаунчер для StreamHub"""

    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        self.frontend_dir = self.project_root / "frontend"
        self.static_dir = self.project_root / "static"
        self.server_process = None
        self.frontend_process = None

        # Ініціалізація безпекових компонентів
        self.secure_path = SecurePath(self.project_root)
        self.secure_cmd = SecureCommand()

        # Налаштування логування
        self.logger = structlog.get_logger()

    def print_banner(self, mode="dev"):
        """Виводить банер запуску"""
        from config import get_settings
        settings = get_settings()

        backend_url = settings.get_backend_url()
        frontend_url = settings.get_frontend_url()
        dashboard_url = settings.get_dashboard_url()
        websocket_url = settings.get_websocket_url()

        banner = f"""
╔══════════════════════════════════════════════════════════════╗
║               🌊 TetraCore StreamHub v2.0                      ║
║                  Unified Secure Launcher                       ║
╠══════════════════════════════════════════════════════════════╣
║  Mode:      {mode.upper():<48}║
║  Environment: {os.getenv('ENVIRONMENT', 'development'):<46}║
╠══════════════════════════════════════════════════════════════╣
║  🔧 Backend:    {backend_url:<44}║
║  🎨 Frontend:   {frontend_url:<44}║
║  📊 Dashboard:  {dashboard_url:<44}║
║  🔌 WebSocket:  {websocket_url:<44}║
╠══════════════════════════════════════════════════════════════╣
║  📁 Project:    {str(self.project_root):<44}║
║  ⏰ Started:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<44}║
╚══════════════════════════════════════════════════════════════╝
        """
        print(banner)

        if mode == "dev":
            print("🔧 Development режим:")
            print("   • Hot reload активний")
            print("   • Debug логування увімкнено")
            print("   • Frontend dev server на :3000")
            print("   • Backend API на :8000")
            print("   • Один процес для всього\n")
        elif mode == "fast":
            print("⚡ Fast режим:")
            print("   • Тільки backend")
            print("   • Використовує готову збірку frontend")
            print("   • Швидкий старт\n")
        elif mode == "prod":
            print("🚀 Production режим:")
            print("   • Оптимізована збірка")
            print("   • Статичні файли з /static")
            print("   • Production налаштування\n")

    def setup_logging(self, verbose=False):
        """Налаштування системи логування"""
        log_dir = self.project_root / "logs"
        log_dir.mkdir(exist_ok=True)

        # Видаляємо всі існуючі handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        # Встановлюємо базовий рівень логування
        if verbose:
            log_level = logging.DEBUG
            uvicorn_log_level = "debug"
        else:
            log_level = logging.WARNING
            uvicorn_log_level = "warning"

        # Налаштування Uvicorn логерів
        uvicorn_loggers = [
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "uvicorn.asgi"
        ]

        for logger_name in uvicorn_loggers:
            logger = logging.getLogger(logger_name)
            logger.setLevel(log_level)
            logger.handlers = []
            logger.propagate = False

        # Налаштування structlog
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        return uvicorn_log_level

    def _check_if_frontend_needs_rebuild(self):
        """Перевіряє чи потрібна перебудова frontend"""
        # Перевіряємо наявність build директорії
        build_dir = self.frontend_dir / "build"
        if not build_dir.exists():
            return True

        # Перевіряємо наявність основних файлів
        required_files = ["index.html", "static/js", "static/css"]
        for file_path in required_files:
            if not (build_dir / file_path).exists():
                return True

        # Перевіряємо час модифікації src файлів
        src_dir = self.frontend_dir / "src"
        if src_dir.exists():
            try:
                # Знаходимо найновіший src файл
                src_files = list(src_dir.rglob("*.js")) + list(src_dir.rglob("*.jsx")) + \
                           list(src_dir.rglob("*.ts")) + list(src_dir.rglob("*.tsx"))

                if src_files:
                    newest_src = max(src_files, key=lambda p: p.stat().st_mtime)
                    src_time = newest_src.stat().st_mtime

                    # Знаходимо найстаріший build файл
                    build_files = list(build_dir.rglob("*.js")) + list(build_dir.rglob("*.css"))
                    if build_files:
                        oldest_build = min(build_files, key=lambda p: p.stat().st_mtime)
                        build_time = oldest_build.stat().st_mtime

                        # Якщо src новіший за build - потрібна перебудова
                        if src_time > build_time:
                            return True
            except Exception as e:
                self.logger.warning(f"Помилка перевірки часу файлів: {e}")
                return True

        return False

    def _copy_build_files(self):
        """Копіює файли збірки frontend в static директорію"""
        build_dir = self.frontend_dir / "build"

        if not build_dir.exists():
            self.logger.warning("Build директорія не існує")
            return False

        try:
            # Створюємо static директорію якщо не існує
            self.static_dir.mkdir(exist_ok=True)

            # Копіюємо всі файли з build в static
            for item in build_dir.iterdir():
                src = build_dir / item.name
                dst = self.static_dir / item.name

                if src.is_dir():
                    # Видаляємо існуючу директорію
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

            self.logger.info("Frontend файли скопійовано в static")
            return True

        except Exception as e:
            self.logger.error(f"Помилка копіювання файлів: {e}")
            return False

    async def check_node_available(self):
        """Перевіряє наявність Node.js з безпековими обмеженнями"""
        try:
            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                ["node", "--version"],
                cwd=self.project_root,
                timeout=10
            )

            if returncode == 0:
                version = stdout.strip()
                self.logger.info(f"Node.js знайдено: {version}")
                return True
            else:
                self.logger.error(f"Node.js помилка: {stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Node.js не знайдено: {e}")
            return False

    async def install_dependencies(self):
        """Встановлює залежності з безпековими обмеженнями"""
        package_json = self.frontend_dir / "package.json"
        if not package_json.exists():
            self.logger.warning("package.json не знайдено, пропускаємо встановлення залежностей")
            return True

        node_modules = self.frontend_dir / "node_modules"
        package_lock = self.frontend_dir / "package-lock.json"

        # Перевіряємо чи потрібно встановлювати залежності
        if node_modules.exists() and package_lock.exists():
            # Перевіряємо час модифікації
            if package_lock.stat().st_mtime < package_json.stat().st_mtime:
                self.logger.info("package.json новіший за package-lock.json, оновлюємо залежності")
            else:
                self.logger.info("Залежності вже встановлені")
                return True

        print("📦 Встановлення залежностей...")
        try:
            # Валідуємо шлях
            frontend_path = self.secure_path.validate_path(str(self.frontend_dir))

            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                ["npm", "ci", "--prefer-offline", "--no-audit"],
                cwd=frontend_path,
                timeout=300
            )

            if returncode == 0:
                print("✅ Залежності встановлено")
                return True
            else:
                self.logger.error(f"npm ci failed: {stderr}")
                # Спробуємо npm install
                returncode, stdout, stderr = await self.secure_cmd.run_safe(
                    ["npm", "install", "--no-audit"],
                    cwd=frontend_path,
                    timeout=300
                )

                if returncode == 0:
                    print("✅ Залежності встановлено через npm install")
                    return True
                else:
                    print(f"❌ Помилка встановлення: {stderr}")
                    return False

        except Exception as e:
            print(f"❌ Помилка встановлення залежностей: {e}")
            return False

    async def build_frontend(self, force=False):
        """Будує frontend з безпековими обмеженнями"""
        if not await self.check_node_available():
            self.logger.error("Node.js не встановлено")
            return False

        # Перевіряємо чи потрібна збірка
        if not force and not self._check_if_frontend_needs_rebuild():
            print("✅ Frontend вже зібрано, використовуємо існуючу збірку")
            return self._copy_build_files()

        # Встановлюємо залежності якщо потрібно
        if not await self.install_dependencies():
            return False

        print("🔨 Збірка frontend...")
        try:
            # Валідуємо шлях
            frontend_path = self.secure_path.validate_path(str(self.frontend_dir))

            # Встановлюємо змінні оточення для збірки
            env = self.secure_cmd.create_safe_env()
            env.update({
                'CI': 'false',  # Вимикаємо CI режим для локальної збірки
                'GENERATE_SOURCEMAP': 'false',  # Вимикаємо source maps для production
                'NODE_ENV': 'production'
            })

            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                ["npm", "run", "build"],
                cwd=frontend_path,
                timeout=600  # 10 хвилин для збірки
            )

            if returncode == 0:
                print("✅ Frontend зібрано успішно")
                # Копіюємо файли в static
                return self._copy_build_files()
            else:
                print(f"❌ Помилка збірки: {stderr}")
                return False

        except Exception as e:
            print(f"❌ Помилка збірки frontend: {e}")
            return False

    async def start_development_server(self):
        """Запускає development сервер frontend з безпековими обмеженнями"""
        if not await self.check_node_available():
            return None

        if not await self.install_dependencies():
            return None

        print("🚀 Запуск frontend development server...")

        try:
            # Валідуємо шлях
            frontend_path = self.secure_path.validate_path(str(self.frontend_dir))

            # Запускаємо процес без обмеження часу для dev server
            process = await asyncio.create_subprocess_exec(
                "npm", "start",
                cwd=str(frontend_path),
                env=self.secure_cmd.create_safe_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            self.frontend_process = process

            # Чекаємо поки сервер запуститься
            await asyncio.sleep(3)

            if process.returncode is None:
                print("✅ Frontend development server запущено на http://localhost:3000")
                return process
            else:
                stdout, stderr = await process.communicate()
                print(f"❌ Помилка запуску frontend: {stderr.decode()}")
                return None

        except Exception as e:
            print(f"❌ Помилка запуску development server: {e}")
            return None

    def setup_environment(self):
        """Налаштування змінних оточення"""
        env_file = self.project_root / ".env"

        # Базові налаштування
        default_env = {
            "ENVIRONMENT": "development",
            "HOST": "0.0.0.0",
            "PORT": os.environ.get("PORT", "8000"),
            "FRONTEND_URL": "http://localhost:3000",
            "BACKEND_URL": "http://localhost:8000",
            "REDIS_URL": "redis://localhost:6379/0",
            "SECRET_KEY": secrets.token_urlsafe(32),
            "WORKERS": "1",
            "LOG_LEVEL": "INFO",
            "ENABLE_CORS": "true"
        }

        # Завантажуємо існуючі налаштування
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)

        # Встановлюємо значення за замовчуванням
        for key, value in default_env.items():
            if key not in os.environ:
                os.environ[key] = value

        # Валідація критичних параметрів
        self._validate_environment()

    def _validate_environment(self):
        """Валідація змінних оточення"""
        required_vars = ["SECRET_KEY", "REDIS_URL"]

        for var in required_vars:
            if not os.environ.get(var):
                raise SecurityError(f"Відсутня обов'язкова змінна оточення: {var}")

        # Перевірка SECRET_KEY
        secret_key = os.environ.get("SECRET_KEY", "")
        if len(secret_key) < 32:
            raise SecurityError("SECRET_KEY занадто короткий (мінімум 32 символи)")

        # Перевірка на дефолтні значення
        if secret_key == "your-secret-key-here":
            raise SecurityError("Використовується дефолтний SECRET_KEY!")

    def create_app(self):
        """Створює FastAPI додаток"""
        from core.hub import StreamHub

        # Створюємо StreamHub
        hub = StreamHub()

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # Startup
            print("🚀 Запуск StreamHub...")
            await hub.initialize()
            app.state.hub = hub

            yield

            # Shutdown
            print("🛑 Зупинка StreamHub...")
            await hub.shutdown()

        # Отримуємо FastAPI додаток від StreamHub
        app = hub.get_app()

        # Встановлюємо lifespan
        # Для новіших версій FastAPI використовуємо router.lifespan_context
        if hasattr(app.router, 'lifespan_context'):
            app.router.lifespan_context = lifespan
        else:
            # Для старіших версій
            app = FastAPI(lifespan=lifespan)
            # Копіюємо роути з оригінального app
            app.mount("/", hub.get_app())

        return app

    async def run_backend(self, host="0.0.0.0", port=None, reload=False, log_level="info"):
        """Запускає backend сервер"""
        # Використовуємо PORT з оточення для Heroku
        if port is None:
            port = int(os.environ.get("PORT", "8000"))

        try:
            app = self.create_app()

            # Налаштування для роботи за проксі (Heroku)
            config = uvicorn.Config(
                app,
                host=host,
                port=port,
                reload=reload,
                log_level=log_level,
                access_log=False,
                use_colors=True,
                loop="asyncio",
                forwarded_allow_ips="*",  # Дозволяємо всі проксі для Heroku
                proxy_headers=True,  # Використовуємо заголовки проксі
                server_header=False  # Приховуємо заголовок сервера
            )

            server = uvicorn.Server(config)
            self.server_process = server
            await server.serve()

        except Exception as e:
            self.logger.error(f"Помилка запуску backend: {e}")
            raise

    async def run_dev_mode(self, verbose=False):
        """Development режим - один сервер з hot reload"""
        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "development"

        # Логування
        log_level = self.setup_logging(verbose)

        # Виводимо банер
        self.print_banner("dev")

        try:
            # Запускаємо backend з hot reload
            print("\n🔧 Запуск в development режимі...\n")

            # Запускаємо frontend dev server
            frontend_process = await self.start_development_server()
            if frontend_process:
                self.frontend_process = frontend_process

            # Development режим - сервуємо frontend через proxy
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=True,
                log_level=log_level
            )

        except KeyboardInterrupt:
            print("\n👋 Зупинено користувачем")
        finally:
            await self.cleanup()

    async def run_fast_mode(self, verbose=False):
        """Fast режим - швидкий запуск тільки backend"""
        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "production"

        # Логування
        log_level = self.setup_logging(verbose)

        # Виводимо банер
        self.print_banner("fast")

        # Копіюємо існуючу збірку якщо є
        self._copy_build_files()

        try:
            # Запускаємо тільки backend
            print("\n⚡ Швидкий запуск backend...\n")
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=False,
                log_level=log_level
            )

        finally:
            await self.cleanup()

    async def run_prod_mode(self, force_build=False, verbose=False):
        """Production режим - повна збірка та оптимізація"""
        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "production"
        os.environ["NODE_ENV"] = "production"

        # Логування
        log_level = self.setup_logging(verbose)

        # Виводимо банер
        self.print_banner("prod")

        # Збірка frontend
        if not await self.build_frontend(force=force_build):
            print("❌ Не вдалося зібрати frontend")
            return

        try:
            # Запускаємо production сервер
            print("\n🚀 Запуск production серверу...\n")
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=False,
                log_level=log_level
            )

        finally:
            await self.cleanup()

    async def cleanup(self):
        """Очищення ресурсів"""
        self.logger.info("🧹 Очищення ресурсів...")

        if self.frontend_process:
            try:
                self.logger.debug("Завершення frontend процесу...")
                self.frontend_process.terminate()
                await self.frontend_process.wait()
                self.logger.debug("Frontend процес завершено")
            except ProcessLookupError:
                # Процес вже завершений
                self.logger.debug("Frontend процес вже був завершений")

        if self.server_process:
            self.logger.debug("Завершення backend процесу...")
            self.server_process.should_exit = True

        self.logger.info("✅ Очищення завершено")

    def _signal_handler(self, signum, frame):
        """Обробка сигналів"""
        print(f"\n🛑 Отримано сигнал {signum}, зупиняємо...")
        asyncio.create_task(self.cleanup())
        sys.exit(0)


def main():
    """Головна функція"""
    import argparse

    parser = argparse.ArgumentParser(
        description="TetraCore StreamHub Unified Secure Launcher",
        epilog="""
Приклади використання:
  python hub_launcher.py              # Запуск dev режиму (за замовчуванням)
  python hub_launcher.py dev          # Розробка з hot reload
  python hub_launcher.py fast         # Швидкий запуск backend
  python hub_launcher.py prod         # Production сервер
  python hub_launcher.py build        # Збірка frontend
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", nargs="?", default="dev",
                       choices=["dev", "fast", "prod", "build"],
                       help="Режим запуску (за замовчуванням: dev)")
    parser.add_argument("--force-build", action="store_true",
                       help="Примусова збірка frontend")
    parser.add_argument("--no-banner", action="store_true",
                       help="Не показувати банер")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Детальні логи")

    args = parser.parse_args()

    launcher = StreamHubLauncher()

    # Обробка сигналів
    signal.signal(signal.SIGINT, launcher._signal_handler)
    signal.signal(signal.SIGTERM, launcher._signal_handler)

    try:
        if args.mode == "dev":
            asyncio.run(launcher.run_dev_mode(verbose=args.verbose))
        elif args.mode == "fast":
            asyncio.run(launcher.run_fast_mode(verbose=args.verbose))
        elif args.mode == "prod":
            asyncio.run(launcher.run_prod_mode(force_build=args.force_build, verbose=args.verbose))
        elif args.mode == "build":
            if not args.no_banner:
                launcher.print_banner("build")
            print("🔨 Збірка frontend...")
            if asyncio.run(launcher.build_frontend(force=True)):
                print("✅ Збірка завершена успішно")
            else:
                print("❌ Помилка збірки")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Зупинено користувачем")
    except Exception as e:
        print(f"\n❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# Shortcuts для швидкого запуску
def run_dev():
    """Швидкий запуск в dev режимі"""
    sys.argv = [sys.argv[0], "dev"]
    main()


def run_fast():
    """Швидкий запуск в fast режимі"""
    sys.argv = [sys.argv[0], "fast"]
    main()


def run_prod():
    """Швидкий запуск в production режимі"""
    sys.argv = [sys.argv[0], "prod"]
    main()


if __name__ == "__main__":
    main()
