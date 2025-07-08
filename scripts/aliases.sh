#!/bin/bash
# TetraCore StreamHub - Bash Aliases
# Додайте цей файл до вашого ~/.bashrc або ~/.zshrc для швидкого доступу

# Основні команди запуску
alias hub-dev='python hub_launcher.py dev'
alias hub-fast='python hub_launcher.py fast'
alias hub-prod='python hub_launcher.py prod'
alias hub-build='python hub_launcher.py build'

# Команди з опціями
alias hub-dev-v='python hub_launcher.py dev --verbose'
alias hub-prod-force='python hub_launcher.py prod --force-build'
alias hub-prod-quiet='python hub_launcher.py prod --no-banner'

# Shortcuts для розробки
alias hub-start='hub-dev'
alias hub-server='hub-fast'
alias hub-deploy='hub-prod'

# Утиліти
alias hub-help='python hub_launcher.py --help'
alias hub-clean='rm -rf frontend/build/ frontend/node_modules/ static/ __pycache__/ core/__pycache__/'
alias hub-install='pip install -r requirements.txt && cd frontend && npm install && cd ..'
alias hub-update='pip install --upgrade -r requirements.txt && cd frontend && npm update && cd ..'

# Логи та моніторинг
alias hub-logs='tail -f logs/*.log'
alias hub-status='curl -s http://localhost:8000/health | jq'
alias hub-metrics='curl -s http://localhost:8000/metrics'

# Тестування
alias hub-test-dev='timeout 10 hub-dev || echo "Dev mode test completed"'
alias hub-test-fast='timeout 10 hub-fast || echo "Fast mode test completed"'
alias hub-test-all='hub-build && hub-test-dev && hub-test-fast'

# Git shortcuts для проекту
alias hub-git-status='git status'
alias hub-git-add='git add .'
alias hub-git-commit='git commit -m'
alias hub-git-push='git push origin main'

# Docker shortcuts (якщо використовується)
alias hub-docker-build='docker build -t tetracore-streamhub .'
alias hub-docker-run='docker run -p 8000:8000 tetracore-streamhub'

# Функції для складніших операцій
hub-reset() {
    echo "🔄 Повне відновлення середовища..."
    hub-clean
    hub-install
    hub-build
    echo "✅ Середовище відновлено"
}

hub-demo() {
    echo "🎬 Демонстрація всіх режимів..."
    echo "1. Збірка..."
    hub-build
    echo "2. Fast режим (5 секунд)..."
    timeout 5 hub-fast &
    sleep 6
    echo "3. Production режим (показ банера)..."
    hub-prod --no-banner &
    sleep 3
    pkill -f "python hub_launcher.py" 2>/dev/null || true
    echo "✅ Демонстрація завершена"
}

hub-backup() {
    local backup_dir="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"
    cp .env "$backup_dir/.env.backup" 2>/dev/null || echo "No .env file found"
    cp -r frontend/src "$backup_dir/frontend_src" 2>/dev/null || echo "No frontend/src found"
    cp -r core "$backup_dir/core" 2>/dev/null || echo "No core directory found"
    echo "💾 Backup створено в $backup_dir"
}

hub-info() {
    echo "📊 TetraCore StreamHub - Інформація:"
    echo "  Версія Python: $(python --version)"
    echo "  Версія Node.js: $(node --version 2>/dev/null || echo 'Не встановлено')"
    echo "  Поточна директорія: $(pwd)"
    echo "  Розмір проекту: $(du -sh . --exclude=./venv --exclude=./frontend/node_modules 2>/dev/null | cut -f1)"
    echo "  Статус серверу: $(curl -s http://localhost:8000/health 2>/dev/null | jq -r '.status' || echo 'Не запущено')"
}

hub-ports() {
    echo "🔌 Перевірка портів:"
    echo "  Port 8000 (Backend): $(lsof -i :8000 2>/dev/null | grep LISTEN || echo 'Вільний')"
    echo "  Port 3000 (Frontend): $(lsof -i :3000 2>/dev/null | grep LISTEN || echo 'Вільний')"
    echo "  Port 6379 (Redis): $(lsof -i :6379 2>/dev/null | grep LISTEN || echo 'Вільний')"
}

hub-env() {
    echo "🌍 Змінні оточення:"
    echo "  ENVIRONMENT: ${ENVIRONMENT:-'не встановлено'}"
    echo "  DEBUG: ${DEBUG:-'не встановлено'}"
    echo "  PORT: ${PORT:-'не встановлено'}"
    echo "  REDIS_URL: ${REDIS_URL:-'не встановлено'}"
    echo "  NODE_ENV: ${NODE_ENV:-'не встановлено'}"
}

# Автокомплітуючі функції
_hub_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    opts="dev fast prod build --verbose --force-build --no-banner --help"

    case ${prev} in
        hub-launcher.py|python)
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
    esac

    COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
    return 0
}

# Реєстрація автокомплітування
complete -F _hub_completion hub-launcher.py
complete -F _hub_completion python

# Показати доступні команди
hub-aliases() {
    echo "🚀 TetraCore StreamHub - Доступні aliases:"
    echo ""
    echo "  Запуск:"
    echo "    hub-dev          - Development режим"
    echo "    hub-fast         - Fast режим"
    echo "    hub-prod         - Production режим"
    echo "    hub-build        - Збірка frontend"
    echo ""
    echo "  З опціями:"
    echo "    hub-dev-v        - Development з verbose"
    echo "    hub-prod-force   - Production з force-build"
    echo "    hub-prod-quiet   - Production без банера"
    echo ""
    echo "  Shortcuts:"
    echo "    hub-start        - Швидкий старт (dev)"
    echo "    hub-server       - Швидкий сервер (fast)"
    echo "    hub-deploy       - Deployment (prod)"
    echo ""
    echo "  Утиліти:"
    echo "    hub-clean        - Очищення build файлів"
    echo "    hub-install      - Встановлення залежностей"
    echo "    hub-reset        - Повне відновлення"
    echo "    hub-backup       - Створення backup"
    echo "    hub-info         - Інформація про проект"
    echo "    hub-ports        - Перевірка портів"
    echo "    hub-env          - Змінні оточення"
    echo ""
    echo "  Для інсталяції додайте до ~/.bashrc:"
    echo "    source $(pwd)/scripts/aliases.sh"
}

# Показати aliases при завантаженні
echo "🌊 TetraCore StreamHub aliases завантажено!"
echo "Використовуйте 'hub-aliases' для перегляду всіх команд"
