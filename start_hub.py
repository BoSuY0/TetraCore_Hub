#!/usr/bin/env python3
"""
TetraCore StreamHub - Universal Launcher

Об'єднує функціональність dev.py, start.py, build_and_run.py.
Підтримує різні режими запуску з автоматичним визначенням середовища.
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
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Dict, Any, List

# Додавання поточної директорії до Python path
sys.path.insert(0, str(Path(__file__).parent))

import structlog
import uvicorn
from fastapi import FastAPI

class StreamHubLauncher:
    """Універсальний лаунчер для StreamHub"""

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.frontend_dir = self.project_root / "frontend"
        self.static_dir = self.project_root / "static"
        self.server_process = None
        self.frontend_process = None

    def print_banner(self, mode="dev"):
        """Виводить банер запуску"""
        banners = {
            "dev": """
╔══════════════════════════════════════════════════════════════╗
║                    Development Mode                          ║
║                                                              ║
║  🔧 Backend: http://localhost:8000                          ║
║  🎨 Frontend: http://localhost:3000                         ║
║  📊 Dashboard: http://localhost:8000/dashboard              ║
║                                                              ║
║  Hot Reload: ✅  |  Debug Mode: ✅                         ║
╚══════════════════════════════════════════════════════════════╝
            """,
            "fast": """
╔══════════════════════════════════════════════════════════════╗
║                       Fast Mode                              ║
║                                                              ║
║  ⚡ Backend Only: http://localhost:8000                     ║
║  📊 Dashboard: http://localhost:8000/dashboard              ║
║                                                              ║
║  Quick Start: ✅  |  No Frontend Dev Server                ║
╚══════════════════════════════════════════════════════════════╝
            """,
            "prod": """
