# TetraCore StreamHub - Makefile
# Shortcuts для hub_launcher.py

.PHONY: help dev fast prod build clean install test test-full test-help test-build test-fast test-prod test-dev lint format

# Показати доступні команди
help:
	@echo "TetraCore StreamHub - Доступні команди:"
	@echo ""
	@echo "  dev          - Запуск в development режимі з hot reload"
	@echo "  fast         - Швидкий запуск тільки backend"
	@echo "  prod         - Production запуск з повною збіркою"
	@echo "  build        - Збірка frontend без запуску"
	@echo "  clean        - Очищення build файлів"
	@echo "  install      - Встановлення всіх залежностей"
	@echo "  test         - Швидкий тест лаунчера"
	@echo "  test-full    - Повний тест всіх режимів"
	@echo "  test-help    - Тест --help"
	@echo "  test-build   - Тест build режиму"
	@echo "  test-fast    - Тест fast режиму"
	@echo "  test-prod    - Тест prod режиму"
	@echo "  test-dev     - Тест dev режиму"
	@echo "  lint         - Перевірка коду"
	@echo "  format       - Форматування коду"
	@echo ""
	@echo "Приклади:"
	@echo "  make dev           # Development режим"
	@echo "  make prod          # Production режим"
	@echo "  make build         # Тільки збірка"

# Development режим
dev:
	@echo "🔧 Запуск в development режимі..."
	python hub_launcher.py dev --verbose

# Fast режим
fast:
	@echo "⚡ Швидкий запуск backend..."
	python hub_launcher.py fast

# Production режим
prod:
	@echo "🚀 Production запуск..."
	python hub_launcher.py prod

# Збірка frontend
build:
	@echo "🔨 Збірка frontend..."
	python hub_launcher.py build

# Примусова перебудова
rebuild:
	@echo "🔄 Примусова перебудова..."
	python hub_launcher.py prod --force-build

# Очищення build файлів
clean:
	@echo "🧹 Очищення build файлів..."
	rm -rf frontend/build/
	rm -rf frontend/node_modules/
	rm -rf static/
	rm -rf __pycache__/
	rm -rf core/__pycache__/
	rm -rf utils/__pycache__/
	rm -rf models/__pycache__/
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Встановлення залежностей
install:
	@echo "📦 Встановлення Python залежностей..."
	pip install -r requirements.txt
	@echo "📦 Встановлення Node.js залежностей..."
	cd frontend && npm install

# Оновлення залежностей
update:
	@echo "🔄 Оновлення залежностей..."
	pip install --upgrade -r requirements.txt
	cd frontend && npm update

# Тестування
test:
	@echo "🧪 Запуск швидкого тесту..."
	python scripts/quick_test.py

# Повний тест
test-full:
	@echo "🧪 Запуск повного тесту..."
	python scripts/test_launcher.py

# Тест конкретного режиму
test-help:
	@echo "🧪 Тест --help..."
	python scripts/test_launcher.py --test help

test-build:
	@echo "🧪 Тест build режиму..."
	python scripts/test_launcher.py --test build

test-fast:
	@echo "🧪 Тест fast режиму..."
	python scripts/test_launcher.py --test fast

test-prod:
	@echo "🧪 Тест prod режиму..."
	python scripts/test_launcher.py --test prod

test-dev:
	@echo "🧪 Тест dev режиму..."
	python scripts/test_launcher.py --test dev

# Перевірка коду
lint:
	@echo "🔍 Перевірка Python коду..."
	flake8 . --exclude=venv,frontend,static
	@echo "🔍 Перевірка TypeScript коду..."
	cd frontend && npm run lint

# Форматування коду
format:
	@echo "📝 Форматування Python коду..."
	black . --exclude=venv
	@echo "📝 Форматування TypeScript коду..."
	cd frontend && npm run format

# Перевірка безпеки
security:
	@echo "🔒 Перевірка безпеки..."
	safety check
	cd frontend && npm audit

# Backup конфігурації
backup:
	@echo "💾 Створення backup..."
	mkdir -p backups
	cp .env backups/.env.backup.$(shell date +%Y%m%d_%H%M%S)
	cp -r frontend/src backups/frontend_src.backup.$(shell date +%Y%m%d_%H%M%S)

# Відновлення після помилок
reset:
	@echo "🔄 Відновлення середовища..."
	$(MAKE) clean
	$(MAKE) install
	$(MAKE) build

# Демонстрація всіх режимів
demo:
	@echo "🎬 Демонстрація всіх режимів..."
	@echo "1. Збірка frontend..."
	python hub_launcher.py build
	@echo "2. Fast режим (5 секунд)..."
	timeout 5 python hub_launcher.py fast || true
	@echo "3. Production режим (показ банера)..."
	python hub_launcher.py prod --no-banner &
	sleep 2
	pkill -f "python hub_launcher.py" || true
	@echo "✅ Демонстрація завершена"

# Розгортання
deploy:
	@echo "🚀 Підготовка до розгортання..."
	$(MAKE) clean
	$(MAKE) install
	$(MAKE) build
	@echo "✅ Готово до розгортання"

# Розробка з автоматичним перезапуском
watch:
	@echo "👀 Моніторинг змін файлів..."
	while true; do \
		inotifywait -e modify -r . --exclude='(frontend/node_modules|venv|__pycache__|\.git)' && \
		echo "🔄 Зміни виявлені, перезапуск..." && \
		pkill -f "python hub_launcher.py" || true && \
		sleep 1 && \
		python hub_launcher.py dev & \
	done

# Статистика проекту
stats:
	@echo "📊 Статистика проекту:"
	@echo "Python файли: $(shell find . -name '*.py' -not -path './venv/*' -not -path './frontend/*' | wc -l)"
	@echo "TypeScript файли: $(shell find frontend/src -name '*.ts' -o -name '*.tsx' | wc -l)"
	@echo "Рядки Python коду: $(shell find . -name '*.py' -not -path './venv/*' -not -path './frontend/*' -exec wc -l {} + | tail -1 | awk '{print $$1}')"
	@echo "Розмір проекту: $(shell du -sh . --exclude=./venv --exclude=./frontend/node_modules | cut -f1)"

# За замовчуванням показуємо help
.DEFAULT_GOAL := help
