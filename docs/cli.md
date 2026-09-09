# CLI: `python -m app.cli`

Команды из [`app/cli.py`](../app/cli.py). Почти все сначала поднимают логирование и `init-db` (схема SQLite). Не коммитьте вывод с секретами.

Секретный путь панели **не** копируйте в чаты. Команда `status` его печатает — смотрите локально.

## База и прокси

### `init-db`

Создаёт схему. Печатает `DATABASE_URL`.

```text
python -m app.cli init-db
```

### `import-proxies PATH`

JSON-массив объектов. У каждой строки нужны `label` и `url`. По желанию `country`, `timezone` / `timezone_name`, `notes`. По умолчанию health-check; `--skip-health-check` — только запись.

```text
python -m app.cli import-proxies ./examples/local-proxies.seed.json --skip-health-check
```

### `add-proxy`

Одна запись. `--label`, `--url` (`http://user:pass@host:port`), опционально `--country`, `--timezone`, `--notes`, `--skip-health-check`.

```text
python -m app.cli add-proxy --label res-de-1 --url http://USER:PASS@HOST:PORT --country DE --timezone Europe/Berlin
```

## Аккаунты (CLI — Instagram)

`add-account` регистрирует **Instagram**: обязательны `--username`, `--password` (можно интерактивно), `--proxy` (метка уже существующего прокси). YouTube/TikTok этим CLI не создаются — UI / чат `create_account` с `platform`.

Опции: `--email`, `--email-password`, `--totp-seed`, `--session-id`, `--timezone` (по умолчанию UTC; плейсхолдер берёт TZ прокси), `--daily-post-cap`, `--min-gap-hours`, `--active-hour-start`, `--active-hour-end`. Существующее имя — обновление полей. Пишет fingerprint в `data/devices`. `--session-id` сбрасывает mobile dump на диске.

```text
python -m app.cli add-account --username alice --proxy res-de-1 --timezone Europe/Berlin
```

### `first-login USER`

Stealth Playwright, только Instagram: логин/пароль из карточки, прокси обязателен. Эквивалент кнопки автовхода / tool `first_login`.

```text
python -m app.cli first-login alice
```

### `pause-account USER` / `resume-account USER`

Статус `paused` / `active`.

### `rotate-proxy USER PROXY_LABEL`

Меняет IP аккаунта. То же, что «Сменить прокси» / `attach_proxy`.

### `list-accounts`

Таблица: имя, статус, прокси, TZ, кап, last publish.

### `export-account USER`

JSON Android-fingerprint instagrapi на stdout. Нет файла устройства — ошибка. Не cookies Studio.

### `provide-code USER CODE`

Код челленджа Instagram: файл `data/challenges/<user>.code`. Если статус `challenge` — снимает на `active`. Не код 2FA живого VNC (`submit_browser_code` / UI).

## Instagram app versions и Playwright

### `refresh-app-versions`

Пул версий Android-приложения Instagram из JSON (по умолчанию `data/app_versions.json`): список `{version, code}`.

### `install-playwright`

`python -m playwright install` (по умолчанию `--browser chromium`).

## Очередь публикаций

### `enqueue-post`

Путь к видео **на диске** (`--video`), не `filename` библиотеки как в чате. `--username`, опционально `--caption-template`, `--when` (ISO UTC). Без `--when` — сейчас плюс случайные 1–30 минут. Статус сразу `queued`.

```text
python -m app.cli enqueue-post --username alice --video data/videos/source/clip.mp4
```

### `plan-week`

**Не** страница «Агент» / `PlanJob`. Берёт `.mp4`/`.mov`/`.m4v` из `--sources-dir` (по умолчанию `data/videos/source`) и раскладывает `PostJob` на `--days` (1–14, по умолчанию 7).

Контент-план fal — UI `/agent` или tools `plan_account` / `preview_plan`.

## Процессы

### `run-worker`

Воркер в foreground: публикации, uniquify, рендеры, склейки, планы.

### `run-api`

FastAPI (`app.api.main:app`). `--host` / `--port` (из настроек, обычно `:8000`), `--reload` только для разработки. При `WORKER_AUTOSTART` / `OLLAMA_AUTOSTART` пытается поднять воркер и Ollama.

```text
python -m app.cli run-api
```

### `ask "текст"`

Один промпт в автономный ассистент (`allow_browser=True`), как `POST /api/assistant/run`. Печатает `reply`, вопросы `asks`, список `used`. Пример:

```text
python -m app.cli ask "создай прокси и аккаунт, войди, опубликуй clip.mp4"
```

Нужны Ollama и (для браузера) VNC-стек. См. [assistant.md](assistant.md).

## Диагностика

### `status`

Снимок: очередь, running, свежие `dead`, дневная статистика. **Печатает секретный путь панели.** Не вставляйте этот вывод в тикеты и в чат модели.

### `preflight`

Перед воркером: есть ли `data/` и `sessions/`, не пуст ли `/ms-playwright` (в Linux-образе), есть ли прокси, не unhealthy ли они. На Windows локально проверка Playwright-кэша в `/ms-playwright` часто «пустая» — это про контейнер.

### `browser-vnc-diag [USER]`

Проверки noVNC на **той машине, где крутится API** (обычно VPS/Docker): `BROWSER_VNC_ENABLED`, `DISPLAY`, бинарники Xvfb / x11vnc / websockify, Playwright, статика `/usr/share/novnc`. С именем аккаунта — JSON статуса сеанса и примеры `curl` / `wscat`. В примерах токен — плейсхолдер `YOUR_ADMIN_TOKEN`, не живой `ADMIN_TOKEN`.

```text
python -m app.cli browser-vnc-diag alice
```

WebSocket: query `token=`, не заголовок Bearer. С хоста nginx должен проксировать Upgrade (см. `deploy/host-nginx.conf.example`).

Дальше: [data-and-ops.md](data-and-ops.md).
