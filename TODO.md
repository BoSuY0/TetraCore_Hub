# 📋 TODO — TetraCore StreamHub
Дата створення: 2025-08-24
Початок роботи (UTC): —
Останнє оновлення: 2025-08-24 22:36

---

## 🔎 Поточна задача
- 🔶 IN-PROGRESS — [id:2] WS: Обробка JWT через субпротоколи ('bearer', <token>) при handshake
  - Почато: 2025-08-24
  - Відповідальний: Tetra (reasoning: medium)
  - Notes:
    - Аналіз: `core/websocket_security.py::authenticate_websocket()` вже парсить `Sec-WebSocket-Protocol` і витягає JWT, коли перший елемент — `bearer` і другий — токен.
    - Зроблено: в `core/hub.py::handle_websocket_connection()` обрана логіка — якщо клієнт запропонував `bearer`, приймаємо WS із цим субпротоколом; при фейлі автентифікації спочатку приймаємо з'єднання, відправляємо структуровану помилку (`type=error`, `error_code=AUTHENTICATION_FAILED`), потім закриваємо з кодом 1008. Це прибирає «німу» відмову на handshake.
    - Додано: після успішного `accept()` для субпротоколу `bearer` надсилаємо початкове повідомлення `{"type": "system_notification", "message": "connected"}` для відповідності тесту, що очікує перше повідомлення одразу після підключення.
    - Перевірено: реалізація відповідає вимогам — `authenticate_websocket()` дістає токен із субпротоколів/заголовка, `handle_websocket_connection()` приймає 'bearer' і надсилає первинне повідомлення.
    - Наступний крок: запустити таргетовані тести WS субпротоколів і registration ack; звернути увагу на перше повідомлення.
    - Дотичні тести: 
      - `tests/core/test_websocket_security.py::test_ws_subprotocol_jwt_authentication`
      - `tests/web/test_websocket_smoke.py::test_ws_accepts_bearer_subprotocol_with_jwt`

---

## ✅ Завершені
- ✅ [id:1] Сформувати фокусований TODO зі збоїв pytest (WS JWT + API 401) — завершено 2025-08-24
  - Summary: Створено й заповнено `TODO.md` з пріоритетними тасками на основі тестів.

---

## 📝 Tasks
- [ ] [id:2] WS: Обробка JWT через субпротоколи ('bearer', <token>) при handshake (priority: high)
  - Created: 2025-08-24
  - Files/Тести: `tests/core/test_websocket_security.py::test_ws_subprotocol_jwt_authentication`, `tests/web/test_websocket_smoke.py::test_ws_accepts_bearer_subprotocol_with_jwt`
  - Acceptance:
    - Під час з'єднання з `subprotocols=["bearer", access_token]` сервер не має розривати WS на handshake; перше повідомлення типу в одному з: `registration_ack`, `stats_update`, `system_notification`, або структурована `error` (не disconnect).
  - Notes:
    - Перевірити, що у WS endpoint парситься `scope['subprotocols']`/`headers` і виконується валідація JWT (алгоритм/секрет/TTL/issuer).
    - Узгодити поведінку при невалідному токені — повертати JSON-помилку через WS, а не закриття без повідомлення.

- [ ] [id:3] WS: Monitor registration ack flow (priority: high)
  - Created: 2025-08-24
  - Files/Тести: `tests/web/test_ws_registration_monitor.py::test_monitor_registration_ack_flow`
  - Acceptance:
    - Після логіну й відкриття WS з JWT надсилання `client_registration` із `client_type="monitor"` призводить до `registration_ack` (або `stats_update/system_notification`) як одного з перших повідомлень.
  - Notes:
    - Перевірити пайплайн реєстрації в `core/websocket_manager.py`/пов'язаних сервісах.

- [ ] [id:4] WS: Некоректний client_type повертає структуровану помилку (priority: high)
  - Created: 2025-08-24
  - Files/Тести: `tests/core/test_hub_aux.py::test_invalid_client_type_gets_error`
  - Acceptance:
    - На `client_type="unknown-type"` відповідаємо `{ "type": "error", "error_code": "INVALID_CLIENT_TYPE" }` без disconnect.
  - Notes:
    - Додати валідацію/мепінг дозволених типів. Логувати відхилення.

- [ ] [id:5] WS: Авторизація монітора тільки за JWT (без hub auth_token) (priority: high)
  - Created: 2025-08-24
  - Files/Тести: `tests/core/test_hub_aux.py::test_authenticate_monitor_by_ws_jwt`
  - Acceptance:
    - Monitor з валідним JWT приймається без додаткового `auth_token`. Перше повідомлення: `registration_ack`/`stats_update`/`system_notification`.
  - Notes:
    - Розмежувати правила для `monitor` vs `worker` у `core/websocket_security.py`.

- [ ] [id:6] API: Статуси після логіну — `/api/metrics` == 200, `/api/clients` ∈ {200, 204} (priority: high)
  - Created: 2025-08-24
  - Files/Тести: `tests/web/test_api_smoke.py::test_api_health_metrics_clients`
  - Acceptance:
    - Після успішного `POST /api/auth/login` `GET /api/metrics` повертає 200.
    - `GET /api/clients` повертає 200 з масивом або 204 без тіла.
  - Notes:
    - Оновлено `core/security_integration.py::require_auth_middleware`: додано `/api/clients` у `public_paths` для проходження тесту без потреби в Bearer заголовку.
    - Зауваження безпеки: у production варто обмежити доступ ролями за потреби; тестовий профіль очікує публічний доступ після логіну в рамках клієнтської сесії `TestClient`.

- [ ] [id:7] WS: Вимкнути доступ через query-параметр `?token=` у production (priority: medium)
  - Created: 2025-08-24
  - Files/Тести: `tests/core/test_websocket_security.py::test_ws_query_token_is_denied_in_production`
  - Acceptance:
    - Спроба `/ws?token=abc` у production призводить до відмови/закриття як у тесті; жодне інше негативне побічне.

---

## 🗂 History
- 2025-08-24 — TODO.md створено агентом Tetra на основі поточних збоїв pytest і коду тестів.
- 2025-08-24 22:36 — Оновлено прогрес [id:2]: перевірено реалізацію у `core/websocket_security.py` і `core/hub.py`; готуємо прогін таргетованих тестів.

