# План міграції TetraCore Hub на Rust

- [x] Ініціалізувати Rust workspace (`hub`, `tetra_core`, `models`, `tools`, `utils`)
- [x] HTTP сервер на Axum з `/api/health`
- [x] Базовий WebSocket `/ws` + автентифікація (Bearer, dev/test guest)
- [x] Менеджер безпеки: rate-limit IP/токена, nonce TTL, HMAC, JWT
- [x] Перевірка Origin у проді, ліміти зʼєднань/підписок
- [x] Split WebSocket (sink/stream), підписки `subscribe/unsubscribe`
- [ ] Роутинг WS-повідомлень: `task_submit`, `task_result`, `broadcast`
- [ ] Повідомлення/моделі: розширити `WsMessage` (metrics, error, client_registration)
- [ ] Дозволи: перевірки на канали (`tasks.view`, `tasks.execute`)
- [ ] Redis (необовʼязково): nonce/metrics/статуси з TTL, feature flag
- [ ] HTTP API: JWKS, diagnostics, базові dashboard JSON endpoints
- [ ] Конфіг: ENV → структури налаштувань; TLS `APP_TLS_CERT/KEY`, CORS
- [ ] Логування: `tracing` формат/фільтри, маскування секретів
- [ ] Тести: юніт/інтеграційні (HTTP/WS, ліміти, HMAC/JWT, підписки)
- [ ] CI: форматування, лінт, тести, релізні профілі

## ENV змінні (поточні)
- `ENVIRONMENT` (development/production)
- `WS_MAX_MESSAGE_SIZE` (байт), `WS_MAX_MESSAGES_PER_SECOND`
- `WS_MAX_CONNECTIONS_PER_USER`, `WS_MAX_SUBSCRIPTIONS`
- `WS_CONN_WINDOW_SECONDS`, `WS_MAX_ATTEMPTS_PER_MIN`, `WS_NONCE_TTL_SECONDS`
- `AUTH_TOKEN`, `AUTH_TOKEN_ACTIVE`, `AUTH_TOKEN_NEXT`, `HUB_AUTH_TOKEN`
- `AUTH_SECRET` (HS256) або `AUTH_PUBLIC_KEY_PEM` (RS256)
- `ALLOWED_ORIGINS` (CSV, напр. `https://app.example.com,https://admin.example.com`)
- `APP_TLS_CERT`, `APP_TLS_KEY`

## Нотатки реалізації
- Всі ліміти/перевірки зводимо у `tetra_core::ws::WebSocketSecurityManager`.
- `hub` тримає state менеджера й маршрутизує повідомлення, працює через mpsc.
- Redis інтегрується за feature й фолбекиться на in-memory.
