#!/usr/bin/env python3
"""
TetraCore StreamHub - Unified Secure Launcher

Об'єднує функціональність start_hub.py та secure_launcher.py.
Підтримує різні режими запуску з автоматичним визначенням середовища
та додатковими заходами безпеки.
"""

import os
import sys
import asyncio
import subprocess
import logging
import shutil
import secrets
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Додавання поточної директорії до Python path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

import structlog
import uvicorn
from fastapi import FastAPI
from core.logging import configure_unified_logging

# Константи безпеки
MAX_PATH_LENGTH = 4096
MAX_COMMAND_LENGTH = 8192
ALLOWED_NODE_COMMANDS = []
ALLOWED_NPM_SCRIPTS = []
DEFAULT_TIMEOUT = 300  # 5 хвилин
MAX_TIMEOUT = 3600  # 1 година
SAFE_ENV_VARS = [
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "NODE_ENV",
    "NPM_CONFIG_LOGLEVEL",
    "CI",
    "FORCE_COLOR",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
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
        dangerous_parts = ["..", ".git", "__pycache__", "node_modules"]
        for part in parts:
            if part in dangerous_parts or part.startswith("."):
                raise SecurityError(f"Небезпечний компонент шляху: {part}")

        return path_obj


class SecureCommand:
    """Безпечне виконання команд"""

    def __init__(self):
        self.allowed_commands = set(ALLOWED_NODE_COMMANDS)

    def find_node_executable(self) -> Optional[str]:
        """Знаходить виконуваний файл Node.js"""
        # Перевіряємо системний PATH
        node_path = shutil.which("node")
        if node_path:
            return node_path

        # Перевіряємо стандартні місця встановлення
        if sys.platform == "win32":
            possible_paths = [
                os.path.join(
                    os.environ.get("ProgramFiles", "C:\\Program Files"),
                    "nodejs",
                    "node.exe",
                ),
                os.path.join(
                    os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                    "nodejs",
                    "node.exe",
                ),
            ]
        else:
            possible_paths = ["/usr/bin/node", "/usr/local/bin/node"]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        return None

    def validate_command(self, command: List[str]) -> List[str]:
        """Валідує команду перед виконанням"""
        if not command:
            raise SecurityError("Порожня команда")

        # Перевірка довжини команди
        cmd_str = " ".join(command)
        if len(cmd_str) > MAX_COMMAND_LENGTH:
            raise SecurityError(
                f"Команда занадто довга: {len(cmd_str)} > {MAX_COMMAND_LENGTH}"
            )

        # Для Windows, автоматично додаємо розширення до команд
        if sys.platform == "win32":
            if command[0] in ["npm", "npx"]:
                command[0] = command[0] + ".cmd"
            elif command[0] == "node":
                # Node.js зазвичай встановлюється як node.exe на Windows
                # Але Windows автоматично знаходить .exe файли
                pass

        # Перевірка дозволених команд
        base_cmd = os.path.basename(command[0])
        if base_cmd not in self.allowed_commands:
            raise SecurityError(f"Недозволена команда: {base_cmd}")

        # Валідація npm scripts
        if base_cmd in ["npm", "npm.cmd"] and len(command) > 1:
            if command[1] not in ["run"] + ALLOWED_NPM_SCRIPTS:
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
        env.update(
            {
                "NODE_ENV": os.getenv("NODE_ENV", "production"),
                "NPM_CONFIG_LOGLEVEL": "warn",
                "CI": os.getenv(
                    "CI", "false"
                ),  # Змінено на false для локального розробництва
                "FORCE_COLOR": "0",
            }
        )

        # Додаємо npm-специфічні змінні для Windows
        if sys.platform == "win32":
            for var in [
                "npm_config_cache",
                "npm_config_prefix",
                "npm_config_userconfig",
            ]:
                if var in os.environ:
                    env[var] = os.environ[var]

        # Видаляємо потенційно небезпечні змінні
        dangerous_vars = ["LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"]
        for var in dangerous_vars:
            env.pop(var, None)

        return env

    async def run_safe(
        self, command: List[str], cwd: Path, timeout: int = DEFAULT_TIMEOUT
    ) -> Tuple[int, str, str]:
        """Безпечне виконання команди"""
        # Валідація
        command = self.validate_command(command)

        # Node/ npm команди більше не підтримуються
        base_cmd = os.path.basename(command[0])
        if base_cmd in ["node", "npm", "npx", "node.exe", "npm.cmd", "npx.cmd"]:
            raise SecurityError(
                "Node/npm команди заборонені: фронтенд вилучено з проекту"
            )

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
                preexec_fn=self._limit_resources if sys.platform != "win32" else None,
            )

            # Очікуємо завершення з таймаутом
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise SecurityError(f"Команда перевищила таймаут: {timeout}s")

            return (
                process.returncode,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
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

            # Обмеження пам'яті (1GB) - закоментовано, бо викликає OOM в node
            # resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))

            # Видаляємо обмеження на кількість процесів, бо воно викликає помилки fork
            # resource.setrlimit(resource.RLIMIT_NPROC, (100, 100))

        except Exception:
            pass  # Ігноруємо помилки на системах без resource


class StreamHubLauncher:
    """Універсальний безпечний лаунчер для StreamHub"""

    def __init__(self):
        self.project_root = Path(__file__).parent.absolute()
        # Frontend вилучено
        self.static_dir = self.project_root / "static"
        self.server_process = None
        self.frontend_process = None

        # Ініціалізація безпекових компонентів
        self.secure_path = SecurePath(self.project_root)
        self.secure_cmd = SecureCommand()

        # Логер буде створений після налаштування логування
        self._logger = None

    @property
    def logger(self):
        """Безпечний доступ до логера"""
        if self._logger is None:
            # Якщо логер ще не налаштований, створюємо тимчасовий
            import structlog

            return structlog.get_logger()
        return self._logger

    def print_banner(self, mode="dev"):
        """Виводить банер запуску"""
        from config import get_settings

        settings = get_settings()

        backend_url = settings.get_backend_url()
        websocket_url = settings.get_websocket_url()

        banner = f"""
╔══════════════════════════════════════════════════════════════╗
║               🌊 TetraCore StreamHub v2.0                      ║
║                  Unified Secure Launcher                       ║
╠══════════════════════════════════════════════════════════════╣
║  Mode:      {mode.upper():<48}║
║  Environment: {os.getenv("ENVIRONMENT", "development"):<46}║
╠══════════════════════════════════════════════════════════════╣
║  🔧 Backend:    {backend_url:<44}║
║  🔌 WebSocket:  {websocket_url:<44}║
╠══════════════════════════════════════════════════════════════╣
║  📁 Project:    {str(self.project_root):<44}║
║  ⏰ Started:    {datetime.now().strftime("%Y-%m-%d %H:%M:%S"):<44}║
╚══════════════════════════════════════════════════════════════╝
        """
        self.logger.info(banner)

        if mode == "dev":
            self.logger.info("🔧 Development режим:")
            self.logger.info("   • Hot reload активний")
            self.logger.info("   • Debug логування увімкнено")
            self.logger.info("   • Backend API на :8000")
            self.logger.info("   • Один процес для всього\n")
        elif mode == "fast":
            self.logger.info("⚡ Fast режим:")
            self.logger.info("   • Тільки backend")
            self.logger.info("   • Швидкий старт\n")
        elif mode == "prod":
            self.logger.info("🚀 Production режим:")
            self.logger.info("   • Оптимізована збірка")
            self.logger.info("   • Production налаштування\n")

    def setup_logging(self, verbose=False):
        """Налаштування системи логування (уніфікована конфігурація)."""
        # Локальна директорія для логів
        log_dir = self.project_root / "logs"
        log_dir.mkdir(exist_ok=True)

        # Підлаштовуємо рівень через ENV для уніфікованої конфігурації
        if verbose:
            os.environ["LOG_LEVEL"] = "DEBUG"
        else:
            os.environ.setdefault("LOG_LEVEL", "INFO")

        # Очищаємо існуючі хендлери і застосовуємо єдину конфігурацію
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        configure_unified_logging()

        # Налаштовуємо Uvicorn логери для пропагації у root (до structlog)
        uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"]
        for logger_name in uvicorn_loggers:
            logger = logging.getLogger(logger_name)
            logger.handlers = []
            logger.propagate = True

        # Визначаємо рівень для Uvicorn за LOG_LEVEL
        env_level = os.getenv("LOG_LEVEL", "INFO").upper()
        uvicorn_log_level = "debug" if env_level == "DEBUG" else "info"

        # Зберігаємо логер класу
        self._logger = structlog.get_logger(__name__)

        return uvicorn_log_level

    def _register_spa_routes(self, app):
        return

    def _check_if_frontend_needs_rebuild(self):
        return False

    def _copy_build_files(self):
        return False

    async def check_node_available(self):
        """Перевіряє наявність Node.js з безпековими обмеженнями"""
        try:
            # Валідуємо команду через SecureCommand (може додати розширення на Windows)
            command = self.secure_cmd.validate_command(["node", "--version"])

            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                command, cwd=self.project_root, timeout=10
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
        """Відключено: фронтенд перенесено з проекту."""
        return False

    async def build_frontend(self, force=False):
        """Відключено: фронтенд перенесено з проекту."""
        return False

    async def start_development_server(self):
        """Відключено: фронтенд перенесено з проекту."""
        return None

    def setup_environment(self):
        """Налаштування змінних оточення"""
        env_file = self.project_root / ".env"

        # Базові налаштування
        default_env = {
            "ENVIRONMENT": "development",
            "HOST": "0.0.0.0",
            "PORT": os.environ.get("PORT", "8000"),
            "BACKEND_URL": "http://localhost:8000",
            # REDISCLOUD_URL видалено для development - Redis вимкнено за замовчуванням
            "SECRET_KEY": secrets.token_urlsafe(32),
            "WORKERS": "1",
            "LOG_LEVEL": "INFO",
            "ENABLE_CORS": "true",
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

        # Узгодження settings з оточенням виконується у відповідних run_* режимах

    def _validate_environment(self):
        """Валідація змінних оточення"""
        required_vars = ["SECRET_KEY"]  # REDISCLOUD_URL більше не обов'язковий

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
        from fastapi.middleware.cors import CORSMiddleware
        from core.security_integration import integrate_security

        # Видалено імпорти web модулів - фронтенд виключено
        from config import get_settings

        # Глобальна змінна для збереження hub instance
        self._hub_instance = None

        # Створюємо FastAPI додаток без lifespan
        app = FastAPI(
            title="TetraCore StreamHub",
            description="Централізований хаб для маршрутизації завдань",
            version="2.0.0",
        )

        # Отримуємо налаштування
        settings = get_settings()

        # Налаштовуємо CORS (звужена конфігурація)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "X-Requested-With",
                "X-Correlation-Id",
            ],
            expose_headers=["X-Total-Count", "X-Page-Count", "X-API-Version"],
        )

        # Інтеграція безпеки
        integrate_security(
            app,
            redis_client=None,  # Буде встановлено після ініціалізації
            require_auth=settings.require_authentication,
        )

        # JWKS endpoint видалено - фронтенд виключено
        # Security diagnostics endpoint видалено - фронтенд виключено

        # Реєстрація dashboard роутів видалена - фронтенд виключено

        # Підключення статичних файлів буде в run_backend після реєстрації API роутів
        # щоб уникнути перехоплення API запитів SPA fallback'ом

        # НЕ реєструємо роути тут - це буде зроблено після створення реального hub
        # Зберігаємо посилання на app для пізнішої реєстрації
        self._app = app
        return app

    async def _startup_hub(self):
        """Запуск StreamHub окремо від FastAPI"""
        try:
            self.logger.info("🚀 Ініціалізація StreamHub...")

            # Імпортуємо StreamHub
            from core.hub import StreamHub

            # Створюємо та ініціалізуємо StreamHub
            hub = StreamHub()
            await hub.initialize()

            # Встановлюємо app та реєструємо роути з реальним hub
            if hasattr(self, "_app"):
                hub.app = self._app
                hub._register_routes()
                self.logger.info("✅ Роути зареєстровано з реальним StreamHub")

            self._hub_instance = hub
            self.logger.info("✅ StreamHub успішно ініціалізовано")

        except Exception as e:
            self.logger.error(f"❌ Помилка ініціалізації StreamHub: {e}")
            raise

    async def _shutdown_hub(self):
        """Зупинка StreamHub"""
        if self._hub_instance:
            try:
                self.logger.info("🛑 Зупинка StreamHub...")

                # Встановлюємо флаг зупинки
                self._hub_instance.is_running = False

                # Швидка зупинка з таймаутом
                await asyncio.wait_for(self._hub_instance.shutdown(), timeout=5.0)

                self.logger.info("✅ StreamHub зупинено")

            except asyncio.TimeoutError:
                self.logger.warning("⏰ Timeout при зупинці StreamHub")
            except Exception as e:
                self.logger.error(f"❌ Помилка зупинки StreamHub: {e}")
            finally:
                self._hub_instance = None

    def get_hub(self):
        """Отримує поточний екземпляр StreamHub"""
        return getattr(self, "_hub_instance", None)

    async def free_port(self, port: int):
        """Звільняє порт, якщо він зайнятий"""
        import socket
        import platform

        # Перевіряємо чи порт зайнятий
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("localhost", port))
        sock.close()

        if result == 0:
            self.logger.debug(f"Порт {port} зайнятий, звільняємо...")

            try:
                import psutil

                # Знаходимо процес, який використовує порт
                for proc in psutil.process_iter(["pid", "name"]):
                    try:
                        for conn in proc.connections():
                            if conn.laddr.port == port:
                                self.logger.debug(
                                    f"Завершення процесу {proc.info['name']} (PID: {proc.info['pid']}) на порту {port}"
                                )
                                proc.terminate()
                                try:
                                    proc.wait(timeout=3)
                                except psutil.TimeoutExpired:
                                    self.logger.debug(
                                        f"Примусове завершення процесу {proc.info['pid']}"
                                    )
                                    proc.kill()
                                # Даємо час ОС звільнити порт
                                await asyncio.sleep(0.5)
                                return
                    except (
                        psutil.NoSuchProcess,
                        psutil.AccessDenied,
                        psutil.ZombieProcess,
                    ):
                        pass
            except ImportError:
                self.logger.debug(
                    "psutil не встановлено, використовуємо альтернативний метод"
                )

                # Fallback метод без psutil
                system = platform.system()
                try:
                    if system in ["Linux", "Darwin"]:  # Linux або macOS
                        # Використовуємо lsof для пошуку процесу
                        # Шукаємо PID процеса без shell=True
                        result = subprocess.run(
                            ["/usr/sbin/lsof", "-ti", f":{port}"],
                            capture_output=True,
                            text=True,
                        )
                        if result.stdout.strip():
                            pid = result.stdout.strip()
                            self.logger.info(
                                f"🔨 Знайдено процес PID {pid} на порту {port}"
                            )
                            # Завершуємо процес
                            subprocess.run(["kill", f"{pid}"])
                            await asyncio.sleep(0.5)
                            # Перевіряємо чи процес завершився
                            if (
                                subprocess.run(
                                    ["bash", "-lc", f"kill -0 {pid} 2>/dev/null"]
                                ).returncode
                                != 0
                            ):
                                self.logger.info(
                                    f"✅ Процес {pid} завершено, порт {port} звільнено"
                                )
                            else:
                                # Примусове завершення
                                subprocess.run(["kill", "-9", f"{pid}"])
                                self.logger.info(f"⚡ Процес {pid} примусово завершено")
                            await asyncio.sleep(0.5)
                            return
                    elif system == "Windows":
                        # Для Windows використовуємо netstat без shell і без пайпів
                        # Валідація порту як числового значення
                        try:
                            port_str = str(int(port))
                        except Exception:
                            self.logger.error(f"Невалідний номер порту: {port}")
                            return
                        # Запускаємо netstat та парсимо вивід у Python
                        result = subprocess.run(
                            ["netstat", "-ano"], capture_output=True, text=True
                        )
                        if result.stdout:
                            lines = result.stdout.strip().splitlines()
                            for line in lines:
                                parts = line.split()
                                # Очікуваний формат: Proto Local Address Foreign Address State PID
                                if len(parts) >= 5:
                                    local_addr = parts[1]
                                    pid = parts[-1]
                                    if f":{port_str}" in local_addr:
                                        self.logger.info(
                                            f"🔨 Знайдено процес PID {pid} на порту {port_str}"
                                        )
                                        subprocess.run(
                                            ["taskkill", "/PID", str(pid), "/F"]
                                        )
                                        self.logger.info(f"✅ Процес {pid} завершено")
                                        await asyncio.sleep(0.5)
                                        return
                except Exception as e:
                    self.logger.error(f"❌ Помилка при спробі звільнити порт: {e}")
        else:
            # Видалений зайвий лог вільного порту
            pass

    async def wait_for_backend_ready(self, max_attempts=10, delay=1):
        """Чекає поки backend стане готовим для прийому запитів"""
        import aiohttp

        backend_url = f"http://localhost:{os.environ.get('PORT', '8000')}/health"

        for attempt in range(max_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(backend_url, timeout=5) as response:
                        if response.status in [200, 401, 403]:  # Сервер працює
                            self.logger.info(
                                f"✅ Backend готовий після {attempt + 1} спроб"
                            )
                            return True
                        else:
                            self.logger.warning(
                                f"⚠️  Backend відповів {response.status}, спроба {attempt + 1}/{max_attempts}"
                            )
            except Exception as e:
                self.logger.debug(
                    f"⏳ Спроба {attempt + 1}/{max_attempts}: Backend ще не готовий ({str(e)[:50]}...)"
                )

            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)

        self.logger.error(f"❌ Backend не став готовим після {max_attempts} спроб")
        return False

    async def run_backend(
        self, host="0.0.0.0", port=None, reload=False, log_level="info"
    ):
        """Запускає backend сервер"""
        # Використовуємо PORT з оточення для Heroku
        if port is None:
            port = int(os.environ.get("PORT", "8000"))

        try:
            # Звільняємо порт перед запуском
            await self.free_port(port)

            # Створюємо FastAPI додаток
            app = self.create_app()

            # Запускаємо StreamHub окремо (фейл-фаст)
            await self._startup_hub()

            # Додаємо hub до app state
            if self._hub_instance:
                app.state.hub = self._hub_instance

            # SPA роути не додаються

            # Кастомний log_config для уніфікації Uvicorn логів через structlog
            def get_custom_console_renderer():
                def custom_console_renderer(logger, method_name, event_dict):
                    timestamp = event_dict.pop("timestamp", "")
                    level = method_name.upper()
                    event = event_dict.pop("event", "")

                    colors = {
                        "DEBUG": "\033[36m",  # Cyan
                        "INFO": "\033[32m",  # Green
                        "WARNING": "\033[33m",  # Yellow
                        "ERROR": "\033[31m",  # Red
                        "CRITICAL": "\033[35m",  # Magenta
                    }
                    reset = "\033[0m"

                    level_color = colors.get(level, "")
                    colored_level = f"{level_color}{level:<8}{reset}"

                    extras = []
                    for key, value in event_dict.items():
                        if key not in ["logger", "level"]:
                            extras.append(f"\033[90m{key}=\033[37m{value}\033[0m")

                    extra_str = " " + " ".join(extras) if extras else ""
                    message = f"\033[90m{timestamp}\033[0m [{colored_level}] {event}{extra_str}"

                    return message

                return custom_console_renderer

            {
                "version": 1,
                "disable_existing_loggers": False,
                "formatters": {
                    "default": {
                        "()": "structlog.stdlib.ProcessorFormatter",
                        "processor": get_custom_console_renderer(),
                    },
                    "access": {
                        "()": "structlog.stdlib.ProcessorFormatter",
                        "processor": get_custom_console_renderer(),
                    },
                },
                "handlers": {
                    "default": {
                        "level": log_level.upper(),
                        "class": "logging.StreamHandler",
                        "formatter": "default",
                    },
                    "access": {
                        "level": log_level.upper(),
                        "class": "logging.StreamHandler",
                        "formatter": "access",
                    },
                },
                "loggers": {
                    "uvicorn": {
                        "handlers": ["default"],
                        "level": log_level.upper(),
                        "propagate": False,
                    },
                    "uvicorn.error": {"level": log_level.upper()},
                    "uvicorn.access": {
                        "handlers": ["access"],
                        "level": log_level.upper(),
                        "propagate": False,
                    },
                },
            }

            # Створюємо uvicorn config з log_config=None щоб уникнути конфлікту з structlog
            # Логи Uvicorn будуть propagate через root logger до structlog
            try:
                certfile = os.getenv("APP_TLS_CERT")
                keyfile = os.getenv("APP_TLS_KEY")

                uvicorn_kwargs = dict(
                    app=app,
                    host=host,
                    port=port,
                    reload=reload,
                    log_level=log_level,
                    log_config=None,
                    access_log=False,
                    use_colors=False,
                    loop="asyncio",
                )

                if certfile and keyfile:
                    self.logger.info(
                        "\ud83d\udd12 TLS увімкнено: використовую APP_TLS_CERT/APP_TLS_KEY"
                    )
                    uvicorn_kwargs["ssl_certfile"] = certfile
                    uvicorn_kwargs["ssl_keyfile"] = keyfile

                config = uvicorn.Config(**uvicorn_kwargs)
            except KeyError as e:
                self.logger.error(f"Помилка конфігурації Uvicorn: відсутній ключ {e}")
                raise
            except ValueError as e:
                if "Unable to configure formatter" in str(e):
                    self.logger.error(
                        "Конфлікт у logging config. Використовується log_config=None для сумісності з structlog."
                    )
                raise
            except Exception as e:
                self.logger.error(f"Помилка створення Uvicorn Config: {e}")
                raise

            # Створюємо сервер
            server = uvicorn.Server(config)
            self.server_process = server

            # Встановлюємо обробники сигналів для сервера
            def signal_handler(signum, frame):
                self.logger.info(f"🛑 Отримано сигнал {signum}")
                server.should_exit = True

                # Запускаємо shutdown в background task
                if self._hub_instance:
                    asyncio.create_task(self._shutdown_hub())

            import signal

            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)

            # Запускаємо сервер
            await server.serve()

        except Exception as e:
            try:
                from core.logging.utils import _mask_text_patterns

                masked = _mask_text_patterns(str(e))
            except Exception:
                masked = str(e)
            self.logger.error(f"Помилка запуску backend: {masked}")
            raise
        finally:
            # Завжди викликаємо shutdown
            await self._shutdown_hub()

    async def run_dev_mode(self, verbose=False):
        """Development режим - один сервер з hot reload"""
        # Логування (перше, щоб захопити всі логи)
        log_level = self.setup_logging(verbose)

        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "development"
        os.environ["NODE_ENV"] = "development"  # ← додали, щоб npm ставив devDeps

        # Узгоджуємо глобальні налаштування з dev-оточенням для коректних URL у банері
        try:
            from config import update_settings, Environment as _Env

            update_settings(
                environment=_Env.DEVELOPMENT,
                port=int(os.environ.get("PORT", "8000")),
                host=os.environ.get("HOST", "0.0.0.0"),
            )
        except Exception:
            pass

        # Виводимо банер
        self.print_banner("dev")

        try:
            # Запускаємо backend з hot reload
            self.logger.info("🔧 Запуск в development режимі...")
            self.logger.info("🚀 Запускаємо backend сервер спочатку...")

            # Запускаємо backend як асинхронну задачу
            backend_task = asyncio.create_task(
                self.run_backend(
                    host="0.0.0.0",
                    port=int(os.environ.get("PORT", "8000")),
                    reload=True,
                    log_level=log_level,
                )
            )

            # Чекаємо поки backend стане готовим
            self.logger.info("⏳ Перевіряємо готовність backend сервера...")
            backend_ready = await self.wait_for_backend_ready(max_attempts=15, delay=1)

            if not backend_ready:
                self.logger.warning("❌ Backend не готовий — очікуємо далі")

            # Frontend dev server відключено

            # Чекаємо завершення backend (він блокує до сигналу)
            try:
                await backend_task
            except asyncio.CancelledError:
                self.logger.info("🛑 Backend task скасовано")

        except KeyboardInterrupt:
            self.logger.info("👋 Зупинено користувачем")
        finally:
            await self.cleanup()

    async def run_fast_mode(self, verbose=False):
        """Fast режим - швидкий запуск тільки backend"""
        # Логування (перше, щоб захопити всі логи)
        log_level = self.setup_logging(verbose)

        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "production"

        # Виводимо банер
        self.print_banner("fast")

        try:
            # Запускаємо тільки backend
            self.logger.info("⚡ Швидкий запуск backend...")
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=False,
                log_level=log_level,
            )

        finally:
            await self.cleanup()

    async def run_prod_mode(self, force_build=False, verbose=False):
        """Production режим - повна збірка та оптимізація"""
        # Логування (перше, щоб захопити всі логи)
        log_level = self.setup_logging(verbose)

        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "production"
        os.environ["NODE_ENV"] = "production"

        # Виводимо банер
        self.print_banner("prod")

        # Збірка фронтенду відключена (фронтенд вилучено з проекту)

        try:
            # Запускаємо production сервер
            self.logger.info("🚀 Запуск production серверу...")
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=False,
                log_level=log_level,
            )

        finally:
            await self.cleanup()

    async def run_main_mode(self, verbose=False):
        """Main режим - простий запуск як в main.py"""
        # Логування (перше, щоб захопити всі логи)
        log_level = self.setup_logging(verbose)

        # Налаштування
        self.setup_environment()

        # Не показуємо банер в main режимі для сумісності
        self.logger.info("🚀 Запуск TetraCore StreamHub (main mode)...")

        try:
            # Запускаємо backend тільки з базовими налаштуваннями
            await self.run_backend(
                host="0.0.0.0",
                port=int(os.environ.get("PORT", "8000")),
                reload=False,
                log_level=log_level,
            )

        finally:
            await self.cleanup()

    async def run_test_inactive_mode(
        self, verbose=False, ping_delay=0, simulate_disconnect=False
    ):
        """Режим тестування неактивності клієнтів"""
        # Логування (перше, щоб захопити всі логи)
        log_level = self.setup_logging(verbose)

        # Налаштування
        self.setup_environment()
        os.environ["ENVIRONMENT"] = "test"

        # Спеціальні налаштування для тестування
        os.environ["WEBSOCKET_HEARTBEAT_INTERVAL"] = (
            "30"  # Коротший інтервал для тестування
        )
        os.environ["WEBSOCKET_TIMEOUT"] = "60"  # Коротший таймаут для тестування

        self.logger.info("🧪 Режим тестування неактивності клієнтів")
        self.logger.info("=" * 60)
        self.logger.info(f"Ping затримка: {ping_delay} секунд")
        self.logger.info(
            f"Симуляція відключення: {'ТАК' if simulate_disconnect else 'НІ'}"
        )
        self.logger.info(
            f"Heartbeat інтервал: {os.environ.get('WEBSOCKET_HEARTBEAT_INTERVAL')} секунд"
        )
        self.logger.info(
            f"WebSocket таймаут: {os.environ.get('WEBSOCKET_TIMEOUT')} секунд"
        )
        self.logger.info("=" * 60)

        try:
            # Запускаємо backend в тестовому режимі
            self.logger.info("🚀 Запуск StreamHub в тестовому режимі...")

            # Створюємо задачу для backend
            backend_task = asyncio.create_task(
                self.run_backend(
                    host="0.0.0.0",
                    port=int(os.environ.get("PORT", "8000")),
                    reload=False,
                    log_level=log_level,
                )
            )

            # Чекаємо поки backend стане готовим
            self.logger.info("⏳ Очікування готовності backend...")
            backend_ready = await self.wait_for_backend_ready(max_attempts=15, delay=1)

            if backend_ready:
                self.logger.info("✅ Backend готовий!")

                # Запускаємо тестові сценарії
                test_task = asyncio.create_task(
                    self._run_inactivity_tests(ping_delay, simulate_disconnect)
                )

                # Чекаємо завершення backend або тестів
                try:
                    done, pending = await asyncio.wait(
                        [backend_task, test_task], return_when=asyncio.FIRST_COMPLETED
                    )

                    # Скасовуємо незавершені задачі
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                except asyncio.CancelledError:
                    self.logger.info("🛑 Тестування скасовано")
            else:
                self.logger.error("❌ Backend не готовий, тестування неможливе")
                backend_task.cancel()

        except KeyboardInterrupt:
            self.logger.info("👋 Тестування зупинено користувачем")
        finally:
            await self.cleanup()

    async def _run_inactivity_tests(self, ping_delay=0, simulate_disconnect=False):
        """Запуск тестових сценаріїв для перевірки неактивності"""
        self.logger.info("🧪 Початок тестових сценаріїв...")

        try:
            # Імітуємо клієнта з затримками ping
            if ping_delay > 0:
                self.logger.info(
                    f"🐌 Тест 1: Клієнт з затримкою ping {ping_delay} секунд"
                )
                await self._test_slow_ping_client(ping_delay)

            # Імітуємо втрату з'єднання
            if simulate_disconnect:
                self.logger.info("💔 Тест 2: Симуляція втрати з'єднання")
                await self._test_connection_loss()

            # Базовий тест неактивності
            self.logger.info("⏱️ Тест 3: Клієнт без активності")
            await self._test_inactive_client()

            self.logger.info("✅ Всі тести завершено!")

        except Exception as e:
            self.logger.exception(f"❌ Помилка під час тестування: {e}")

    async def _test_slow_ping_client(self, ping_delay):
        """Тест клієнта з повільним ping"""
        self.logger.info(f"   📡 Підключення клієнта з затримкою ping {ping_delay}с...")
        # Тут можна додати код для створення тестового WebSocket клієнта
        # з модифікованим ping інтервалом
        await asyncio.sleep(5)  # Імітація тестування
        self.logger.info("   ✅ Тест повільного ping завершено")

    async def _test_connection_loss(self):
        """Тест втрати з'єднання"""
        self.logger.info("   💔 Симуляція втрати мережевого з'єднання...")
        # Тут можна додати код для імітації мережевих проблем
        await asyncio.sleep(5)  # Імітація тестування
        self.logger.info("   ✅ Тест втрати з'єднання завершено")

    async def _test_inactive_client(self):
        """Тест повністю неактивного клієнта"""
        self.logger.info("   😴 Створення неактивного клієнта...")
        # Тут можна додати код для створення клієнта, який не надсилає ping
        await asyncio.sleep(10)  # Імітація тестування
        self.logger.info("   ✅ Тест неактивного клієнта завершено")

    def diagnose_environment(self):
        """Діагностика середовища виконання"""
        from config import get_settings

        self.logger.info("🔍 Діагностика середовища TetraCore Hub")
        self.logger.info("=" * 60)

        settings = get_settings()
        info = settings.diagnose_environment()

        # Основна інформація
        self.logger.info("\n📊 ЗАГАЛЬНА ІНФОРМАЦІЯ")
        self.logger.info(f"Дата/час: {info['timestamp']}")
        self.logger.info(f"Python: {info['python_version']}")
        self.logger.info(f"Платформа: {info['platform']}")
        self.logger.info(f"Hostname: {info['hostname']}")

        # Середовище
        self.logger.info("\n🌍 СЕРЕДОВИЩЕ")
        env = info["environment"]
        self.logger.info(f"Heroku: {'ТАК' if env['is_heroku'] else 'НІ'}")
        self.logger.info(f"DYNO: {env['dyno'] or '<не встановлено>'}")
        self.logger.info(f"PORT: {env['port'] or '<не встановлено>'}")
        self.logger.info(f"Environment: {env['environment']}")
        self.logger.info(f"Debug: {env['debug']}")
        self.logger.info(f"Log Level: {env['log_level']}")

        # URL конфігурація
        self.logger.info("\n🔗 URL КОНФІГУРАЦІЯ")
        urls = info["urls"]
        self.logger.info(f"Backend: {urls['backend']}")
        self.logger.info(f"WebSocket: {urls['websocket']}")

        # Redis
        self.logger.info("\n🔴 REDIS")
        redis = info["redis"]
        self.logger.info(f"Enabled: {redis['enabled']}")
        self.logger.info(f"URL: {redis['url_safe']}")

        # Автентифікація
        self.logger.info("\n🔐 АВТЕНТИФІКАЦІЯ")
        auth = info["auth"]
        self.logger.info(f"Require Auth: {auth['require_authentication']}")
        self.logger.info(f"Admin Configured: {auth['admin_configured']}")

        # Валідація
        auth_errors = settings.validate_auth_config()
        if auth_errors:
            self.logger.warning("\n⚠️ ПОМИЛКИ КОНФІГУРАЦІЇ:")
            for error in auth_errors:
                self.logger.warning(f"  • {error}")
        else:
            self.logger.info("\n✅ Конфігурація валідна")

        self.logger.info("\n" + "=" * 60)

    async def cleanup(self):
        """Очищення ресурсів"""
        self.logger.info("🧹 Очищення ресурсів...")

        cleanup_tasks = []

        # Немає frontend процесу для очищення

        # Завершення backend сервера
        if self.server_process:

            async def cleanup_backend():
                try:
                    self.logger.debug("Завершення backend процесу...")
                    self.server_process.should_exit = True
                    if hasattr(self.server_process, "force_exit"):
                        self.server_process.force_exit = True
                except Exception as e:
                    self.logger.debug(f"Error stopping backend: {e}")

            cleanup_tasks.append(cleanup_backend())

        # Виконуємо cleanup паралельно з таймаутом
        if cleanup_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cleanup_tasks, return_exceptions=True), timeout=3.0
                )
            except asyncio.TimeoutError:
                self.logger.warning("⏰ Cleanup timeout")
            except Exception as e:
                self.logger.debug(f"Cleanup error: {e}")

        self.logger.info("✅ Очищення завершено")

    def _signal_handler(self, signum, frame):
        """Обробка сигналів (застарілий - використовується тільки як fallback)"""
        self.logger.warning(f"🛑 Fallback signal handler: отримано сигнал {signum}")

        # Просто встановлюємо флаг та виходимо
        if hasattr(self, "_hub_instance") and self._hub_instance:
            self._hub_instance.is_running = False

        self.logger.error("💥 Примусове завершення")
        sys.exit(1)

    def _force_exit_handler(self, signum, frame):
        """Примусове завершення при повторному сігналі"""
        self.logger.error(f"💥 Примусове завершення (сигнал {signum})")
        sys.exit(1)


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
  python hub_launcher.py main         # Простий запуск (замість main.py)
  python hub_launcher.py diagnose     # Діагностика середовища
  python hub_launcher.py test-inactive # Тестування неактивності
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="dev",
        choices=["dev", "fast", "prod", "main", "diagnose", "test-inactive"],
        help="Режим запуску (за замовчуванням: dev)",
    )
    # Прапор зборки фронтенду вилучено
    parser.add_argument("--no-banner", action="store_true", help="Не показувати банер")
    parser.add_argument("--verbose", "-v", action="store_true", help="Детальні логи")
    parser.add_argument(
        "--ping-delay",
        type=int,
        default=0,
        help="Додаткова затримка ping в секундах (для test-inactive)",
    )
    parser.add_argument(
        "--simulate-disconnect",
        action="store_true",
        help="Симуляція втрати з'єднання (для test-inactive)",
    )

    args = parser.parse_args()

    launcher = StreamHubLauncher()

    # Signal handlers тепер реєструються в run_backend()

    try:
        if args.mode == "dev":
            asyncio.run(launcher.run_dev_mode(verbose=args.verbose))
        elif args.mode == "fast":
            asyncio.run(launcher.run_fast_mode(verbose=args.verbose))
        elif args.mode == "prod":
            asyncio.run(launcher.run_prod_mode(verbose=args.verbose))
        elif args.mode == "main":
            # Режим main.py для сумісності
            asyncio.run(launcher.run_main_mode(verbose=args.verbose))
        elif args.mode == "diagnose":
            # Діагностика середовища
            launcher.diagnose_environment()
        elif args.mode == "test-inactive":
            # ДОДАНО: Режим тестування неактивності
            asyncio.run(
                launcher.run_test_inactive_mode(
                    verbose=args.verbose,
                    ping_delay=args.ping_delay,
                    simulate_disconnect=args.simulate_disconnect,
                )
            )
    except KeyboardInterrupt:
        launcher.logger.info("👋 Зупинено користувачем")
    except Exception as e:
        # Акуратний вихід без стек-трейсу з маскуванням
        from core.logging.utils import _mask_text_patterns

        err_text = _mask_text_patterns(str(e))
        launcher.logger.error(f"❌ Помилка: {err_text}")
        if any(
            k in err_text.lower()
            for k in [
                "redis",
                "gaierror",
                "connectionerror",
                "name or service not known",
            ]
        ):
            launcher.logger.error(
                "🔴 Redis недоступний або неправильно налаштований. Перевірте REDIS_TLS_URL/REDIS_URL/REDISCLOUD_URL та мережу/DNS. Завершення роботи."
            )
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
