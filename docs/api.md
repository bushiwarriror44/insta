# HTTP API панели

Интерактивная схема: `http://127.0.0.1:8000/api/docs` (OpenAPI JSON: `/api/openapi.json`). Этот файл **не** дублирует весь OpenAPI — только вход и маршруты, которые путают с чатом.

Заголовок почти везде:

```http
Authorization: Bearer YOUR_ADMIN_TOKEN
```

Владелец: `ADMIN_TOKEN` из `.env` и/или мастер-пароль из БД. Операторы — отдельные пароли со страницы «Доступы». Если токен не задан и мастер-пароль пуст, часть стенда может работать без auth (смотри лог `auth_required` при старте `run-api`). В примерах — плейсхолдер `YOUR_ADMIN_TOKEN`, не живое значение.

CORS: `CORS_ALLOWED_ORIGINS` (Vite `:5173`, Docker UI `:3000`).

## Ассистент

Префикс `/api/assistant`, тег OpenAPI `assistant`.

### Чат панели — `POST /api/assistant`

Тело: **`messages`**, не `prompt`.

```json
{
  "messages": [{"role": "user", "content": "сколько аккаунтов?"}],
  "page": "/accounts",
  "account_id": 1,
  "job_id": null
}
```

`page` / `account_id` / `job_id` подмешиваются в system (срез handbook текущей страницы). Browser-tools нет. До 6 раундов tools.

Ответ: `reply`, `used`, `asks`, `open_url`, `opened`, `images`, `created`.

Ошибки Ollama: HTTP 503 (можно повторить) или 409.

### Stream — `POST /api/assistant/stream`

То же тело, что у чата. `Content-Type: text/event-stream`. Каждое событие: `data: {json}\n\n`. Виды: промежуточные `Step`, финал `type=done` с полями ответа, либо `type=error`.

### Автономный run — `POST /api/assistant/run`

Тело: **`prompt`**, не `messages`.

```json
{
  "prompt": "создай прокси и аккаунт, войди, опубликуй clip.mp4"
}
```

По желанию те же `page` / `account_id` / `job_id`. `allow_browser=true` на сервере: `start_browser`, `wait_render`, … CLI `python -m app.cli ask` бьёт в тот же код, минуя HTTP.

Пустой `prompt` — ошибка валидации.

## Живой браузер

Префикс `/api/accounts/{username}/browser/…`. `{username}` — имя аккаунта в БД. Нужны прокси и обычно `BROWSER_VNC_ENABLED=true`.

| Метод | Путь | Смысл |
| --- | --- | --- |
| `POST` | `/api/accounts/{username}/browser/start` | старт Playwright + VNC; query `login_surface` |
| `GET` | `/api/accounts/{username}/browser/status` | статус сеанса |
| `POST` | `/api/accounts/{username}/browser/code` | тело с кодом 2FA |
| `POST` | `/api/accounts/{username}/browser/save` | cookies → `state.json` |
| `POST` | `/api/accounts/{username}/browser/open-instagram` | навигация (Instagram) |
| `DELETE` | `/api/accounts/{username}/browser/stop` | остановить сеанс |
| WebSocket | `/api/accounts/{username}/browser/vnc/ws?token=YOUR_ADMIN_TOKEN` | noVNC; токен в query, не Bearer |

Примеры curl с плейсхолдером — `python -m app.cli browser-vnc-diag USER`.

Из нижнего чата эти маршруты не вызываются. Run вызывает обёртки tools.

## Соседние группы (смотреть в `/api/docs`)

Неполный указатель, чтобы не искать вслепую:

- `/api/health` — живость процесса.
- `/api/accounts`, `/api/proxies` — CRUD, `test-connection`, `first-login`, `mint-mobile-session`, cookies, fingerprint, Playwright state.
- `/api/jobs` — очередь публикаций, approve / cancel / retry, логи.
- `/api/generations`, `/api/compositions` — fal и склейка.
- `POST /api/accounts/{id}/plan` | `/preview` | `/week` — контент-план.
- `/api/worker/start` | `/stop` — воркер панели.
- `/api/maintenance/runtime` — Ollama; `POST /api/maintenance/backups` — копия БД.
- `/api/settings`, `/api/operators` — только владелец (секретный путь, мастер-пароль, операторы).

Чат не удаляет сущности, даже если в OpenAPI есть `DELETE`.

## Безопасность примеров

Не вставляйте в тикеты: `entry_path`, `ADMIN_TOKEN`, пароли, TOTP, URL прокси с логином, содержимое `state.json`. Для curl — `YOUR_ADMIN_TOKEN` и `http://USER:PASS@HOST:PORT`.
