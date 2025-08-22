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
from core.logging_utils import RateLimiterProcessor, SampleInfoProcessor

# Константи безпеки
MAX_PATH_LENGTH = 4096
MAX_COMMAND_LENGTH = 8192
ALLOWED_NODE_COMMANDS = ["node", "npm", "npx", "npm.cmd", "npx.cmd"]
ALLOWED_NPM_SCRIPTS = ["install", "ci", "build", "start", "test"]
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

        # Перевіряємо, чи команда є node, і якщо так, чи існує виконуваний файл
        base_cmd = os.path.basename(command[0])
        if base_cmd.startswith("node"):
            node_executable = self.find_node_executable()
            if not node_executable:
                raise SecurityError(
                    "Node.js не знайдено. Будь ласка, встановіть Node.js і переконайтеся, що він є у вашому PATH."
                )
            command[0] = node_executable

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
        self.frontend_dir = self.project_root / "frontend"
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
            log_level = logging.INFO
            uvicorn_log_level = "info"

        # Налаштування Uvicorn логерів (пропагуємо до root)
        uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access", "uvicorn.asgi"]
        for logger_name in uvicorn_loggers:
            logger = logging.getLogger(logger_name)
            logger.setLevel(log_level)
            logger.handlers = []
            logger.propagate = True  # ВИПРАВЛЕННЯ: пропагуємо до root

        # Встановлюємо рівень для root
        root_logger.setLevel(log_level)

        # Rate limiter
        rate_limiter = RateLimiterProcessor(
            min_interval=float(os.getenv("LOG_RATE_LIMIT_SEC", "5"))
        )
        info_sampler = SampleInfoProcessor()
        from core.logging_utils import RedactSecretsProcessor

        redact_secrets = RedactSecretsProcessor()

        # Кастомний рендерер з кольорами (ваш beautiful рендерер)
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

        # Processors для structlog (останній - wrap_for_formatter для stdlib)
        processors = [
            structlog.stdlib.filter_by_level,  # Стандартний фільтр по рівню
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            rate_limiter,
            info_sampler,
            redact_secrets,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,  # ВАЖЛИВО для stdlib
        ]

        structlog.configure(
            processors=processors,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),  # ВИПРАВЛЕННЯ: stdlib інтеграція
            cache_logger_on_first_use=True,
        )

        # Додаємо handler з ProcessorFormatter + ваш custom_renderer
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=custom_console_renderer,  # Ваш рендерер як processor
        )
        handler = logging.StreamHandler()  # Вивід на stdout
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

        # Логування налаштувань
        logger = structlog.get_logger()

        # Зберігаємо логер
        self._logger = structlog.get_logger(__name__)

        return uvicorn_log_level

    def _register_spa_routes(self, app):
        """Реєструє SPA роути після API роутів для правильного порядку обробки"""
        # Підключення статичних файлів тільки в non-dev режимах
        if os.environ.get("ENVIRONMENT") != "development" and self.static_dir.exists():
            from fastapi.staticfiles import StaticFiles
            from fastapi.responses import HTMLResponse
            from fastapi import HTTPException

            app.mount(
                "/static", StaticFiles(directory=str(self.static_dir)), name="static"
            )

            # SPA підтримка - сервування index.html на корені та fallback для роутингу
            @app.get("/", response_class=HTMLResponse)
            @app.get("/dashboard", response_class=HTMLResponse)
            @app.get(
                "/dashboard/{path:path}", response_class=HTMLResponse
            )  # Fallback для SPA роутингу
            async def serve_spa():
                if (self.static_dir / "index.html").exists():
                    with open(
                        self.static_dir / "index.html", "r", encoding="utf-8"
                    ) as f:
                        return HTMLResponse(f.read())
                return HTMLResponse("Frontend not found", status_code=404)

            # Глобальний fallback для SPA (останній, після всіх API роутів)
            @app.get("/{path:path}", response_class=HTMLResponse)
            async def serve_spa_fallback(path: str):
                # Повертаємо 404 для неіснуючих API/WS/static шляхів
                if (
                    path.startswith("api/")
                    or path.startswith("ws")
                    or path.startswith("static/")
                ):
                    raise HTTPException(status_code=404, detail="Not found")
                if (self.static_dir / "index.html").exists():
                    with open(
                        self.static_dir / "index.html", "r", encoding="utf-8"
                    ) as f:
                        return HTMLResponse(f.read())
                self.logger.warning("Frontend not found: index.html відсутній")
                return HTMLResponse("Frontend not found", status_code=404)

            self.logger.info("✅ SPA роути зареєстровано після API роутів")

    def _check_if_frontend_needs_rebuild(self):
        """Перевіряє чи потрібна перебудова frontend"""
        # Перевіряємо наявність build директорії
        build_dir = self.frontend_dir / "build"
        if not build_dir.exists():
            return True

        # Перевіряємо наявність основних файлів
        # Інші дрібниці:
        required_files = ["index.html", "static/js", "static/css"]
        for file_path in required_files:
            if not (build_dir / file_path).exists():
                return True

        # Перевіряємо час модифікації src файлів
        src_dir = self.frontend_dir / "src"
        if src_dir.exists():
            try:
                # Знаходимо найновіший src файл (включаючи CSS та HTML)
                src_files = (
                    list(src_dir.rglob("*.js"))
                    + list(src_dir.rglob("*.jsx"))
                    + list(src_dir.rglob("*.ts"))
                    + list(src_dir.rglob("*.tsx"))
                    + list(src_dir.rglob("*.css"))
                    + list(src_dir.rglob("*.html"))
                )

                if src_files:
                    newest_src = max(src_files, key=lambda p: p.stat().st_mtime)
                    src_time = newest_src.stat().st_mtime

                    # Знаходимо найстаріший build файл
                    build_files = list(build_dir.rglob("*.js")) + list(
                        build_dir.rglob("*.css")
                    )
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
            # Очищуємо static_dir перед копіюванням для чистої структури
            if self.static_dir.exists():
                shutil.rmtree(self.static_dir)
            self.static_dir.mkdir(exist_ok=True)
            # Рекурсивне копіювання всіх файлів з build до static (без nesting)
            copied_files = 0
            flattened_files = 0

            for root, dirs, files in os.walk(build_dir):
                for file in files:
                    src_file = Path(root) / file
                    # Визначаємо відносний шлях відносно build
                    rel_path = src_file.relative_to(build_dir)
                    str(rel_path)

                    # Універсальний рекурсивний flatten: видаляємо проблематичні префікси
                    flatten_prefixes = [
                        "static/",
                        "assets/static/",
                        "build/static/",
                        "public/static/",
                        "dist/static/",
                        "out/static/",
                    ]
                    path_changed = True
                    flatten_count = 0
                    max_iterations = 5  # Запобігаємо нескінченному циклу

                    while path_changed and flatten_count < max_iterations:
                        path_changed = False
                        for prefix in flatten_prefixes:
                            if str(rel_path).startswith(prefix):
                                old_rel_path = rel_path
                                rel_path = Path(str(rel_path)[len(prefix) :])
                                flattened_files += 1
                                flatten_count += 1
                                self.logger.debug(
                                    f"🔄 Flatten #{flatten_count}: {old_rel_path} → {rel_path}"
                                )
                                path_changed = True
                                break  # Перевіряємо з початку після зміни

                    dst_file = self.static_dir / rel_path
                    dst_file.parent.mkdir(
                        parents=True, exist_ok=True
                    )  # Створюємо піддиректорії якщо потрібно
                    shutil.copy2(src_file, dst_file)
                    copied_files += 1

            self.logger.info(
                f"📋 Копіювання завершено: {copied_files} файлів, {flattened_files} flatten'ено"
            )

            # Перевірки
            if not (self.static_dir / "index.html").exists():
                self.logger.error("Помилка: index.html не знайдено після копіювання")
                return False

            # Ширша перевірка на nesting: перевіряємо на різні проблематичні директорії
            problematic_dirs = ["static", "assets", "build"]
            for prob_dir in problematic_dirs:
                nested_dir = self.static_dir / prob_dir
                if nested_dir.exists() and nested_dir.is_dir():
                    sub_structure = list(nested_dir.iterdir())
                    if sub_structure:
                        # Перевіряємо чи це не просто assets/ з контентом (це OK)
                        if prob_dir == "assets" and not any(
                            item.name in problematic_dirs for item in sub_structure
                        ):
                            continue  # assets/ з js/css файлами - це нормально
                        self.logger.error(
                            f"Критична помилка: {prob_dir}/ містить файли після flattening - можлива nesting проблема"
                        )
                        self.logger.error(
                            f"Вміст {prob_dir}/: {[item.name for item in sub_structure]}"
                        )
                        return False

            # Детальна діагностика структури файлів
            static_subdirs = [d.name for d in self.static_dir.iterdir() if d.is_dir()]
            static_files = [f.name for f in self.static_dir.iterdir() if f.is_file()]

            self.logger.info("✅ Frontend файли скопійовано в static")
            self.logger.debug(f"📁 Директорії в static: {static_subdirs}")
            self.logger.debug(f"📄 Файли в static: {static_files}")

            # Перевіряємо ключові файли і директорії
            key_paths = ["js", "css", "assets", "index.html"]
            for key_path in key_paths:
                path_obj = self.static_dir / key_path
                if path_obj.exists():
                    if path_obj.is_dir():
                        contents = list(path_obj.iterdir())
                        self.logger.debug(f"📂 {key_path}/: {len(contents)} елементів")
                    else:
                        self.logger.debug(f"📄 {key_path}: файл існує")
                else:
                    self.logger.debug(f"❌ {key_path}: не знайдено")
            return True

        except Exception as e:
            self.logger.error(f"Помилка копіювання файлів: {e}")
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
        """Встановлює залежності frontend з безпековими обмеженнями"""
        if not await self.check_node_available():
            return False

        if not self.frontend_dir.exists():
            self.logger.error("Frontend директорія не знайдена")
            return False

        self.logger.debug("Перевірка залежностей...")

        self.logger.debug("Використовуємо системний Node.js та 'npm install'.")

        command_list = ["npm", "install", "--legacy-peer-deps", "--no-audit"]

        try:
            frontend_path = self.secure_path.validate_path(str(self.frontend_dir))

            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                command_list, cwd=frontend_path, timeout=600  # 10 хвилин
            )

            if returncode == 0:
                self.logger.debug("Залежності встановлено/перевірено.")
                return True
            else:
                # Детальне логування помилки
                error_msg = f"Помилка виконання 'npm install' (код: {returncode})"
                self.logger.error(error_msg)

                if stdout.strip():
                    print(f"STDOUT: {stdout.strip()}")
                    self.logger.error(f"npm stdout: {stdout.strip()}")

                if stderr.strip():
                    print(f"STDERR: {stderr.strip()}")
                    self.logger.error(f"npm stderr: {stderr.strip()}")

                # Додаткова діагностика
                print(f"Команда: {' '.join(command_list)}")
                print(f"Робоча директорія: {frontend_path}")
                print(
                    f"Змінні оточення: {list(self.secure_cmd.create_safe_env().keys())}"
                )

                return False

        except Exception as e:
            self.logger.error(f"Фатальна помилка під час встановлення залежностей: {e}")
            return False

    async def build_frontend(self, force=False):
        """Збирає frontend, якщо потрібно"""
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
            env.update(
                {
                    "CI": "false",  # Вимикаємо CI режим для локальної збірки
                    "GENERATE_SOURCEMAP": "false",  # Вимикаємо source maps для production
                    "NODE_ENV": "production",
                }
            )

            returncode, stdout, stderr = await self.secure_cmd.run_safe(
                ["npm", "run", "build"],
                cwd=frontend_path,
                timeout=600,  # 10 хвилин для збірки
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

        # Звільняємо порт 3000 для frontend
        await self.free_port(3000)

        try:
            # Валідуємо шлях
            frontend_path = self.secure_path.validate_path(str(self.frontend_dir))

            command_list = ["npm", "run", "dev", "--", "--host", "--port", "3000"]

            # Валідуємо команду через SecureCommand (автоматично додасть .cmd на Windows)
            validated_command = self.secure_cmd.validate_command(command_list)

            process = await asyncio.create_subprocess_exec(
                *validated_command,
                cwd=str(frontend_path),
                env=self.secure_cmd.create_safe_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self.frontend_process = process

            # Запускаємо моніторинг логів
            async def log_output(pipe, prefix):
                try:
                    while True:
                        line = await pipe.readline()
                        if not line:
                            break
                        line_text = line.decode().strip()
                        if line_text:
                            self.logger.debug(f"{prefix}: {line_text}")
                            # Виводимо важливі повідомлення в консоль
                            if any(
                                keyword in line_text.lower()
                                for keyword in [
                                    "local:",
                                    "error",
                                    "warn",
                                    "ready",
                                    "compiled",
                                ]
                            ):
                                print(f"[Frontend {prefix}] {line_text}")
                except Exception as e:
                    self.logger.error(f"Помилка читання {prefix}: {e}")

            # Створюємо задачі для моніторингу
            stdout_task = asyncio.create_task(log_output(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(log_output(process.stderr, "stderr"))

            # Зберігаємо задачі для cleanup
            if not hasattr(self, "frontend_log_tasks"):
                self.frontend_log_tasks = []
            self.frontend_log_tasks.extend([stdout_task, stderr_task])

            # Чекаємо поки сервер запуститься
            await asyncio.sleep(3)

            if process.returncode is None:
                print(
                    "✅ Frontend development server запущено на http://localhost:3000"
                )
                return process
            else:
                # Зупиняємо задачі моніторингу якщо процес не запустився
                for task in [stdout_task, stderr_task]:
                    if not task.done():
                        task.cancel()
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
            # REDIS_URL видалено для development - Redis вимкнено за замовчуванням
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

    def _validate_environment(self):
        """Валідація змінних оточення"""
        required_vars = ["SECRET_KEY"]  # REDIS_URL більше не обов'язковий

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
        from web.jwks import router as jwks_router
        from web.dashboard import register_dashboard_routes
        from web.security_diagnostics import router as security_diag_router
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

        # JWKS endpoint (always)
        app.include_router(jwks_router)

        # Security diagnostics endpoint тільки у development
        try:
            if settings.is_development():
                app.include_router(security_diag_router)
        except Exception:
            pass

        # Реєструємо базові fallback-роути для API (health/metrics/clients/tasks)
        # Це потрібно для тестового середовища, де StreamHub ще не ініціалізований
        try:
            register_dashboard_routes(app, streamhub_instance=None)
        except Exception:
            pass

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

        backend_url = f"http://localhost:{os.environ.get('PORT', '8000')}/api/health"

        for attempt in range(max_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(backend_url, timeout=5) as response:
                        if response.status in [200, 401, 403]:  # Сервер працює
                            print(f"✅ Backend готовий після {attempt + 1} спроб")
                            return True
                        else:
                            print(
                                f"⚠️  Backend відповів {response.status}, спроба {attempt + 1}/{max_attempts}"
                            )
            except Exception as e:
                print(
                    f"⏳ Спроба {attempt + 1}/{max_attempts}: Backend ще не готовий ({str(e)[:50]}...)"
                )

            if attempt < max_attempts - 1:
                await asyncio.sleep(delay)

        print(f"❌ Backend не став готовим після {max_attempts} спроб")
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

            # Запускаємо StreamHub окремо
            await self._startup_hub()

            # Додаємо hub до app state
            if self._hub_instance:
                app.state.hub = self._hub_instance

            # Додаємо SPA роути ПІСЛЯ реєстрації API роутів, щоб уникнути перехоплення
            self._register_spa_routes(app)

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
            self.logger.error(f"Помилка запуску backend: {e}")
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

        # Виводимо банер
        self.print_banner("dev")

        try:
            # Запускаємо backend з hot reload
            print("\n🔧 Запуск в development режимі...\n")
            print("🚀 Запускаємо backend сервер спочатку...")

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
            print("⏳ Перевіряємо готовність backend сервера...")
            backend_ready = await self.wait_for_backend_ready(max_attempts=15, delay=1)

            if not backend_ready:
                print("❌ Backend не готовий, але продовжуємо запуск frontend...")

            # Запускаємо frontend dev server
            print("🎨 Запускаємо frontend dev server...")
            frontend_process = await self.start_development_server()
            if frontend_process:
                self.frontend_process = frontend_process
                print("✅ Frontend dev server запущено на http://localhost:3000")

            # Чекаємо завершення backend (він блокує до сигналу)
            try:
                await backend_task
            except asyncio.CancelledError:
                print("🛑 Backend task скасовано")

        except KeyboardInterrupt:
            print("\n👋 Зупинено користувачем")
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

        # Копіюємо існуючу збірку якщо є
        self._copy_build_files()

        try:
            # Запускаємо тільки backend
            print("\n⚡ Швидкий запуск backend...\n")
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
        print("🚀 Запуск TetraCore StreamHub (main mode)...")

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

        print("🧪 Режим тестування неактивності клієнтів")
        print("=" * 60)
        print(f"Ping затримка: {ping_delay} секунд")
        print(f"Симуляція відключення: {'ТАК' if simulate_disconnect else 'НІ'}")
        print(
            f"Heartbeat інтервал: {os.environ.get('WEBSOCKET_HEARTBEAT_INTERVAL')} секунд"
        )
        print(f"WebSocket таймаут: {os.environ.get('WEBSOCKET_TIMEOUT')} секунд")
        print("=" * 60)

        try:
            # Запускаємо backend в тестовому режимі
            print("\n🚀 Запуск StreamHub в тестовому режимі...")

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
            print("⏳ Очікування готовності backend...")
            backend_ready = await self.wait_for_backend_ready(max_attempts=15, delay=1)

            if backend_ready:
                print("✅ Backend готовий!")

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
                    print("🛑 Тестування скасовано")
            else:
                print("❌ Backend не готовий, тестування неможливе")
                backend_task.cancel()

        except KeyboardInterrupt:
            print("\n👋 Тестування зупинено користувачем")
        finally:
            await self.cleanup()

    async def _run_inactivity_tests(self, ping_delay=0, simulate_disconnect=False):
        """Запуск тестових сценаріїв для перевірки неактивності"""
        print("\n🧪 Початок тестових сценаріїв...")

        try:
            # Імітуємо клієнта з затримками ping
            if ping_delay > 0:
                print(f"\n🐌 Тест 1: Клієнт з затримкою ping {ping_delay} секунд")
                await self._test_slow_ping_client(ping_delay)

            # Імітуємо втрату з'єднання
            if simulate_disconnect:
                print("\n💔 Тест 2: Симуляція втрати з'єднання")
                await self._test_connection_loss()

            # Базовий тест неактивності
            print("\n⏱️ Тест 3: Клієнт без активності")
            await self._test_inactive_client()

            print("\n✅ Всі тести завершено!")

        except Exception as e:
            print(f"\n❌ Помилка під час тестування: {e}")
            import traceback

            traceback.print_exc()

    async def _test_slow_ping_client(self, ping_delay):
        """Тест клієнта з повільним ping"""
        print(f"   📡 Підключення клієнта з затримкою ping {ping_delay}с...")
        # Тут можна додати код для створення тестового WebSocket клієнта
        # з модифікованим ping інтервалом
        await asyncio.sleep(5)  # Імітація тестування
        print("   ✅ Тест повільного ping завершено")

    async def _test_connection_loss(self):
        """Тест втрати з'єднання"""
        print("   💔 Симуляція втрати мережевого з'єднання...")
        # Тут можна додати код для імітації мережевих проблем
        await asyncio.sleep(5)  # Імітація тестування
        print("   ✅ Тест втрати з'єднання завершено")

    async def _test_inactive_client(self):
        """Тест повністю неактивного клієнта"""
        print("   😴 Створення неактивного клієнта...")
        # Тут можна додати код для створення клієнта, який не надсилає ping
        await asyncio.sleep(10)  # Імітація тестування
        print("   ✅ Тест неактивного клієнта завершено")

    def diagnose_environment(self):
        """Діагностика середовища виконання"""
        from config import get_settings

        print("🔍 Діагностика середовища TetraCore Hub")
        print("=" * 60)

        settings = get_settings()
        info = settings.diagnose_environment()

        # Основна інформація
        print("\n📊 ЗАГАЛЬНА ІНФОРМАЦІЯ")
        print(f"Дата/час: {info['timestamp']}")
        print(f"Python: {info['python_version']}")
        print(f"Платформа: {info['platform']}")
        print(f"Hostname: {info['hostname']}")

        # Середовище
        print("\n🌍 СЕРЕДОВИЩЕ")
        env = info["environment"]
        print(f"Heroku: {'ТАК' if env['is_heroku'] else 'НІ'}")
        print(f"DYNO: {env['dyno'] or '<не встановлено>'}")
        print(f"PORT: {env['port'] or '<не встановлено>'}")
        print(f"Environment: {env['environment']}")
        print(f"Debug: {env['debug']}")
        print(f"Log Level: {env['log_level']}")

        # URL конфігурація
        print("\n🔗 URL КОНФІГУРАЦІЯ")
        urls = info["urls"]
        print(f"Backend: {urls['backend']}")
        print(f"Frontend: {urls['frontend']}")
        print(f"Dashboard: {urls['dashboard']}")
        print(f"WebSocket: {urls['websocket']}")

        # Redis
        print("\n🔴 REDIS")
        redis = info["redis"]
        print(f"Enabled: {redis['enabled']}")
        print(f"URL: {redis['url_safe']}")

        # Автентифікація
        print("\n🔐 АВТЕНТИФІКАЦІЯ")
        auth = info["auth"]
        print(f"Require Auth: {auth['require_authentication']}")
        print(f"Admin Configured: {auth['admin_configured']}")

        # Валідація
        auth_errors = settings.validate_auth_config()
        if auth_errors:
            print("\n⚠️ ПОМИЛКИ КОНФІГУРАЦІЇ:")
            for error in auth_errors:
                print(f"  • {error}")
        else:
            print("\n✅ Конфігурація валідна")

        print("\n" + "=" * 60)

    async def cleanup(self):
        """Очищення ресурсів"""
        self.logger.info("🧹 Очищення ресурсів...")

        cleanup_tasks = []

        # Завершення frontend процесу
        if self.frontend_process:

            async def cleanup_frontend():
                try:
                    # Зупиняємо log monitoring tasks
                    if hasattr(self, "frontend_log_tasks"):
                        for task in self.frontend_log_tasks:
                            if not task.done():
                                task.cancel()
                        self.frontend_log_tasks.clear()

                    self.logger.debug("Завершення frontend процесу...")
                    self.frontend_process.terminate()
                    await asyncio.wait_for(self.frontend_process.wait(), timeout=5.0)
                    self.logger.debug("Frontend процес завершено")
                except ProcessLookupError:
                    self.logger.debug("Frontend процес вже був завершений")
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "Frontend процес не відповідає, форсуємо завершення"
                    )
                    try:
                        self.frontend_process.kill()
                    except Exception:
                        pass
                except Exception as e:
                    self.logger.debug(f"Error terminating frontend: {e}")

            cleanup_tasks.append(cleanup_frontend())

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
        print(f"\n🛑 Fallback signal handler: отримано сигнал {signum}")

        # Просто встановлюємо флаг та виходимо
        if hasattr(self, "_hub_instance") and self._hub_instance:
            self._hub_instance.is_running = False

        print("💥 Примусове завершення")
        sys.exit(1)

    def _force_exit_handler(self, signum, frame):
        """Примусове завершення при повторному сігналі"""
        print(f"\n💥 Примусове завершення (сигнал {signum})")
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
  python hub_launcher.py build        # Збірка frontend
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
        choices=["dev", "fast", "prod", "build", "main", "diagnose", "test-inactive"],
        help="Режим запуску (за замовчуванням: dev)",
    )
    parser.add_argument(
        "--force-build", action="store_true", help="Примусова збірка frontend"
    )
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
            asyncio.run(
                launcher.run_prod_mode(
                    force_build=args.force_build, verbose=args.verbose
                )
            )
        elif args.mode == "build":
            if not args.no_banner:
                launcher.print_banner("build")
            print("🔨 Збірка frontend...")
            if asyncio.run(launcher.build_frontend(force=True)):
                print("✅ Збірка завершена успішно")
            else:
                print("❌ Помилка збірки")
                sys.exit(1)
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
