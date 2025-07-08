# Hub Launcher - Об'єднаний безпечний лаунчер для TetraCore StreamHub

## 📋 Огляд

`hub_launcher.py` - це новий об'єднаний лаунчер для TetraCore StreamHub, який поєднує функціональність `start_hub.py` та безпекові можливості `secure_launcher.py` в одному файлі. Цей лаунчер забезпечує універсальний та безпечний спосіб запуску StreamHub в різних режимах.

## ✨ Особливості

### 🔒 Безпека
- **Валідація шляхів**: Всі шляхи перевіряються через клас `SecurePath`
- **Безпечне виконання команд**: Клас `SecureCommand` валідує всі команди перед виконанням
- **Обмеження ресурсів**: Автоматичне обмеження CPU, пам'яті та кількості процесів
- **Безпечне оточення**: Фільтрація небезпечних змінних оточення
- **Таймаути**: Автоматичні таймаути для всіх операцій

### 🚀 Функціональність
- **Універсальність**: Підтримка dev, fast, prod та build режимів
- **Автоматична збірка**: Інтелектуальна перевірка необхідності перебудови frontend
- **Hot reload**: Підтримка hot reload в development режимі
- **Оптимізована збірка**: Production-ready збірка з відключеними source maps

## 📖 Використання

### Базові команди

```bash
# Development режим (за замовчуванням)
python hub_launcher.py
python hub_launcher.py dev

# Fast режим - швидкий запуск тільки backend
python hub_launcher.py fast

# Production режим - повна збірка та оптимізація
python hub_launcher.py prod

# Тільки збірка frontend
python hub_launcher.py build
```

### Додаткові опції

```bash
# Детальні логи
python hub_launcher.py dev --verbose
python hub_launcher.py dev -v

# Примусова перебудова frontend
python hub_launcher.py prod --force-build

# Без банера
python hub_launcher.py dev --no-banner
```

## 🔧 Режими роботи

### Development режим (`dev`)
- Hot reload для backend та frontend
- Debug логування
- Frontend development server на порту 3000
- Backend API на порту 8000
- Автоматичне відкриття браузера

```bash
python hub_launcher.py dev
```

### Fast режим (`fast`)
- Швидкий запуск тільки backend
- Використовує існуючу збірку frontend (якщо є)
- Без hot reload
- Мінімальні логи

```bash
python hub_launcher.py fast
```

### Production режим (`prod`)
- Повна збірка frontend з оптимізаціями
- Статичні файли сервуються з /static
- Production налаштування безпеки
- Мінімальні логи

```bash
python hub_launcher.py prod
```

### Build режим (`build`)
- Тільки збірка frontend без запуску серверів
- Корисно для CI/CD pipeline

```bash
python hub_launcher.py build
```

## 🔄 Міграція зі старих лаунчерів

### З `start_hub.py`
Старі команди автоматично працюватимуть:
```bash
# Замість
python start_hub.py dev

# Використовуйте
python hub_launcher.py dev
```

### З `secure_launcher.py`
Всі безпекові функції тепер інтегровані:
```bash
# Замість
python secure_launcher.py --dev

# Використовуйте
python hub_launcher.py dev
```

## 🛡️ Безпекові особливості

### Валідація шляхів
- Перевірка на path traversal атаки
- Обмеження довжини шляхів
- Блокування небезпечних компонентів (.git, __pycache__, тощо)

### Безпечне виконання команд
- Whitelist дозволених команд (node, npm, npx)
- Валідація npm scripts
- Автоматичне екранування аргументів
- Обмеження довжини команд

### Обмеження ресурсів (Unix/Linux)
- CPU час: максимум 5 хвилин
- Пам'ять: максимум 1GB
- Кількість процесів: максимум 100

### Безпечне оточення
- Фільтрація небезпечних змінних (LD_PRELOAD, PYTHONPATH)
- Дозвіл тільки безпечних змінних
- Автоматичне встановлення безпечних значень

## 📝 Приклади використання

### Розробка з детальними логами
```bash
python hub_launcher.py dev --verbose
```

### Production запуск з примусовою перебудовою
```bash
python hub_launcher.py prod --force-build
```

### Швидкий запуск для тестування API
```bash
python hub_launcher.py fast
```

### CI/CD збірка
```bash
# В CI/CD pipeline
python hub_launcher.py build
if [ $? -eq 0 ]; then
    echo "Build successful"
    python hub_launcher.py prod
else
    echo "Build failed"
    exit 1
fi
```

## 🐛 Розв'язання проблем

### Node.js не знайдено
```bash
# Перевірте наявність Node.js
node --version

# Встановіть Node.js якщо потрібно
# Ubuntu/Debian
sudo apt-get install nodejs npm

# macOS
brew install node
```

### Помилка збірки frontend
```bash
# Очистіть кеш npm
npm cache clean --force

# Видаліть node_modules та перевстановіть
rm -rf frontend/node_modules
python hub_launcher.py dev
```

### Порт вже використовується
```bash
# Знайдіть процес на порту
lsof -i :8000

# Або використайте інший порт
PORT=8001 python hub_launcher.py dev
```

## 📊 Змінні оточення

Лаунчер автоматично налаштовує необхідні змінні оточення:

| Змінна | Development | Production | Опис |
|--------|-------------|------------|------|
| ENVIRONMENT | development | production | Режим роботи |
| DEBUG | true | false | Debug режим |
| LOG_LEVEL | INFO | WARNING | Рівень логування |
| NODE_ENV | development | production | Node.js оточення |
| CI | false | true | CI режим для npm |

## 🔗 Пов'язані файли

- `start_hub.py` - Застарілий лаунчер (wrapper для hub_launcher.py)
- `secure_launcher.py` - Застарілий безпечний лаунчер (wrapper для hub_launcher.py)
- `config.py` - Конфігурація додатку
- `main.py` - Головний FastAPI додаток

## 📚 Додаткова інформація

Для детальної інформації про архітектуру StreamHub та API документацію, дивіться:
- [README.md](../README.md)
- [API Documentation](./api.md)
- [Architecture Overview](./architecture.md)