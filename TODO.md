# План міграції з Python на Rust для TetraCore Hub

Цей документ описує повний і детальний план переписування функціоналу StreamHub з Python на Rust. Завдання згруповані по підсистемах, із конкретними кроками реалізації, орієнтовними інтерфейсами та вимогами до сумісності з існуючим фронтендом і клієнтами. Мета — поступова заміна Python‑модулів без втрати функціоналу й сумісності протоколу.

## 1. WebSocket‑ядро (Axum + tungstenite)

- Підсистема: `rust/hub` (Axum, HTTP + WS), модуль безпеки `rust/hub/src/ws.rs`.
- Поточний стан: базове ядро готове, є аутентифікація (JWT/статичні токени), HMAC‑handshake у prod, rate‑limit, підписки/бродкаст, парсинг повідомлень, часткова статистика.

Завдання:
- [x] Підтримка `permessage-deflate` (вмикається через tungstenite features).
- [x] Heartbeat: сервісні `ping` з інтервалом `WS_HEARTBEAT_INTERVAL` (деф. 30s).
- [x] Оновлення активності на `Ping/Pong` (touch).
- [x] Таймаут неактивності рідера `WS_IDLE_TIMEOUT_SECONDS` (деф. 120s) з автоматичним відправленням Close‑frame (reason: `idle_timeout`) і від’єднанням.
- [x] Нагадування про реєстрацію: якщо клієнт не надіслав `client_registration` за `WS_REGISTRATION_TIMEOUT_SECONDS` — попереджувальне повідомлення.
- [x] Метрики: лічильники підписок/відписок/бродкастів/помилок (див. розділ 7).
- [ ] Backpressure: 
  - [x] Обмеження вхідних повідомлень на клієнта (`WS_MAX_INFLIGHT`, деф. 8–32). — реалізовано bounded outbox + try_send, метрики `errors_backpressure_total`.
  - [ ] Черга очікування для перевантажених клієнтів (механізм «дозволь надіслати, коли інфлайт звільниться»).
  - [x] Ліміт розміру повідомлення (`WS_MAX_MESSAGE_SIZE`) — вже є, додати м’яке «429 Too Many WS Messages» (JSON‑подія) перед Close, якщо перевищення стабільне.
- [x] Гейт реєстрації: блокувати всі повідомлення, крім `ping` та `client_registration`, поки `registered == true` (конфігуровано через ENV) (через ENV `WS_REQUIRE_REGISTRATION_BEFORE_ACTIONS`).
- [x] Ідіоматичне закриття: спроба `Close` з кодами (policy violation, normal closure) залежно від сценарію — частково: `idle_timeout`, `registration_timeout` (інші кейси — TODO).

Деталі імплементації:
- Контроль неактивності зроблено через таймаут операції читання (tokio::time::timeout) та керуючий канал до таску‑відправника, який має sink.
- Для backpressure: додати лічильники інфлайтів на клієнта в `WebSocketSecurityManager`, ACK на відправлення, канал керування для призупинення прийому.

## 2. Протокол повідомлень (сумісність із Python)

- Підсистема: `rust/models` і нормалізація у `rust/hub/src/ws.rs`.
- Поточний стан: основні типи (`ping/pong`, `subscribe/unsubscribe`, `broadcast`, `client_registration`, `task_submit/result`). Додано `stats_update` і `system_notification`. Є нормалізація `data`/`message_type`.

Завдання:
- [x] Додати типи: `stats_update`, `system_notification` (ретрансляція у канали `stats` і `system`).
- [x] Нормалізація payload (як у Pydantic):
  - [x] alias `message_type` → `type`.
  - [x] flatten `data` для `task_submit`, `task_result`, `client_registration`.
  - [x] для `subscribe/unsubscribe` з `data.channel` → плоский `channel`.
  - [x] для `broadcast`: якщо `data` без `payload`, вважати `payload` = `data`.
- [x] Додати типи, що використовуються Python‑тестами (за потреби): `task_update`, `health_status`, `metrics_response` (за специфікацією), з no‑op/ретрансляцією. (Реалізовано у Rust; сумісність Python — далі)
- [x] Узгодити коди помилок та структуру `error` (повідомлення/код/кореляція).