╔══════════════════════════════════════════════════════════════╗
║                    Production Mode                           ║
║                                                              ║
║  🏭 Server: http://localhost:8000                           ║
║  📊 Dashboard: http://localhost:8000/dashboard              ║
║                                                              ║
║  Optimized Build: ✅  |  Production Ready: ✅              ║
╚══════════════════════════════════════════════════════════════╝
            """
        }

        print(banners.get(mode, banners["dev"]))

    def setup_logging(self, quiet_mode=False):
        """Налаштування системи логування"""
        if quiet_mode:
            # Тихий режим - вимикаємо всі логи окрім критичних помилок
            logging.basicConfig(
                level=logging.CRITICAL,
                format='%(message)s',
                handlers=[logging.StreamHandler()]
            )
            # Вимикаємо всі зайві логери
            for logger_name in ["uvicorn", "uvicorn.access", "fastapi", "core"]:
                logging.getLogger(logger_name).setLevel(logging.CRITICAL)

            # Простіше налаштування structlog без виводу
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.processors.add_log_level,
                    lambda logger, method_name, event_dict: "",  # Повертаємо пустий рядок
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
            return

        try:
            from config import get_settings
            settings = get_settings()

            # Мінімальна конфігурація structlog
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.processors.add_log_level,
                    structlog.processors.StackInfoRenderer(),
                    structlog.dev.ConsoleRenderer(colors=True),
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )

            # Налаштування рівнів логування - використовуємо INFO для verbose
            log_level = logging.INFO
            logging.basicConfig(
                level=log_level,
                format="%(message)s",
                handlers=[logging.StreamHandler()]
            )

            # В verbose режимі дозволяємо більше логів
            logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

        except ImportError:
            # Fallback з мінімальними логами
            logging.basicConfig(
                level=logging.WARNING,
                format='%(message)s',
                handlers=[logging.StreamHandler()]
            )

    def check_node_available(self) -> bool:
        """Перевіряє чи доступний Node.js"""
        try:
            subprocess.run(['node', '--version'], capture_output=True, check=True, timeout=5)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def install_dependencies(self) -> bool:
        """Встановлює залежності frontend"""
        if not self.frontend_dir.exists():
            print("🟡 Frontend директорія не знайдена, пропускаємо...")
            return True

        if not self.check_node_available():
            print("🟡 Node.js не знайдено, пропускаємо frontend...")
            return True

        node_modules = self.frontend_dir / "node_modules"
        if not node_modules.exists():
            print("📦 Встановлюємо frontend залежності...")
            try:
                subprocess.run(['npm', 'ci'], cwd=self.frontend_dir, check=True, timeout=120)
                print("✅ Frontend залежності встановлено")
                return True
            except subprocess.CalledProcessError as e:
                print(f"❌ Помилка встановлення залежностей: {e}")
                return False
        return True

    def build_frontend(self, force=False) -> bool:
        """Збирає frontend для production"""
        if not self.frontend_dir.exists() or not self.check_node_available():
            print("🟡 Пропускаємо збірку frontend")
            return True

        if not force and self.static_dir.exists() and (self.static_dir / "index.html").exists():
            print("✅ Frontend вже зібраний")
            return True

        print("🔨 Збираємо frontend...")
        try:
            start_time = time.time()

            # Встановлюємо залежності якщо потрібно
            if not self.install_dependencies():
                return False

            # Очищуємо попередню збірку
            if self.static_dir.exists():
                shutil.rmtree(self.static_dir)

            # Збираємо frontend з оптимізаціями
            env = os.environ.copy()
            env.update({
                'GENERATE_SOURCEMAP': 'false',
                'INLINE_RUNTIME_CHUNK': 'false',
                'BUILD_PATH': 'build',
                'CI': 'false',
                'DISABLE_ESLINT_PLUGIN': 'true',
            })

            subprocess.run(['npm', 'run', 'build'], cwd=self.frontend_dir, env=env, check=True, timeout=180)

            # Копіюємо зібрані файли
            build_dir = self.frontend_dir / "build"
            if build_dir.exists():
                self.static_dir.mkdir(exist_ok=True)

                for item in build_dir.iterdir():
                    if item.name == "static":
                        for static_item in item.iterdir():
                            dest = self.static_dir / static_item.name
                            if static_item.is_dir():
                                if dest.exists():
                                    shutil.rmtree(dest)
                                shutil.copytree(static_item, dest)
                            else:
                                shutil.copy2(static_item, dest)
                    else:
                        dest = self.static_dir / item.name
                        if item.is_dir():
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)

                build_time = time.time() - start_time
                print(f"✅ Frontend зібрано за {build_time:.2f}s")
                return True
            else:
                print("❌ Build директорія не знайдена")
                return False

        except subprocess.CalledProcessError as e:
            print(f"❌ Помилка збірки frontend: {e}")
            return False
        except Exception as e:
            print(f"❌ Неочікувана помилка: {e}")
            return False

    def start_development_server(self, port=3000):
        """Запускає development сервер з hot reload"""
        if not self.frontend_dir.exists() or not self.check_node_available():
            print("🟡 Неможливо запустити development сервер")
            return None

        try:
            print(f"🎨 Запускаємо frontend development сервер на порту {port}...")

            # Встановлюємо залежності якщо потрібно
            if not self.install_dependencies():
                return None

            # Запускаємо development сервер
            env = os.environ.copy()
            env.update({
                'BROWSER': 'none',
                'PORT': str(port),
                'FAST_REFRESH': 'true',
                'CHOKIDAR_USEPOLLING': 'false',
            })

            process = subprocess.Popen(
                ['npm', 'start'],
                cwd=self.frontend_dir,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            print(f"✅ Frontend development сервер запущено на http://localhost:{port}")
            return process

        except Exception as e:
            print(f"❌ Помилка запуску development сервера: {e}")
            return None

    def setup_environment(self, mode="dev"):
        """Налаштовує змінні середовища"""
        env_configs = {
            "dev": {
                "ENVIRONMENT": "development",
                "DEBUG": "true",
                "LOG_LEVEL": "INFO",
                "HOT_RELOAD": "true",
                "HOST": "0.0.0.0",
                "PORT": "8000",
            },
            "fast": {
                "ENVIRONMENT": "development",
                "DEBUG": "true",
                "LOG_LEVEL": "INFO",
                "HOT_RELOAD": "false",
                "HOST": "0.0.0.0",
                "PORT": "8000",
            },
            "prod": {
                "ENVIRONMENT": "production",
                "DEBUG": "false",
                "LOG_LEVEL": "INFO",
                "HOT_RELOAD": "false",
                "HOST": "0.0.0.0",
                "PORT": "8000",
            }
        }

        config = env_configs.get(mode, env_configs["dev"])
        os.environ.update(config)

    def create_app(self) -> FastAPI:
        """Створює FastAPI додаток"""
        try:
            from config import get_settings, configure_for_environment
            from core.hub import StreamHub

            settings = get_settings()
            configure_for_environment(settings.environment)

            hub = StreamHub(settings)

            @asynccontextmanager
            async def lifespan(app: FastAPI):
                start_time = time.time()
                try:
                    if not hub.is_running:
                        await hub.initialize()
                    startup_time = time.time() - start_time
                    print(f"✅ Готово за {startup_time:.2f}s")
                except Exception as e:
                    print(f"❌ Помилка запуску: {e}")
                    raise
                yield
                try:
                    await hub.shutdown()
                except Exception as e:
                    print(f"❌ Помилка зупинки: {e}")

            hub.lifespan = lifespan
            app = hub.get_app()
            app.state.streamhub = hub
            return app

        except ImportError as e:
            print(f"❌ Помилка імпорту: {e}")
            print("Переконайтеся що всі залежності встановлені")
            sys.exit(1)

    async def run_backend(self, quiet_mode=False):
        """Запускає backend сервер"""
        app = self.create_app()

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
            log_level="error" if quiet_mode else "warning",
            access_log=False,
            reload=False,
            workers=1,
            loop="uvloop" if sys.platform != "win32" else "asyncio",
        )

        server = uvicorn.Server(config)
        await server.serve()

    # === РЕЖИМИ ЗАПУСКУ ===

    async def run_dev_mode(self, verbose=False):
        """Режим розробки з hot reload"""
        self.setup_environment("dev")
        self.setup_logging(quiet_mode=not verbose)
        self.print_banner("dev")

        # Запускаємо React development сервер
        print("🎨 Запускаємо React development сервер...")
        frontend_process = self.start_development_server(port=3000)
        if not frontend_process:
            print("⚠️  Продовжуємо без frontend development сервера")

        # Запускаємо FastAPI з reload
        app = self.create_app()

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=8000,
            log_level="error" if not verbose else "info",
            access_log=False,
            reload=True,
            reload_dirs=["."],  # Моніторимо зміни в backend
            workers=1,
            loop="uvloop" if sys.platform != "win32" else "asyncio",
        )

        server = uvicorn.Server(config)

        try:
            print("🚀 Запускаємо backend сервер з hot reload...")
            await server.serve()
        except KeyboardInterrupt:
            print("\n🛑 Зупинка серверів...")
        finally:
            if frontend_process:
                frontend_process.terminate()
                try:
                    frontend_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    frontend_process.kill()
            await self.cleanup()

    async def run_fast_mode(self, verbose=False):
        """Швидкий запуск тільки backend"""
        self.setup_environment("fast")
        self.setup_logging(quiet_mode=not verbose)
        self.print_banner("fast")

        try:
            print("⚡ Швидкий запуск backend сервера...")
            await self.run_backend(quiet_mode=not verbose)
        except KeyboardInterrupt:
            print("\n🛑 Зупинка сервера...")

    async def run_prod_mode(self, force_build=False, verbose=False):
        """Production режим"""
        self.setup_environment("prod")
        self.setup_logging(quiet_mode=not verbose)
        self.print_banner("prod")

        # Збираємо frontend
        if not self.build_frontend(force=force_build):
            print("⚠️  Продовжуємо без frontend")

        try:
            print("🏭 Запускаємо production сервер...")
            await self.run_backend(quiet_mode=not verbose)
        except KeyboardInterrupt:
            print("\n🛑 Зупинка сервера...")

    async def cleanup(self):
        """Очищення ресурсів"""
        print("✅ Cleanup завершено")

def main():
    """Головна функція"""
    import argparse

    parser = argparse.ArgumentParser(
        description="TetraCore StreamHub Universal Launcher",
        epilog="""
