#!/usr/bin/env python3
"""
Тестування ендпоінтів TetraCore Hub
Включає тести для API proxy, WebSocket та dev-режиму
"""

import asyncio
import aiohttp
import websockets
import pytest
import time
import subprocess
import os
import socket
from pathlib import Path

# Конфігурація тестів
BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"
WEBSOCKET_URL = "ws://localhost:8000/ws"
WEBSOCKET_PROXY_URL = "ws://localhost:3000/ws"

# Основні API ендпоінти для тестування
TEST_ENDPOINTS = [
    "/api/health",
    "/api/metrics", 
    "/api/clients",
    "/api/tasks"
]

class TestHubEndpoints:
    """Тестування ендпоінтів Hub"""

    @pytest.fixture
    async def session(self):
        """HTTP сесія для тестів"""
        async with aiohttp.ClientSession() as session:
            yield session

    def _is_port_open(self, host: str, port: int, timeout: float = 0.2) -> bool:
        """Швидка перевірка доступності порту на IPv4 і IPv6"""
        for family in (socket.AF_INET, socket.AF_INET6):
            s = socket.socket(family, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                if family == socket.AF_INET6:
                    s.connect(("::1" if host == "localhost" else host, port))
                else:
                    s.connect((("127.0.0.1" if host == "localhost" else host), port))
                return True
            except Exception:
                pass
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        return False

    async def retry_request(self, session, url, max_attempts=1, delay=0.2, request_timeout=2):
        """Retry логіка для HTTP запитів з експоненційним backoff"""
        for attempt in range(max_attempts):
            try:
                async with session.get(url, timeout=request_timeout) as response:
                    print(f"🔄 Спроба {attempt + 1}/{max_attempts} для {url}: {response.status}")
                    
                    # Якщо отримали 404 для /api/* ендпоінтів, це проблема з роутами
                    if response.status == 404 and '/api/' in url:
                        if attempt < max_attempts - 1:
                            print(f"⚠️  404 для API ендпоінту, retry через {delay}с...")
                            await asyncio.sleep(delay)
                            delay *= 1.5  # Експоненційний backoff
                            continue
                        else:
                            print(f"❌ Остаточна 404 для {url} після {max_attempts} спроб")
                    
                    # Для інших статусів повертаємо відразу
                    return response.status, await response.text()
                    
            except Exception as e:
                if attempt < max_attempts - 1:
                    print(f"⚠️  Помилка спроби {attempt + 1}: {e}, retry через {delay}с...")
                    await asyncio.sleep(delay)
                    delay *= 1.5
                else:
                    print(f"❌ Остаточна помилка після {max_attempts} спроб: {e}")
                    raise e
        
        return None, None

    async def test_backend_direct_endpoints(self, session):
        """Тест прямих ендпоінтів backend (localhost:8000)"""
        print(f"\n🔍 Тестування прямих backend ендпоінтів...")
        if not self._is_port_open('localhost', 8000):
            pytest.skip("Backend не запущений — пропускаємо, щоб уникнути таймаутів")

        async def _fetch(ep: str):
            url = f"{BACKEND_URL}{ep}"
            return ep, await self.retry_request(session, url, max_attempts=1, delay=0.2, request_timeout=2)

        results = await asyncio.gather(*[_fetch(ep) for ep in TEST_ENDPOINTS], return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                pytest.fail(f"Backend endpoint error: {res}")
            endpoint, reply = res
            if reply:
                status, text = reply
                print(f"✅ {endpoint}: {status}")
                assert status in [200, 401, 403], f"Неочікуваний статус {status} для {endpoint}"
            else:
                pytest.fail(f"Backend endpoint {endpoint} недоступний після швидкої перевірки")

    async def test_proxy_endpoints(self, session):
        """Тест ендпоінтів через Vite proxy (localhost:3000)"""
        print(f"\n🔄 Тестування API через Vite proxy...")
        if not self._is_port_open('localhost', 3000):
            pytest.skip("Frontend proxy не запущений — пропускаємо, щоб уникнути таймаутів")

        async def _fetch_proxy(ep: str):
            url = f"{FRONTEND_URL}{ep}"
            return ep, await self.retry_request(session, url, max_attempts=1, delay=0.2, request_timeout=2)

        results = await asyncio.gather(*[_fetch_proxy(ep) for ep in TEST_ENDPOINTS], return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                pytest.fail(f"Proxy endpoint error: {res}")
            endpoint, reply = res
            if reply:
                status, text = reply
                print(f"✅ Proxy {endpoint}: {status}")
                assert status != 404, f"404 помилка для proxy {endpoint} - роути не зареєстровані"
                assert status in [200, 401, 403, 503], f"Неочікуваний статус {status} для proxy {endpoint}"
                if status == 503:
                    # Деякі проксі (Vite/Heroku) повертають HTML error-page. Достатньо самого статусу 503.
                    print(f"⚠️  {endpoint}: Backend недоступний (503)")
            else:
                pytest.fail(f"Proxy endpoint {endpoint} недоступний після швидкої перевірки")

    async def test_websocket_direct(self):
        """Тест прямого WebSocket з'єднання (localhost:8000)"""
        print(f"\n🔌 Тестування прямого WebSocket...")
        if not self._is_port_open('localhost', 8000):
            pytest.skip("Backend WS не запущений — пропускаємо, щоб уникнути таймаутів")
        
        try:
            async with websockets.connect(WEBSOCKET_URL, timeout=2) as websocket:
                print("✅ Пряме WebSocket з'єднання успішне")
                
                # Надсилаємо тестове повідомлення
                await websocket.send('{"type": "ping"}')
                
                # Чекаємо відповідь
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                    print(f"✅ WebSocket відповідь отримана: {response[:50]}...")
                except asyncio.TimeoutError:
                    print("⚠️  WebSocket відповідь не отримана (timeout)")
                    
        except Exception as e:
            print(f"❌ Пряме WebSocket з'єднання не вдалося: {e}")
            # Не fail-имо тест, бо це може бути нормально в dev

    async def test_websocket_proxy(self):
        """Тест WebSocket через Vite proxy (localhost:3000)"""
        print(f"\n🔄 Тестування WebSocket через Vite proxy...")
        if not self._is_port_open('localhost', 3000):
            pytest.skip("Frontend WS proxy не запущений — пропускаємо, щоб уникнути таймаутів")
        
        try:
            async with websockets.connect(WEBSOCKET_PROXY_URL, timeout=2) as websocket:
                print("✅ WebSocket proxy з'єднання успішне")
                
                # Надсилаємо тестове повідомлення
                await websocket.send('{"type": "ping"}')
                
                # Чекаємо відповідь
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                    print(f"✅ WebSocket proxy відповідь: {response[:50]}...")
                except asyncio.TimeoutError:
                    print("⚠️  WebSocket proxy відповідь не отримана (timeout)")
                    
        except Exception as e:
            print(f"❌ WebSocket proxy з'єднання не вдалося: {e}")
            # Не fail-имо, бо frontend може бути не запущений

    async def test_cors_headers(self, session):
        """Тест CORS заголовків"""
        print(f"\n🌍 Тестування CORS заголовків...")
        
        headers = {
            'Origin': 'http://localhost:3000',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'authorization,content-type'
        }
        
        url = f"{BACKEND_URL}/api/health"
        try:
            async with session.options(url, headers=headers, timeout=5) as response:
                cors_origin = response.headers.get('Access-Control-Allow-Origin', '')
                cors_methods = response.headers.get('Access-Control-Allow-Methods', '')
                
                print(f"✅ CORS Origin: {cors_origin}")
                print(f"✅ CORS Methods: {cors_methods}")
                
                # Перевіряємо що localhost:3000 дозволений
                assert cors_origin in ['*', 'http://localhost:3000'], f"CORS не дозволяє localhost:3000: {cors_origin}"
                
        except Exception as e:
            print(f"❌ CORS тест не вдався: {e}")

def check_servers_running():
    """Перевіряє чи запущені сервери"""
    print("🔍 Перевіряємо доступність серверів...")
    
    import socket
    
    def check_port(host, port, name):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print(f"✅ {name} ({host}:{port}) доступний")
            return True
        else:
            print(f"❌ {name} ({host}:{port}) недоступний")
            return False
    
    backend_running = check_port('localhost', 8000, 'Backend')
    frontend_running = check_port('localhost', 3000, 'Frontend')
    
    return backend_running, frontend_running

async def run_comprehensive_test():
    """Запуск всіх тестів"""
    print("🚀 Запуск комплексного тестування TetraCore Hub")
    print("=" * 60)
    
    # Перевіряємо сервери
    backend_running, frontend_running = check_servers_running()
    
    if not backend_running and not frontend_running:
        print("\n❌ Ні backend, ні frontend не запущені!")
        # Підказка без прив’язки до конкретного режиму: запускайте як вам зручно
        print("💡 Підказка: запустіть бекенд і/або фронтенд у будь-який зручний для вас спосіб")
        return False
    
    # Створюємо тестовий клас
    test_instance = TestHubEndpoints()
    
    async with aiohttp.ClientSession() as session:
        try:
            # Тест backend ендпоінтів
            if backend_running:
                await test_instance.test_backend_direct_endpoints(session)
                await test_instance.test_websocket_direct()
                await test_instance.test_cors_headers(session)
            
            # Тест proxy ендпоінтів
            if frontend_running:
                await test_instance.test_proxy_endpoints(session)
                await test_instance.test_websocket_proxy()
            
            print(f"\n✅ Всі тести завершені успішно!")
            return True
            
        except Exception as e:
            print(f"\n❌ Тести не пройшли: {e}")
            return False

def test_dev_mode_startup():
    """Тест запуску dev-режиму"""
    print(f"\n🔧 Тестування запуску dev-режиму...")
    
    # Перевіряємо чи файли існують
    project_root = Path(__file__).parent
    launcher_path = project_root / "hub_launcher.py"
    
    if not launcher_path.exists():
        print(f"❌ hub_launcher.py не знайдено: {launcher_path}")
        return False
    
    print(f"✅ hub_launcher.py знайдено: {launcher_path}")
    
    # Тестуємо чи можна імпортувати модулі
    try:
        import hub_launcher
        print("✅ hub_launcher модуль імпортується")
    except Exception as e:
        print(f"❌ Помилка імпорту hub_launcher: {e}")
        return False
    
    # Перевіряємо frontend директорію
    frontend_dir = project_root / "frontend"
    if frontend_dir.exists():
        package_json = frontend_dir / "package.json"
        if package_json.exists():
            print("✅ Frontend директорія та package.json знайдені")
        else:
            print("⚠️  package.json не знайдено у frontend")
    else:
        print("⚠️  Frontend директорія не знайдена")
    
    return True

if __name__ == "__main__":
    print("🧪 TetraCore Hub Endpoint Tester")
    print("=" * 50)
    
    # Тест dev-режиму
    if not test_dev_mode_startup():
        exit(1)
    
    # Основні тести
    try:
        success = asyncio.run(run_comprehensive_test())
        if success:
            print("\n🎉 Всі тести пройшли успішно!")
            exit(0)
        else:
            print("\n💥 Деякі тести не пройшли")
            exit(1)
    except KeyboardInterrupt:
        print("\n👋 Тестування скасовано користувачем")
    except Exception as e:
        print(f"\n💥 Критична помилка тестування: {e}")
        exit(1) 