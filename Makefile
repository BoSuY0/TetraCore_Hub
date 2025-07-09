# TetraCore StreamHub - Makefile
# Основні команди для запуску та управління

.PHONY: help dev fast prod build clean install test diagnose

# За замовчуванням показуємо help
.DEFAULT_GOAL := help

# Показати доступні команди
help:
	@echo "TetraCore StreamHub - Доступні команди:"
	@echo ""
	@echo "  🚀 ЗАПУСК:"
	@echo "    dev          - Development режим з hot reload"
	@echo "    fast         - Швидкий запуск backend"
	@echo "    prod         - Production режим"
	@echo "    main         - Простий запуск (замість main.py)"
	@echo ""
	@echo "  🔧 ЗБІРКА:"
	@echo "    build        - Збірка frontend"
	@echo "    install      - Встановлення залежностей"
	@echo "    clean        - Очищення build файлів"
	@echo ""
	@echo "  🧪 ІНСТРУМЕНТИ:"
	@echo "    test         - Швидкі тести"
	@echo "    diagnose     - Діагностика середовища"
	@echo ""
	@echo "Приклади:"
	@echo "  make dev     # Development режим"
	@echo "  make prod    # Production запуск"

# === ОСНОВНІ РЕЖИМИ ЗАПУСКУ ===

# Development режим
dev:
	@echo "🔧 Запуск в development режимі..."
	python hub_launcher.py dev --verbose

# Fast режим
fast:
	@echo "⚡ Швидкий запуск..."
	python hub_launcher.py fast

# Production режим
prod:
	@echo "🚀 Production запуск..."
	python hub_launcher.py prod

# Main режим (замість main.py)
main:
	@echo "🚀 Простий запуск..."
	python hub_launcher.py main

# === ЗБІРКА ТА ВСТАНОВЛЕННЯ ===

# Збірка frontend
build:
	@echo "🔨 Збірка frontend..."
	python hub_launcher.py build

# Встановлення залежностей
install:
	@echo "📦 Встановлення залежностей..."
	@if [ -f requirements.txt ]; then \
		pip install -r requirements.txt; \
	fi
	@if [ -d frontend ] && [ -f frontend/package.json ]; then \
		cd frontend && npm install; \
	fi

# Очищення
clean:
	@echo "🧹 Очищення..."
	@rm -rf frontend/build/ 2>/dev/null || true
	@rm -rf frontend/node_modules/ 2>/dev/null || true
	@rm -rf static/ 2>/dev/null || true
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "✅ Очищення завершено"

# === ІНСТРУМЕНТИ ===

# Швидкі тести
test:
	@echo "🧪 Запуск тестів..."
	@if [ -f scripts/quick_test.py ]; then \
		python scripts/quick_test.py; \
	else \
		echo "⚠️ Тестові скрипти не знайдені"; \
	fi

# Діагностика середовища
diagnose:
	@echo "🔍 Діагностика середовища..."
	python hub_launcher.py diagnose

# === СЕРВІСНІ КОМАНДИ ===

# Повна перебудова
rebuild: clean install build
	@echo "✅ Повна перебудова завершена"

# Перевірка статусу
status:
	@echo "📊 Статус проекту:"
	@echo "Python файли: $$(find . -name '*.py' -not -path './venv/*' -not -path './frontend/*' | wc -l)"
	@if [ -d frontend/src ]; then \
		echo "Frontend файли: $$(find frontend/src -name '*.ts' -o -name '*.tsx' | wc -l)"; \
	fi
	@echo "Розмір: $$(du -sh . --exclude=./venv --exclude=./frontend/node_modules 2>/dev/null | cut -f1 || echo 'невідомо')"
