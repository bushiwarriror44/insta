# Запуск и конфигурация

Не коммитьте `.env`. Значения секретов сюда не копировать.

## Требования

- Python 3.11+ (локально), ffmpeg в PATH для uniquify.
- Playwright Chromium: `python -m app.cli install-playwright` или `playwright install chromium`.
- Для живого браузера в Docker: `BROWSER_VNC_ENABLED=true`, в образе Xvfb / x11vnc / websockify. Локально Windows VNC-стек как в Linux-контейнере не предполагается — Instagram-автовход идёт через `first_login` / Playwright без noVNC.
- Ollama на хосте (`localhost:11434`) или сервис `reels-ollama`.

## Локально

```text
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.cli install-playwright
copy .env.example .env
python -m app.cli init-db
python -m app.cli run-api
```

Во втором терминале — фронтенд:

```text
cd frontend
npm install
npm run dev
```

- API: `http://127.0.0.1:8000` (OpenAPI: `/api/docs`).
- Vite: `http://127.0.0.1:5173` (`PANEL_BASE_URL`).
- Панель открывается **не** с `/`, а с секретного пути (страница «Настройки»). Корень без пути — ошибка 500.

`run-api` при `WORKER_AUTOSTART=true` поднимает воркер, при `OLLAMA_AUTOSTART=true` — пытается поднять Ollama и модель.

## Docker

```text
docker compose up -d --build
```

Сервисы (имена для `docker_logs` в чате — только эти):

| Сервис | Роль |
| --- | --- |
| `reels-api` | FastAPI, порт хоста `8000`, Playwright/VNC внутри |
| `reels-worker` | очередь публикаций / рендеров / планов |
| `reels-ollama` | модель чата и контент-агента |
| `reels-ollama-pull` | одноразово тянет `AGENT_MODEL` |
| `reels-frontend` | nginx UI, порт хоста `3000` → контейнер `:80` |

В compose API/worker смотрят на `http://reels-ollama:11434/v1`, `OLLAMA_AUTOSTART=false`, `WORKER_AUTOSTART=false` (воркер — отдельный контейнер). Том `./data` общий. `init-db` на старте контейнеров; отключить: `SKIP_AUTO_INIT_DB=1`.

CLI внутри стека: `docker compose exec reels-api python -m app.cli status` (не печатайте путь панели в переписку).

## Переменные `.env`

Группы из `.env.example` и [`app/config.py`](../app/config.py). Пустое = значение по умолчанию в коде.

### База и пути

| Переменная | Смысл |
| --- | --- |
| `DATABASE_URL` | по умолчанию `sqlite:///data/app.db` |
| `DATA_DIR` | корень данных |
| `SESSIONS_DIR` | mobile dump Instagram |
| `DEVICES_DIR` | Android fingerprint Instagram |
| `PLAYWRIGHT_DIR` | `state.json` Studio / web |
| `VIDEO_SOURCE_DIR` / `VIDEO_OUT_DIR` | исходники и выход uniquify |
| `LOG_FILE` / `LOG_LEVEL` | `data/app.log` |

### Панель и API

| Переменная | Смысл |
| --- | --- |
| `ADMIN_TOKEN` | Bearer владельца; пустой — auth выключен (только localhost/VPN) |
| `API_HOST` / `API_PORT` | `0.0.0.0:8000` |
| `CORS_ALLOWED_ORIGINS` | Vite `:5173` и UI `:3000` |
| `UPLOAD_MAX_MB` | лимит загрузки |
| `PANEL_BASE_URL` | URL UI для снимков чата и ссылок |

Секретный путь и мастер-пароль живут в **базе** (страница «Настройки»), не в `.env`.

### Чат и воркер

| Переменная | Смысл |
| --- | --- |
| `AGENT_BASE_URL` | OpenAI-совместимый чат, по умолчанию `http://localhost:11434/v1` |
| `AGENT_MODEL` | обычно `qwen3:8b` |
| `ASSISTANT_TIMEOUT_SECONDS` | таймаут HTTP к модели (чат) |
| `WORKER_AUTOSTART` / `OLLAMA_AUTOSTART` | автостарт при `run-api` |
| `WORKER_POLL_INTERVAL_SEC` | опрос очереди |
| `JOB_MAX_ATTEMPTS` | попытки публикации |

### Прокси, Playwright, браузер

| Переменная | Смысл |
| --- | --- |
| `PROXY_HEALTH_URL` | проверка IP |
| `PLAYWRIGHT_HEADLESS` | headless first-login |
| `BROWSER_VNC_ENABLED` | живой браузер + noVNC (в Docker-образе включают) |
| `BROWSER_SESSION_TIMEOUT_MIN` | простой сессии VNC |

### Генерация и лимиты по умолчанию

| Переменная | Смысл |
| --- | --- |
| `FAL_API_KEY` | без ключа `create_render` отказывается с текстом healthcheck |
| `FAL_MODEL` | модель fal (Wan 2.5 по умолчанию) |
| `DEFAULT_DAILY_POST_CAP` и часы | дефолты новых аккаунтов |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | алерты (необязательно) |

Дальше: [panel.md](panel.md).