Приклади використання:
  python start_hub.py               # Запуск dev режиму (за замовчуванням)
  python start_hub.py dev           # Розробка з hot reload (1 сервер на :8000)
  python start_hub.py fast          # Швидкий запуск backend
  python start_hub.py prod          # Production сервер
  python start_hub.py build         # Збірка frontend
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
                       help="Детальні логи (за замовчуванням тихий режим)")

    args = parser.parse_args()

    launcher = StreamHubLauncher()

    # Обробка сигналів
    def signal_handler(signum, frame):
        print(f"\n🛑 Отримано сигнал {signum}, зупиняємо...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.mode == "dev":
            asyncio.run(launcher.run_dev_mode(verbose=args.verbose))
        elif args.mode == "fast":
            asyncio.run(launcher.run_fast_mode(verbose=args.verbose))
        elif args.mode == "prod":
            asyncio.run(launcher.run_prod_mode(force_build=args.force_build, verbose=args.verbose))
        elif args.mode == "build":
            if not args.no_banner:
                launcher.print_banner("prod")
            print("🔨 Збірка frontend...")
            if launcher.build_frontend(force=True):
                print("✅ Збірка завершена успішно")
            else:
                print("❌ Помилка збірки")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 Зупинено користувачем")
    except Exception as e:
        print(f"\n❌ Помилка: {e}")
        sys.exit(1)

# Зручні алиаси для швидкого запуску
def run_dev():
    """Запуск dev режиму без аргументів"""
    os.environ.setdefault("STREAMHUB_MODE", "dev")
    launcher = StreamHubLauncher()
    asyncio.run(launcher.run_dev_mode())

def run_fast():
    """Запуск fast режиму без аргументів"""
    os.environ.setdefault("STREAMHUB_MODE", "fast")
    launcher = StreamHubLauncher()
    asyncio.run(launcher.run_fast_mode())

if __name__ == "__main__":
    main()
