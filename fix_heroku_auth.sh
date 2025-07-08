#!/bin/bash

# TetraCore Hub - Виправлення автентифікації на Heroku
# Цей скрипт автоматично налаштовує всі необхідні секрети для авторизації

echo "🔧 Виправлення автентифікації TetraCore Hub на Heroku"
echo "="*60

# Перевірка наявності Heroku CLI
if ! command -v heroku &> /dev/null; then
    echo "❌ Heroku CLI не знайдено!"
    echo "   Встановіть Heroku CLI: https://devcenter.heroku.com/articles/heroku-cli"
    exit 1
fi

# Перевірка авторизації
echo "🔍 Перевірка авторизації Heroku..."
if ! heroku auth:whoami &> /dev/null; then
    echo "❌ Не авторизований в Heroku!"
    echo "   Виконайте: heroku login"
    exit 1
fi

echo "✅ Авторизація Heroku - OK"
echo

# Запуск скрипта налаштування
echo "🚀 Запуск скрипта налаштування секретів..."
cd "$(dirname "$0")"

if [ -f "setup_heroku_secrets.py" ]; then
    python3 setup_heroku_secrets.py
else
    echo "❌ Файл setup_heroku_secrets.py не знайдено!"
    exit 1
fi

echo
echo "✅ Скрипт завершено!"
echo "🌐 Перевірте ваш додаток на https://hub.tetra-core.website"
echo "📝 Дані для входу збережені в admin_credentials.txt"
echo
echo "🔧 Якщо все ще є проблеми, перезапустіть додаток:"
echo "   heroku restart --app НАЗВА_ДОДАТКУ" 