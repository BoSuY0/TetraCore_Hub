#!/bin/bash

# TetraCore Hub - Heroku Buildpacks Setup Script
# Цей скрипт налаштовує правильні buildpack'и для деплою на Heroku

echo "🚀 TetraCore Hub - Налаштування Heroku Buildpacks"
echo "================================================="

# Перевіряємо чи встановлений Heroku CLI
if ! command -v heroku &> /dev/null; then
    echo "❌ Heroku CLI не встановлено!"
    echo "📦 Встановіть його з: https://devcenter.heroku.com/articles/heroku-cli"
    exit 1
fi

# Перевіряємо чи ми в правильній директорії
if [ ! -f "package.json" ] || [ ! -f "requirements.txt" ]; then
    echo "❌ Цей скрипт потрібно запускати з кореневої директорії tetra-core-hub!"
    exit 1
fi

# Отримуємо ім'я додатку Heroku
echo ""
echo "📝 Введіть назву вашого Heroku додатку (наприклад: tetra-core-hub):"
read -p "Назва додатку: " APP_NAME

if [ -z "$APP_NAME" ]; then
    echo "❌ Назва додатку не може бути порожньою!"
    exit 1
fi

echo ""
echo "🔧 Налаштовуємо buildpack'и для $APP_NAME..."

# Очищаємо існуючі buildpack'и
echo "🧹 Очищаємо існуючі buildpack'и..."
heroku buildpacks:clear -a "$APP_NAME"

# Додаємо buildpack'и в правильному порядку
echo "📦 Додаємо Node.js buildpack..."
heroku buildpacks:add heroku/nodejs -a "$APP_NAME"

echo "📦 Додаємо Python buildpack..."
heroku buildpacks:add heroku/python -a "$APP_NAME"

# Показуємо поточні buildpack'и
echo ""
echo "✅ Buildpack'и налаштовані! Поточний список:"
heroku buildpacks -a "$APP_NAME"

# Встановлюємо важливі змінні середовища
echo ""
echo "🔧 Встановлюємо змінні середовища..."

# Вимикаємо збір метрик npm (прискорює збірку)
heroku config:set NPM_CONFIG_PRODUCTION=true -a "$APP_NAME"

# Встановлюємо Node.js версію (опціонально)
echo ""
echo "📝 Бажаєте встановити специфічну версію Node.js? (за замовчуванням Heroku вибере сам)"
echo "Натисніть Enter щоб пропустити або введіть версію (наприклад: 18.x):"
read -p "Node.js версія: " NODE_VERSION

if [ ! -z "$NODE_VERSION" ]; then
    # Створюємо або оновлюємо .nvmrc файл
    echo "$NODE_VERSION" > .nvmrc
    echo "✅ Node.js версія встановлена: $NODE_VERSION"
fi

# Перевіряємо чи всі необхідні файли існують
echo ""
echo "🔍 Перевіряємо необхідні файли..."

MISSING_FILES=()

if [ ! -f ".buildpacks" ]; then
    MISSING_FILES+=(".buildpacks")
fi

if [ ! -f "runtime.txt" ]; then
    MISSING_FILES+=("runtime.txt")
fi

if [ ! -f "Procfile" ]; then
    MISSING_FILES+=("Procfile")
fi

if [ ${#MISSING_FILES[@]} -eq 0 ]; then
    echo "✅ Всі необхідні файли знайдено!"
else
    echo "⚠️  Відсутні файли: ${MISSING_FILES[*]}"
    echo "   Переконайтеся, що вони існують перед деплоєм!"
fi

# Показуємо наступні кроки
echo ""
echo "📋 Наступні кроки:"
echo "==================="
echo "1. Переконайтеся, що всі зміни закомічені:"
echo "   git add ."
echo "   git commit -m 'Configure Heroku buildpacks'"
echo ""
echo "2. Запушіть на Heroku:"
echo "   git push heroku main"
echo ""
echo "3. Перевірте логи збірки:"
echo "   heroku logs --tail -a $APP_NAME"
echo ""
echo "4. Якщо виникнуть проблеми, перевірте:"
echo "   - package.json має scripts.heroku-postbuild"
echo "   - frontend/package.json має script.build"
echo "   - static директорія включена в git (або .gitkeep файл)"
echo ""
echo "✅ Налаштування завершено!"