## 3. Auth (видача JWT, refresh, JWKS, сесії)

- Підсистема: новий crate `rust/auth` (рекомендується), інтеграція у `hub`.
- Поточний стан: Rust уміє декодувати JWT (HS/RS) і статичні токени; немає видачі/refresh/JWKS/сесій.

Завдання:
- [ ] Реалізувати видачу `access`/`refresh` токенів (HS256/RS256 за конфігом), TTL, `kid` support.
- [ ] Зберігання сесій/чорних списків у Redis (з термінами дії).
- [ ] JWKS endpoint (`/api/jwks`) з кешем ключів.
- [ ] Блокування логінів (rate‑limit, lockout, LOGIN_LOCKOUT_SECONDS).
- [ ] Bcrypt з конфігурованими раундами, сумісно з Python налаштуваннями.
- [ ] Інтеграція з WS: аутентифікація через заголовки/сабпротоколи; deny query token у prod (вже є).

## 4. Redis‑інтеграція (standalone/sentinel/cluster, Pub/Sub, overflow)

- Підсистема: новий crate `rust/redisx` (умовна назва) або модуль у `hub` з подальшим виділенням.

Завдання:
- [ ] Автовизначення режиму: standalone/sentinel/cluster (ENV + auto‑probe).
- [ ] Підтримка Pub/Sub (канали для hub подій: `stats`, `system`, `tasks:*`).
- [ ] Overflow‑черги (lists або streams), параметри `*_MAXLEN`.
- [ ] Пайплайни та health‑loop (бекоф при помилках, відновлення).
- [ ] Експорт базових метрик (помилки з’єднань, відновлення, qos).

## 5. TaskRouter (черги/розподіл/таймаути/історія)

- Підсистема: `rust/hub/src/task_router.rs` (вже є базова версія, in‑memory).

Завдання:
- [x] Черги за пріоритетами, submit/assign/complete — базово готово.
- [ ] Призначення задач воркерам із урахуванням `accepted_types`, `capabilities`, `max_concurrent_tasks`.
- [ ] Таймаути виконання (`timeout`), повтори (`max_retries`), стани (`processing/timeout/retry`).
- [ ] Історія, TTL і збирання статистики (переміщення з active в history, обрізання історії).
- [ ] Інтеграція з Redis overflow (коли локальні черги переповнені).
- [ ] WS‑ендпоїнти/події: `task_assign`, `task_update`, `task_error`.

## 6. ClientManager (стани/heartbeat/спроможності)

- [ ] Трекінг клієнтів: тип, версія, capabilities, статус `Idle/Busy/Overloaded`.
- [ ] Оцінка навантаження, агрегація статистики (total/success/failed/timeout).
- [ ] Інтеграція з TaskRouter для призначення задач.
- [ ] Оповіщення фронтенда (WS broadcast) при змінах стану.

## 7. Метрики і моніторинг

- Поточний стан: базові лічильники у `WebSocketSecurityManager.metrics`, виводяться в `/api/ws/stats`.

Завдання:
- [x] Лічильники: `subscriptions_total`, `unsubscriptions_total`, `broadcasts_total`, `broadcast_recipients_total`.
- [x] Лічильники помилок: `errors_invalid_message_total`, `errors_permission_denied_total`, `errors_auth_failed_total`, `errors_origin_blocked_total`, `errors_rate_limited_total`, `errors_message_too_large_total`, `errors_too_many_connections_total`.
- [x] Лічильники неактивності: `pong_missed_total`, `idle_closed_total`.
- [x] Окремі лічильники подій: `stats_updates_total`, `system_notifications_total`.
- [ ] Інтеграція з `metrics`/`opentelemetry` (Prometheus exporter), окремий `/metrics`.
- [ ] Теги/labels: user_id? (обережно: приватність), агрегувати по каналах.

## 8. Security Headers і HTTPS

- [ ] Middleware на `tower-http` для `Strict-Transport-Security`, `Content-Security-Policy`, `Permissions-Policy`, `Referrer-Policy`, `X-Frame-Options`, COOP/COEP/CORP.
- [ ] Режим `report-only` для CSP у dev; endpoint для збору звітів CSP.
- [ ] Примусовий redirect HTTP→HTTPS, крім `development/testing`.

