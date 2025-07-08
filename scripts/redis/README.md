# Redis Scripts для TetraCore Stream Hub

Цей каталог містить утиліти для роботи з Redis в TetraCore Stream Hub.

## Скрипти

### 1. monitor_memory.py - Моніторинг пам'яті Redis

Автоматичний моніторинг використання пам'яті Redis та очищення старих даних.

#### Функції:
- 📊 Моніторинг використання пам'яті в реальному часі
- 🧹 Автоматичне очищення старих даних за паттернами
- ⏰ Встановлення TTL для ключів без експірації
- 📈 Збір статистики очищення
- 🚨 Попередження при перевищенні порогу пам'яті

#### Використання:

```bash
# Базовий запуск
python scripts/redis/monitor_memory.py

# З кастомними налаштуваннями через змінні середовища
REDIS_URL=redis://localhost:6379 python scripts/redis/monitor_memory.py

# Запуск як фоновий процес
nohup python scripts/redis/monitor_memory.py > redis_monitor.log 2>&1 &
```

#### Конфігурація:

Скрипт використовує налаштування з `config.py` та змінні середовища:

- `REDIS_URL` - URL підключення до Redis
- `REDIS_CLEANUP_INTERVAL` - інтервал перевірки (секунди, за замовчуванням 3600)
- `REDIS_DEFAULT_TTL` - дефолтний TTL для ключів (секунди, за замовчуванням 86400)

#### Паттерни очищення:

| Паттерн | TTL (дні) | Опис |
|---------|-----------|------|
| `tetra:tasks:*` | 7 | Завдання зберігаються тиждень |
| `tetra:results:*` | 3 | Результати зберігаються 3 дні |
| `tetra:metrics:*` | 1 | Метрики зберігаються день |
| `tetra:temp:*` | 0.25 | Тимчасові дані - 6 годин |
| `session:*` | 30 | Сесії зберігаються місяць |

### 2. benchmark.py - Бенчмаркінг продуктивності

Комплексний тест продуктивності Redis для різних операцій та конфігурацій.

#### Функції:
- 🚀 Тестування SET/GET операцій
- 📦 Тестування Pipeline batch операцій
- 📡 Тестування Pub/Sub продуктивності
- ⚡ Тестування конкурентних операцій
- ⏱️ Тестування операцій з TTL
- 🔍 Тестування SCAN операцій
- 📊 Детальні метрики (latency percentiles, throughput)

#### Використання:

```bash
# Базовий запуск (10,000 операцій, 1KB дані)
python scripts/redis/benchmark.py

# З кастомними параметрами
python scripts/redis/benchmark.py --operations 50000 --data-size 2048

# Короткі опції
python scripts/redis/benchmark.py -o 100000 -s 512

# Тестування різних режимів Redis
python scripts/redis/benchmark.py --mode standalone
python scripts/redis/benchmark.py --mode sentinel
python scripts/redis/benchmark.py --mode cluster

# З кастомним Redis URL
python scripts/redis/benchmark.py --redis-url redis://user:pass@host:6379
```

#### Параметри:

- `-o, --operations` - кількість операцій для тесту (за замовчуванням 10000)
- `-s, --data-size` - розмір тестових даних в байтах (за замовчуванням 1024)
- `-r, --redis-url` - URL підключення до Redis (перевизначає конфігурацію)
- `-m, --mode` - режим Redis для тестування (standalone/sentinel/cluster)

#### Вивід результатів:

```
REDIS BENCHMARK RESULTS
================================================================================
Redis Mode: standalone
Pipeline Enabled: True
================================================================================
Operation                           Total Ops   Time (s)    Ops/sec   Avg (ms)   P95 (ms)   P99 (ms)
----------------------------------- ---------- ---------- ---------- ---------- ---------- ----------
SET                                      10000       2.14    4673.36       0.21       0.35       0.52
GET                                      10000       1.89    5291.01       0.19       0.31       0.45
Pipeline (batch=100)                     10000       0.22   45454.55       0.02       0.04       0.06
Pub/Sub                                  10000       1.12    8928.57       0.11       0.18       0.25
Concurrent (workers=50)                  10000       0.43   23255.81       2.15       3.82       4.91
```

Результати також зберігаються в JSON файл: `redis_benchmark_YYYYMMDD_HHMMSS.json`

## Вимоги

```bash
# Встановіть залежності
pip install redis[hiredis] structlog click
```

## Запуск як служби

### Використання systemd:

```ini
# /etc/systemd/system/tetracore-redis-monitor.service
[Unit]
Description=TetraCore Redis Memory Monitor
After=network.target redis.service

[Service]
Type=simple
User=tetracore
WorkingDirectory=/path/to/tetra-core-hub
ExecStart=/usr/bin/python3 scripts/redis/monitor_memory.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Активація служби
sudo systemctl enable tetracore-redis-monitor
sudo systemctl start tetracore-redis-monitor
sudo systemctl status tetracore-redis-monitor
```

### Використання supervisor:

```ini
# /etc/supervisor/conf.d/redis-monitor.conf
[program:redis-monitor]
command=python3 /path/to/scripts/redis/monitor_memory.py
directory=/path/to/tetra-core-hub
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/redis-monitor.err.log
stdout_logfile=/var/log/supervisor/redis-monitor.out.log
user=tetracore
```

## Приклади використання

### Періодичний бенчмаркінг через cron:

```bash
# Додайте в crontab
0 */6 * * * cd /path/to/tetra-core-hub && python3 scripts/redis/benchmark.py -o 5000 >> /var/log/redis-benchmark.log 2>&1
```

### Моніторинг з алертами:

```python
# Приклад інтеграції з системою алертів
import subprocess
import json

# Запуск бенчмарку
result = subprocess.run(['python3', 'scripts/redis/benchmark.py', '-o', '1000'],
                       capture_output=True, text=True)

# Перевірка результатів
if "Ops/sec" in result.stdout:
    lines = result.stdout.split('\n')
    for line in lines:
        if "SET" in line and "Ops/sec" in line:
            ops_per_sec = float(line.split()[3])
            if ops_per_sec < 1000:
                # Відправити алерт
                send_alert("Redis performance degraded: {} ops/sec".format(ops_per_sec))
```

## Troubleshooting

### Проблема: Connection refused

```bash
# Перевірте чи працює Redis
redis-cli ping

# Перевірте URL підключення
echo $REDIS_URL
```

### Проблема: Permission denied

```bash
# Переконайтеся що є права на виконання
chmod +x scripts/redis/*.py

# Перевірте права на лог файли
ls -la /var/log/
```

### Проблема: High memory usage

```bash
# Запустіть монітор з форсованим очищенням
python scripts/redis/monitor_memory.py --force-cleanup

# Перевірте Redis конфігурацію
redis-cli CONFIG GET maxmemory
redis-cli CONFIG GET maxmemory-policy
```

## Розробка

### Додавання нових паттернів очищення:

```python
# В monitor_memory.py
self.cleanup_patterns = [
    ("tetra:tasks:*", 7),
    ("tetra:results:*", 3),
    ("your:pattern:*", 1),  # Додайте свій паттерн
]
```

### Додавання нових бенчмарків:

```python
# В benchmark.py
async def _benchmark_custom(self, operations: int):
    """Ваш кастомний бенчмарк"""
    # Реалізація
    pass

# Додайте виклик в run_benchmarks()
await self._benchmark_custom(operations)
```
