# План имплементации Firewall для API (с сохранением открытого Dashboard)

## 1. Цель и границы

- Цель: ограничить доступ к API allowlist-списком IP адресов.
- Dashboard должен остаться без ограничений firewall:
  - UI: `/dashboard`, `/accounts`, `/settings`, новая вкладка `/firewall`
  - Dashboard API: `/api/*` (как сейчас, под текущей TOTP-логикой)
- Под защиту firewall попадают API-эндпоинты для клиентов:
  - обязательно: `/backend-api/codex/*`
  - рекомендуется также: `/v1/*` (чтобы не было обхода через альтернативный вход)

## 2. Поведение firewall (договор)

- Модель: allowlist.
- Если список IP пустой: firewall в пассивном режиме (доступ к API открыт всем).
- Если список не пустой: доступ только IP из списка.
- При блокировке:
  - HTTP `403`
  - тело ошибки в OpenAI-формате: `{"error":{"code":"ip_forbidden","message":"...","type":"access_error"}}`

## 3. Архитектура по слоям

### 3.1 База данных

Добавить таблицу allowlist:

- Таблица: `api_firewall_allowlist`
- Поля:
  - `ip_address` (`String`, PK, уникальный, в каноническом виде)
  - `created_at` (`DateTime`, `server_default=func.now()`, not null)

Файлы:

- `app/db/models.py` (новая ORM-модель + index при необходимости)
- `app/db/migrations/versions/007_add_api_firewall_allowlist.py` (идемпотентная миграция)
- `app/db/migrations/__init__.py` (добавить migration entry)

### 3.2 Новый модуль `firewall`

Создать модуль по принятой структуре:

- `app/modules/firewall/schemas.py`
- `app/modules/firewall/repository.py`
- `app/modules/firewall/service.py`
- `app/modules/firewall/api.py`
- `app/modules/firewall/__init__.py`

Контракты (typed):

- Pydantic input/output через `DashboardModel`
- Внутренние payload-и через dataclass (service layer)

Предлагаемые API:

1. `GET /api/firewall/ips`
   - Response:
     - `entries: [{ ipAddress: str, createdAt: datetime }]`
     - `mode: "allow_all" | "allowlist_active"`
2. `POST /api/firewall/ips`
   - Request: `{ ipAddress: str }`
   - Response: добавленная запись
   - Ошибки:
     - `400` invalid IP
     - `409` duplicate
3. `DELETE /api/firewall/ips/{ip_address}`
   - Response: `{ status: "deleted" }`
   - Ошибка `404` если IP не найден

Валидация IP:

- Использовать `ipaddress.ip_address(...)`
- Нормализовать:
  - IPv4 как есть
  - IPv6 в канонической форме (`str(ip_obj)`)

### 3.3 DI и зависимости

Добавить контекст в `app/dependencies.py`:

- `FirewallContext` с `session`, `repository`, `service`
- провайдер `get_firewall_context(...)`

### 3.4 Middleware для защиты API

Добавить новый middleware, например:

- `app/core/middleware/api_firewall.py`

Логика:

1. Проверить `request.url.path`.
2. Если путь не относится к защищаемым префиксам, пропустить.
3. Определить клиентский IP.
4. Получить текущий allowlist.
5. Принять решение allow/deny.
6. При deny вернуть `403` в OpenAI-формате.

Подключение:

- `app/core/middleware/__init__.py`
- `app/main.py` (добавить middleware до router include)

## 4. Определение клиентского IP (важно)

Нужен явный, безопасный режим:

- Новый конфиг в `app/core/config/settings.py`:
  - `firewall_trust_proxy_headers: bool = False`

Правило:

1. Если `firewall_trust_proxy_headers = True`, брать IP из первого значения `X-Forwarded-For`.
2. Иначе использовать `request.client.host`.

Операционный комментарий:

- За reverse-proxy включать trust only если прокси гарантированно перезаписывает `X-Forwarded-For`.
- Иначе оставить `False` (защита от spoofing).

## 5. Изменения dashboard (новая вкладка Firewall)

### 5.1 Роутинг SPA

Файлы:

- `app/main.py`: добавить `@app.get("/firewall") -> index.html`
- `app/static/index.js`: добавить страницу в `PAGES`
- `app/static/index.html`: добавить `tabpanel` `tab-firewall`

### 5.2 UI/UX вкладки

Во вкладке `Firewall`:

- Текущее состояние:
  - `Mode: allow_all / allowlist_active`
  - Количество разрешенных IP
- Форма добавления IP:
  - input + кнопка `Add`
  - inline валидация
- Список разрешенных IP:
  - таблица/лист
  - `createdAt`
  - кнопка `Remove`

### 5.3 Frontend state/actions

Файл: `app/static/index.js`

- `API_ENDPOINTS`:
  - `firewallIps: "/api/firewall/ips"`
  - `firewallIpDelete: (ip) => ...`
- Новый state-срез `firewall`
- Методы:
  - `fetchFirewallIps()`
  - `addFirewallIp()`
  - `removeFirewallIp()`
  - `refreshFirewall()` (в `refreshAll` добавить загрузку firewall-данных)

## 6. Error handling и контракты ответов

- Ошибки dashboard API (`/api/firewall/*`) использовать `dashboard_error(...)`.
- Ошибки firewall-блокировки на `/backend-api/codex/*` и `/v1/*` использовать `openai_error(...)`.
- Не смешивать форматы между dashboard и proxy API.

## 7. План тестирования

### 7.1 Integration tests

Добавить:

- `tests/integration/test_firewall_api.py`
  - list empty
  - add valid IPv4
  - add valid IPv6
  - duplicate -> 409
  - invalid IP -> 400
  - delete success / delete missing -> 404

- `tests/integration/test_api_firewall_middleware.py`
  - empty list => `/backend-api/codex/responses` не блокируется
  - non-empty + allowed IP => доступ есть
  - non-empty + denied IP => `403`
  - `/dashboard` и `/api/settings` не ограничиваются firewall
  - (если включаем scope) `/v1/responses` тоже защищен

### 7.2 Unit tests

Добавить:

- `tests/unit/test_firewall_service.py`
  - нормализация/валидация IP
  - режим `allow_all`/`allowlist_active`
- `tests/unit/test_firewall_ip_resolution.py`
  - источник IP при `firewall_trust_proxy_headers=True/False`

## 8. Последовательность реализации (рекомендуемая)

1. DB модель + migration + подключение migration.
2. Модуль `firewall` (schemas/repository/service/api).
3. DI context в `app/dependencies.py`.
4. Middleware + подключение в `app/main.py`.
5. SPA route `/firewall` + tab в `index.html`/`index.js`.
6. Frontend CRUD для IP.
7. Интеграционные и unit тесты.
8. Финальная проверка: dashboard работает как раньше, API фильтруется по allowlist.

## 9. Критерии готовности (DoD)

- Можно добавить/удалить IP через вкладку `Firewall`.
- При непустом allowlist API недоступен с неразрешенного IP (`403`).
- Dashboard остается доступным и функциональным.
- Все новые контракты покрыты тестами.
- Миграции идемпотентны и проходят в существующем потоке `run_migrations`.