## 9. Secrets Manager

- [ ] Централізований доступ до секретів (JWT/refresh/HMAC), джерела: ENV / файл / KMS.
- [ ] Ротація ключів, кешування `kid→key`, безпечне логування (маскування).

## 10. Логування та аудит

- [ ] Єдине структуроване логування (`tracing`), кореляційні ідентифікатори (`correlation_id`).
- [ ] Маскування конфіденційних даних у логах (патерни, як у `core/logging/utils.py`).
- [ ] Аудит‑події (автентифікація, зміни конфігів, дії з задачами).

## 11. Тести

- [ ] Порт юніт‑тестів Python на Rust (за можливості 1:1), у т.ч. для:
  - WebSocket‑безпеки/шлюзів (аутентифікація, rate‑limit, origin‑policy).
  - TaskRouter (черги, таймаути, повтори, історія, призначення).
  - Redis‑шар (Pub/Sub, відновлення після відмов, overflow).
  - Протокол повідомлень (нормалізація `data`, типи, помилки).
- [ ] Інтеграційні тести для Axum‑сервера (http/https/ws), smoke‑сценарії.

## 12. CI/CD

- [ ] Оновити GitHub Actions для Rust: `cargo fmt/clippy/test`, build артефакти, реліз.
- [ ] Створити окремий воркфлоу для інструментів (`rust/tools`).
- [ ] SBOM/безпека залежностей (`cargo deny`), CodeQL для Rust.

## 13. Міграційний план

- [ ] Паралельний запуск Python‑версії та Rust‑хаба за фічефлагом/портом.
- [ ] Переведення трафіку WS та HTTP поетапно (canary/blue‑green).
- [ ] Збір метрик/помилок, відкат за тригерами.
- [ ] Деактивація Python‑модулів після стабілізації.

## 14. Документація

- [ ] Опис протоколу WS (типи подій, поля, приклади).
- [ ] Опис ENV‑змінних і дефолтів; таблиця відповідностей із Python‑версією.
- [ ] Інструкції розгортання (TLS, reverse‑proxy, docker/heroku).

---

## Поточні зміни, вже виконані в Rust

- `permessage-deflate` увімкнено через tungstenite features.
- Heartbeat `ping` + `touch()` на `Ping/Pong`.
- Таймаут неактивності з відправленням Close‑frame (`idle_timeout`).
- Нагадування про реєстрацію, прапорець `registered` у з’єднанні.
- Додані повідомлення `stats_update` і `system_notification` + ретрансляція в канали `stats`/`system`.
- Нормалізація `data`/`message_type`.
- Метрики WS: лічильники підписок/бродкастів/помилок/idle.
- `TaskRouter` (in‑memory): submit/assign/complete + базова статистика.
- `/api/tasks` та `/api/diagnostics` віддають статистику з TaskRouter.

## Узгодження із фронтендом/клієнтами

- Канали `stats` і `system` доступні через `subscribe` (перевірка права `tasks.view`).
- Підтримуються плоскі/`data` payload‑и; `message_type` як alias для `type`.
- У production заборонено `?token=`; рекомендується передача JWT у заголовку `Authorization` або через WS‑сабпротоколи `Sec-WebSocket-Protocol: bearer,<jwt>`.

## ENV змінні (релевантні для WS)

- `WS_HEARTBEAT_INTERVAL` — інтервал пінгу (сек), деф. 30.
- `WS_IDLE_TIMEOUT_SECONDS` — таймаут неактивності рідера (сек), деф. 120.
- `WS_REGISTRATION_TIMEOUT_SECONDS` — таймаут очікування `client_registration` (сек), деф. 30.
- `WS_MAX_MESSAGE_SIZE`, `WS_MAX_MESSAGES_PER_SECOND`, `WS_MAX_SUBSCRIPTIONS`, `WS_MAX_CONNECTIONS_PER_USER` — поточні обмеження.
- `WS_MAX_INFLIGHT` — інфлайт‑обмеження для backpressure.
- `WS_REQUIRE_REGISTRATION_BEFORE_ACTIONS` — вимагати реєстрацію перед діями (true/false, деф. true).



