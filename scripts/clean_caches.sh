#!/usr/bin/env bash
set -euo pipefail

# Cross-platform friendly delete helper
rm_rf() {
  local target="$1"
  if [ -d "$target" ]; then
    rm -rf "$target" 2>/dev/null || true
  elif [ -f "$target" ]; then
    rm -f "$target" 2>/dev/null || true
  fi
}

echo "🧹 Cleaning caches..."

# Pytest / coverage
rm_rf .pytest_cache
rm_rf .hypothesis
rm_rf htmlcov
rm_rf .coverage

# Ruff / mypy
rm_rf .ruff_cache
rm_rf .mypy_cache

echo "✅ Caches cleaned"


