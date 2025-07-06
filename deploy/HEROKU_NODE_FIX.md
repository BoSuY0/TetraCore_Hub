# Вирішення проблеми "Node.js не знайдено в PATH" на Heroku

## Опис проблеми

При деплої TetraCore Hub на Heroku виникає помилка:
```
❌ Node.js не знайдено в PATH
```

Це відбувається тому, що:
1. Heroku використовує buildpack'и для збірки додатку
2. Node.js buildpack запускається першим і збирає frontend
3. Python buildpack запускається другим і запускає сервер
4. Під час виконання Python коду, Node.js вже не доступний в PATH

## Рішення

### 1. Правильне налаштування Buildpack'ів

Переконайтеся, що у вашому Heroku додатку налаштовані обидва buildpack'и в правильному порядку:

```bash
# Перевірити поточні buildpack'и
heroku buildpacks -a your-app-name

# Очистити і встановити правильно
heroku buildpacks:clear -a your-app-name
heroku buildpacks:add heroku/nodejs -a your-app-name
heroku buildpacks:add heroku/python -a your-app-name
```

Або використайте наш скрипт:
```bash
./deploy/setup_heroku.sh
```

### 2. Налаштування збірки Frontend

Frontend має збиратися під час деплою, а не під час запуску сервера.

**package.json** (кореневий):
```json
{
  "scripts": {
    "heroku-prebuild": "echo 'Installing frontend dependencies...' && cd frontend && npm install",
    "heroku-postbuild": "echo 'Building frontend...' && cd frontend && npm run build && echo 'Frontend built successfully'"
  }
}
```

### 3. Оновлення start_hub.py

Ми оновили `start_hub.py` щоб він:
- Не намагався перевіряти Node.js в production режимі, якщо frontend вже зібраний
- Використовував існуючу збірку замість спроби перезбирати

Ключові зміни:
```python
# В production режимі перевіряємо чи frontend вже зібраний
if force_build or not (self.static_dir.exists() and (self.static_dir / "index.html").exists()):
    if not self.build_frontend(force=force_build):
        print("⚠️  Продовжуємо без frontend")
else:
    print("✅ Використовуємо існуючу збірку frontend")
```

### 4. Структура файлів

Переконайтеся, що маєте всі необхідні файли:

```
tetra-core-hub/
├── .buildpacks          # Визначає buildpack'и (для старих версій Heroku)
├── package.json         # Кореневий package.json з heroku-postbuild
├── requirements.txt     # Python залежності
├── runtime.txt         # Python версія
├── Procfile            # Команда запуску
├── app.json            # Конфігурація Heroku app
├── frontend/
│   ├── package.json    # Frontend залежності
│   └── src/            # Frontend код
└── static/             # Зібраний frontend (створюється автоматично)
```

### 5. Перевірка деплою

Після деплою перевірте:

```bash
# Логи збірки
heroku logs --tail -a your-app-name

# Перевірити змінні середовища
heroku config -a your-app-name

# Перезапустити додаток якщо потрібно
heroku restart -a your-app-name
```

## Альтернативні рішення

### Варіант А: Попередньо зібраний Frontend

Якщо buildpack'и не працюють, можна зібрати frontend локально і закомітити:

```bash
cd frontend
npm install
npm run build
cd ..
cp -r frontend/build/* static/
git add static/
git commit -m "Add prebuilt frontend"
git push heroku main
```

### Варіант Б: Використання Docker

Створити `Dockerfile` з multi-stage build:

```dockerfile
# Stage 1: Build frontend
FROM node:18 as frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python app
FROM python:3.11
WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
COPY --from=frontend-builder /app/frontend/build ./static
CMD ["python", "start_hub.py", "prod"]
```

## Діагностика

Якщо проблема залишається:

1. Перевірте версію Node.js в `engines` секції package.json
2. Переконайтеся що `heroku-postbuild` скрипт виконується (дивіться логи збірки)
3. Перевірте чи файли frontend копіюються в правильну директорію
4. Використайте `heroku run bash` для дослідження файлової системи

## Контакти для підтримки

Якщо потрібна додаткова допомога:
- Створіть issue в репозиторії проекту
- Перевірте Heroku документацію: https://devcenter.heroku.com/articles/using-multiple-buildpacks-for-an-app