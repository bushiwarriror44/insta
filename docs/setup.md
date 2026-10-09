# Запуск и конфигурация

Не коммитьте `.env`. Значения секретов сюда не копировать.

## Требования

- Python 3.11+ (локально), ffmpeg в PATH для uniquify.
- Playwright Chromium: `python -m app.cli install-playwright` или `playwright install chromium`.
- Для живого браузера в Docker: `BROWSER_VNC_ENABLED=true`, в образе Xvfb / x11vnc / websockify. Локально Windows VNC-стек как в Linux-контейнере не предполагается — Instagram-автовход идёт через `first_login` / Playwright без noVNC.
- Ollama **не** на маленьком админ-VPS. GPU-хост задаётся через `AGENT_BASE_URL`. Локальный `reels-ollama` только с профилем compose `ollama` (нужно ≥16 GB RAM).

## Локально

```text
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.cli install-playwright
copy .env.example .env
```

Для **локального Ollama** не оставляйте в `.env` строку `AGENT_BASE_URL=` с пустым значением — удалите переменную целиком, иначе чат не увидит `http://localhost:11434/v1`. На Docker/VPS пустой или отсутствующий URL — норма (модель на внешнем GPU).

```text
python -m app.cli init-db
python -m app.cli run-api
```

Во втором терминале — фронтенд:

```text
cd frontend
npm install
npm run dev
```

- API: `http://127.0.0.1:8000` (схема: вкладка «Администрирование», JSON `/api/openapi.json`).
- Vite: `http://127.0.0.1:5173` (`PANEL_BASE_URL`).
- Панель открывается **не** с `/`, а с секретного пути (страница «Настройки»). Корень без пути — ошибка 500.

`run-api` при `WORKER_AUTOSTART=true` поднимает воркер, при `OLLAMA_AUTOSTART=true` — пытается поднять Ollama и модель.

## Docker

Админ-панель (2 vCPU / 6 GB — **без** Ollama):

```text
docker compose up -d --build
```

Ollama в том же compose (не для 6 GB):

```text
docker compose --profile ollama up -d --build
```

Сервисы (имена для `docker_logs` в чате — только эти):

| Сервис | Роль |
| --- | --- |
| `reels-api` | FastAPI, порт хоста `8000`, Playwright/VNC внутри |
| `reels-worker` | очередь публикаций / рендеров / планов |
| `reels-ollama` | модель чата и контент-агента |
| `reels-ollama-pull` | одноразово тянет `AGENT_MODEL` |
| `reels-frontend` | nginx UI, порт хоста `3000` → контейнер `:80` |

`AGENT_BASE_URL` берётся из `.env` (пустой — чат 503 до GPU). `OLLAMA_AUTOSTART=false`, `WORKER_AUTOSTART=false` (воркер — отдельный контейнер). Том `./data` общий. `init-db` на старте **обоих** `reels-api` и `reels-worker` (идемпотентно: lock в `data/.init_db.lock` + игнор `duplicate column` при гонке ALTER). Отключить auto-init: `SKIP_AUTO_INIT_DB=1`.

**Salad / GPU:** в логах API `GET …salad.cloud/…` с **503** при **200** от `api.salad.com` — норма, пока группа **Stopped** или образ качается. Карточка «GPU Salad» → Start; `WAN_BASE_URL` / `AGENT_BASE_URL` имеют смысл только когда контейнер **Running** и Ollama/Wan отвечает.

CLI внутри стека: `docker compose exec reels-api python -m app.cli status` (секретный путь панели по умолчанию не выводится; при необходимости — `status --show-entry-path`, не светите в переписке).

## Перед релизом

Чеклист: [qa-checklist.md §15](qa-checklist.md#15-релиз). Минимум: `python -m pytest tests/ -q`, `cd frontend && npm test -- --run`, на хосте воркера **ffmpeg** в PATH и `python -m app.cli preflight` (в Docker: `docker compose exec reels-worker python -m app.cli preflight`). Ручной smoke (IG, Studio, T2V, slideshow, публикация с `hold_for_review`) — только со staging-прокси и ключами.

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
| `AGENT_BASE_URL` | OpenAI-совместимый чат; **не задавайте** `=` без URL локально; на VPS — пусто до GPU (Clore) + `/v1` |
| `AGENT_MODEL` | обычно `qwen3:8b` (совпадает с `ollama-pull` в compose) |
| `BROWSER_VNC_ENABLED` | `true` в Docker-образе api для noVNC |
| `GENERATION_TIMEOUT_SECONDS` | таймаут очереди рендера |
| `MEDIA_URL_SECRET` | подпись ссылок на медиа в production |
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
| `VIDEO_BACKEND` | `auto` или одно имя: `fal` / `huggingface` / `pollinations` / `local` / `hfspace` |
| `VIDEO_BACKEND_CHAIN` | порядок failover для `auto` |
| `FAL_API_KEY` | fal; без ключа этот движок выключен |
| `FAL_MODEL` | модель fal (Wan 2.5 по умолчанию) |
| `HF_TOKEN` / `HF_VIDEO_MODEL` | Hugging Face Inference |
| `POLLINATIONS_VIDEO_URL` | T2V endpoint; пусто — движок выключен |
| `POLLINATIONS_API_KEY` | Bearer для Pollinations; **битый ключ → 403** `rejected the credentials`. Удалите строку или задайте ключ из кабинета Pollinations |
| `WAN_BASE_URL` | свой GPU HTTP, не compose панели. Сборка образа чат+Wan: `docker/salad-gpu` |
| `SALAD_API_KEY` | ключ Salad Public API для Start/Stop группы с `/administration`. В чат и логи не копировать |
| `SALAD_ORGANIZATION` / `SALAD_PROJECT` / `SALAD_CONTAINER_GROUP` | slug-имена из кабинета Salad, не URL |
| `SALAD_IDLE_STOP_MINUTES` | авто-Stop группы после простоя (чат или local-рендер); `0` выключает. Start снова качает образ |
| `HF_SPACE_ID` | optional Gradio Space, experimental |
| `DEFAULT_DAILY_POST_CAP` и часы | дефолты новых аккаунтов |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | алерты (необязательно) |

### Рендер: диагностика `.env` (VPS)

Без вывода секретов:

```bash
cd /opt/insta
bash scripts/audit_render_env.sh .env
docker compose up -d
```

Проверка Pollinations из worker:

```bash
docker compose exec reels-worker python scripts/probe_pollinations.py
```

Типичная ошибка `pollinations rejected the credentials (generate)` — HTTP 401/403: нет `FAL_API_KEY` / `HF_TOKEN`, цепочка дошла до Pollinations. Решения: **`FAL_API_KEY`** (рекомендуется), исправить/убрать `POLLINATIONS_API_KEY`, **`WAN_BASE_URL`** + Salad Running, или `VIDEO_BACKEND_CHAIN=fal,local` без pollinations.

Дальше: [panel.md](panel.md).
