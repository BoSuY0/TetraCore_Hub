# TetraCore Stream Hub

Централізований хаб для управління потоками завдань між Telegram ботами та воркерами.

## Основні можливості

- 🔌 WebSocket сервер для real-time комунікації
- 📊 Web dashboard для моніторингу
- 🔄 Автоматичне балансування навантаження
- 💾 Redis інтеграція для масштабування
- 🏭 Production-ready з підтримкою Heroku

## Швидкий старт

### Локальна розробка

```bash
# Встановлення залежностей
pip install -r requirements.txt

# Режим розробки (backend + frontend dev server)
python start_hub.py dev

# Швидкий режим (тільки backend)
python start_hub.py fast

# Production режим
python start_hub.py prod
```

### Режими запуску

- **dev** - Повний режим розробки з hot reload
- **fast** - Швидкий запуск без frontend dev server
- **prod** - Production режим з оптимізаціями

## Розгортання на Heroku

### 1. Підготовка

```bash
# Створіть новий додаток Heroku
heroku create your-app-name

# Встановіть buildpacks
heroku buildpacks:add heroku/python
heroku buildpacks:add heroku/nodejs

# Налаштуйте кастомний домен
heroku domains:add hub.tetra-core.website

# Додайте Redis
heroku addons:create heroku-redis:hobby-dev
```

### 2. Конфігурація змінних середовища

```bash
# Опціональні налаштування
heroku config:set LOG_LEVEL=INFO
heroku config:set AUTH_TOKEN=your-secret-token
```

### 3. Розгортання

```bash
# Push код на Heroku
git push heroku main

# Перевірка логів
heroku logs --tail
```

### 4. Діагностика

```bash
# Запустіть діагностичний скрипт для перевірки конфігурації
heroku run python diagnose_env.py
```

### 5. Кастомний домен

Хаб налаштований на використання кастомного домену `hub.tetra-core.website`.
Переконайтеся, що DNS записи правильно налаштовані для вашого домену.

## Конфігурація

### Змінні середовища

| Змінна | Опис | За замовчуванням |
|--------|------|------------------|
| `PORT` | Порт сервера | 8000 |
| `ENVIRONMENT` | Середовище (development/production) | development |
| `REDIS_URL` | URL для Redis | redis://localhost:6379 |
| `REDIS_ENABLED` | Увімкнути Redis | true (на Heroku) |
| `LOG_LEVEL` | Рівень логування | INFO |
| `AUTH_TOKEN` | Токен для аутентифікації клієнтів | - |

### Автоматичне визначення Heroku

Hub автоматично визначає що запущений на Heroku за наявністю змінної `DYNO`.
У production режимі використовується кастомний домен `hub.tetra-core.website`.

## API Endpoints

### WebSocket
- `/ws` - WebSocket endpoint для підключення клієнтів

### HTTP
- `/` - Головна сторінка (перенаправлення на dashboard)
- `/dashboard` - Web dashboard
- `/health` - Health check endpoint
- `/api/status` - Статус хабу та підключених клієнтів
- `/api/metrics` - Метрики системи

## Архітектура

```
┌─────────────┐     WebSocket      ┌─────────────┐
│ Telegram    │ ◄─────────────────► │             │
│ Bot         │                     │             │
└─────────────┘                     │             │
                                    │  StreamHub  │
┌─────────────┐     WebSocket      │             │
│ Worker      │ ◄─────────────────► │             │
│ (API)       │                     │             │
└─────────────┘                     └──────┬──────┘
                                           │
┌─────────────┐     WebSocket             │ Redis
│ Worker      │ ◄─────────────────►       │ Pub/Sub
│ (Tasks)     │                           ▼
└─────────────┘                     ┌─────────────┐
                                    │   Redis     │
                                    └─────────────┘
```

## Моніторинг

### Dashboard

Відкрийте `/dashboard` у браузері для доступу до:
- Статус підключених клієнтів
- Статистика завдань
- Метрики продуктивності
- Логи в реальному часі

### Health Check

```bash
# Локально
curl http://localhost:8000/health

# На Heroku з кастомним доменом
curl https://hub.tetra-core.website/health
```

## Розробка

### Структура проекту

```
tetra-core-hub/
├── core/               # Основні компоненти
│   ├── hub.py         # Головний клас StreamHub
│   ├── client_manager.py
│   ├── task_router.py
│   └── redis_manager.py
├── models/            # Моделі даних
├── web/              # Web endpoints
├── frontend/         # React dashboard
├── config.py         # Конфігурація
└── start_hub.py      # Точка входу
```

### Frontend розробка

```bash
cd frontend
npm install
npm run dev
```

## Усунення проблем

### URL кастомного домену

Хаб використовує кастомний домен `hub.tetra-core.website` замість стандартного Heroku URL.
Якщо виникають проблеми з доменом:

1. Перевірте налаштування DNS
2. Переконайтеся що домен додано до Heroku:
   ```bash
   heroku domains
   ```

### Redis connection failed

1. Перевірте що Redis addon додано:
   ```bash
   heroku addons | grep redis
   ```

2. Перевірте REDIS_URL:
   ```bash
   heroku config:get REDIS_URL
   ```

### Frontend не збудований

На Heroku frontend збирається автоматично при деплої.
Для локальної розробки:

```bash
# Режим розробки (автоматично запускає frontend dev server)
python start_hub.py dev

# Або збудуйте вручну
cd frontend && npm run build
```

## Ліцензія

MIT License