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

    def _check_if_frontend_needs_rebuild(self) -> bool:
        """Перевіряє чи потрібна перезбірка frontend на основі дат модифікації"""
        try:
            # Перевіряємо чи існує зібраний frontend
            static_index = self.static_dir / "index.html"
            build_index = self.frontend_dir / "build" / "index.html"
            
            # Якщо немає зібраного frontend - потрібна збірка
            if not static_index.exists() and not build_index.exists():
                return True
            
            # Знаходимо найновіший зібраний файл
            latest_built = None
            if static_index.exists():
                latest_built = static_index.stat().st_mtime
            if build_index.exists():
                build_time = build_index.stat().st_mtime
                if latest_built is None or build_time > latest_built:
                    latest_built = build_time
            
            if latest_built is None:
                return True
            
            # Перевіряємо дати модифікації вихідних файлів frontend
            src_dir = self.frontend_dir / "src"
            public_dir = self.frontend_dir / "public"
            package_json = self.frontend_dir / "package.json"
            
            # Файли що можуть впливати на збірку
            check_paths = []
            
            if src_dir.exists():
                for src_file in src_dir.rglob("*"):
                    if src_file.is_file():
                        check_paths.append(src_file)
            
            if public_dir.exists():
                for pub_file in public_dir.rglob("*"):
                    if pub_file.is_file():
                        check_paths.append(pub_file)
            
            if package_json.exists():
                check_paths.append(package_json)
            
            # Перевіряємо чи якийсь файл новіший за збірку
            for file_path in check_paths:
                if file_path.stat().st_mtime > latest_built:
                    print(f"🔍 Знайдено оновлений файл: {file_path.name}")
                    return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Помилка перевірки дат файлів: {e}")
            return True  # У разі помилки краще перезібрати

    def _copy_build_files(self, start_time=None) -> bool:
        """Копіює файли з frontend/build до static директорії"""
        try:
            build_dir = self.frontend_dir / "build"
            if not build_dir.exists():
                print("❌ Build директорія не знайдена")
                return False

            print("📁 Копіюємо зібрані файли до static/...")
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

            if start_time:
                build_time = time.time() - start_time
                print(f"✅ Frontend зібрано та скопійовано за {build_time:.2f}s")
            else:
                print("✅ Frontend файли скопійовано")
            return True

        except Exception as e:
            print(f"❌ Помилка копіювання файлів: {e}")
            return False

    def check_node_available(self) -> bool:
        """Перевіряє чи доступний Node.js"""
        try:
            result = subprocess.run(['node', '--version'], capture_output=True, check=True, timeout=5)
            version = result.stdout.decode().strip()
            print(f"✅ Node.js знайдено: {version}")
            return True
        except FileNotFoundError:
            print("❌ Node.js не знайдено в PATH")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ Помилка запуску Node.js: {e}")
            return False
        except subprocess.TimeoutExpired:
            print("❌ Таймаут при перевірці Node.js")
            return False

    def install_dependencies(self) -> bool:
        """Встановлює залежності frontend"""
        if not self.frontend_dir.exists():
            print("🟡 Frontend директорія не знайдена, пропускаємо...")
            return True

        print("🔍 Перевіряємо доступність Node.js...")
        node_available = self.check_node_available()
        if not node_available:
            print("⚠️  Node.js недоступний, спробуємо продовжити...")
            # Не повертаємо False, спробуємо продовжити

        node_modules = self.frontend_dir / "node_modules"
        if not node_modules.exists():
            print("📦 Встановлюємо frontend залежності...")
            try:
                # Спочатку спробуємо npm ci
                print("🔄 Запускаємо npm ci...")
                subprocess.run(['npm', 'ci'], cwd=self.frontend_dir, check=True, timeout=180)
                print("✅ Frontend залежності встановлено через npm ci")
                return True
            except subprocess.CalledProcessError as e:
                print(f"⚠️  npm ci не вдався: {e}")
                print("🔄 Пробуємо npm install...")
                try:
                    subprocess.run(['npm', 'install'], cwd=self.frontend_dir, check=True, timeout=180)
                    print("✅ Frontend залежності встановлено через npm install")
                    return True
                except subprocess.CalledProcessError as e2:
                    print(f"❌ npm install також не вдався: {e2}")
                    return False
            except FileNotFoundError:
                print("❌ npm команда не знайдена")
                return False
        else:
            print("✅ node_modules вже існує")
        return True

    def build_frontend(self, force=False) -> bool:
        """Збирає frontend для production"""
        if not self.frontend_dir.exists():
            print("🟡 Frontend директорія не знайдена, пропускаємо збірку frontend")
            return True
            
        # В продакшені завжди намагаємося зібрати frontend
        if not self.check_node_available():
            print("⚠️  Node.js не знайдено, але спробуємо зібрати frontend...")
            # Не повертаємо False, продовжуємо спробу

        # Перевіряємо чи frontend потребує перезбірки
        if not force:
            needs_rebuild = self._check_if_frontend_needs_rebuild()
            if not needs_rebuild:
                print("✅ Frontend актуальний, перезбірка не потрібна")
                return True
            else:
                print("🔄 Frontend потребує перезбірки (файли оновлені)")

        print("🔨 Збираємо frontend...")
        try:
            start_time = time.time()

            # Встановлюємо залежності якщо потрібно
            print("🔍 Перевіряємо залежності...")
            if not self.install_dependencies():
                print("❌ Не вдалося встановити залежності")
                return False

            # Очищуємо попередню збірку
            if self.static_dir.exists():
                print("🧹 Очищуємо попередню збірку...")
                shutil.rmtree(self.static_dir)

            # Збираємо frontend з оптимізаціями
            print("⚙️  Налаштовуємо змінні середовища для збірки...")
            env = os.environ.copy()
            env.update({
                'GENERATE_SOURCEMAP': 'false',
                'INLINE_RUNTIME_CHUNK': 'false',
                'BUILD_PATH': 'build',
                'CI': 'false',
                'DISABLE_ESLINT_PLUGIN': 'true',
            })

            print("🔄 Запускаємо npm run build...")
            subprocess.run(['npm', 'run', 'build'], cwd=self.frontend_dir, env=env, check=True, timeout=300)

            # Копіюємо зібрані файли
            return self._copy_build_files(start_time)

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
            },
            "fast": {
                "ENVIRONMENT": "development",
                "DEBUG": "true",
                "LOG_LEVEL": "INFO",
                "HOT_RELOAD": "false",
                "HOST": "0.0.0.0",
            },
            "prod": {
                "ENVIRONMENT": "production",
                "DEBUG": "false",
                "LOG_LEVEL": "INFO",
                "HOT_RELOAD": "false",
                "HOST": "0.0.0.0",
            }
        }

        config = env_configs.get(mode, env_configs["dev"])
        
        # Не перезаписуємо PORT якщо він вже встановлений (наприклад, Heroku)
        if "PORT" not in os.environ:
            config["PORT"] = "8000"
            
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
        
        port = int(os.environ.get("PORT", 8000))
        print(f"🌐 Запускаємо сервер на порту {port}")

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=port,
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
        
        port = int(os.environ.get("PORT", 8000))

        config = uvicorn.Config(
            app=app,
            host="0.0.0.0",
            port=port,
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
            port = int(os.environ.get("PORT", 8000))
            print(f"🏭 Запускаємо production сервер на порту {port}...")
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
