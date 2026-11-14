# Данные на диске, логи, бэкап

Корень задаётся `DATA_DIR` (по умолчанию `data/`). Не кладите этот каталог в git. Чат `list_project_files` / `read_project_file` видит репозиторий и `data/`, за пределы проекта не выходит.

## Каталоги `data/`

| Путь | Что лежит |
| --- | --- |
| `data/app.db` | SQLite (если `DATABASE_URL=sqlite:///data/app.db`) |
| `data/app.log` | лог приложения (`LOG_FILE`) |
| `data/sessions/` | mobile dump Instagram (`session_*.json`) после instagrapi / `mint_mobile_session` |
| `data/devices/` | Android fingerprint Instagram (`device_*.json`) |
| `data/playwright/<username>/state.json` | cookies Playwright: web IG, YouTube, TikTok |
| `data/videos/source` | загрузки библиотеки и исходники (`MEDIA_DIR` совпадает) |
| `data/videos/out` | uniquify перед публикацией |
| `data/screenshots` | снимки `screenshot_page` |
| `data/backups` | копии SQLite `app-YYYYMMDD-HHMMSS.db` |
| `data/reference` | файлы-источники контент-агента |
| `data/challenges/<username>.code` | код челленджа Instagram для `provide-code` |
| `data/app_versions.json` | опциональный пул версий приложения для `refresh-app-versions` |

Fingerprint и mobile dump — **только Instagram**. Для Studio достаточно `state.json` (+ прокси).

## Логи

Хвост `data/app.log` — tool `diagnose` (по умолчанию ~24 строки) и страница Обслуживание / Активность через `job_logs`. Полный файл чат не читает целиком.

Docker: `python -m app.cli` не подменяет compose. Логи сервисов — `docker compose logs reels-api` (и соседние `reels-*`) или чат `docker_logs`. Нет Docker CLI — инструмент вернёт `available: false`; не выдумывать.

## Бэкап

«Снять копию» на Обслуживании и `take_backup` копируют **только SQLite** в `data/backups/` (`BACKUP_DIR`). Имя `app-<UTC-штамп>.db`. Старые копии режутся (`BACKUP_KEEP`, по умолчанию 14). Не SQLite — ошибка «only SQLite is backed up».

**Restore нет в UI и в чате.** HTTP `POST /api/maintenance/backups/restore` с `{"name": "app-….db"}` существует в API, но кнопки и tools его не вызывают. Восстановление вручную: остановить API/воркер, подменить файл БД, поднять процессы. Копии `state.json`, сессий и роликов бэкап **не** включает.

**Перенос аккаунтов на другой сервер (merge):** бандл `.tar.gz` — [`migration-server-merge.md`](migration-server-merge.md), команды `export-migration-bundle` / `import-migration-bundle` (или `scripts/export_migration_bundle.py` / `import_migration_bundle.py`). Не путать с restore всей БД.

Список копий: `GET /api/maintenance/backups`.

## Диагностика

1. `diagnose` — воркер (pid / heartbeat), блоки `posting` / `login` / `proxies` (очередь, сессии, DiagnosticRun, geo, `hints`), Ollama (reachable, модели), свежие ошибки, хвост лога. Чат: секции «Если постинг сломался», «Если вход сломался», «Если прокси сломался» в [`assistant-handbook.md`](assistant-handbook.md).
2. `test_connection` / «Подключение» — прокси + сессия на диске; для Studio это не «Google ещё пускает».
3. Челлендж Instagram — Telegram (если задан) и файл в `data/challenges/`; CLI `provide-code`.
4. VNC: `python -m app.cli browser-vnc-diag` на хосте контейнера.
5. `preflight` — грубые дыры перед стартом воркера.

Не списывать любую ошибку на «прокси»: цитировать поле `ошибка` инструмента.

## Telegram

**Алерты (воркер):** необязательно. `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`. Если оба заданы, воркер шлёт короткие алерты (челлендж, blocked, мёртвый прокси и т.п.) и пишет `Event` в БД даже при сбое доставки.

**Агент-бот:** `TELEGRAM_AGENT_ENABLED=true`, токен `TELEGRAM_AGENT_BOT_TOKEN` (или тот же `TELEGRAM_BOT_TOKEN`; лучше отдельный бот). Запуск: `python -m app.cli telegram-bot`. В чате: `/auth <ADMIN_TOKEN>`, затем задание текстом — тот же ассистент, что `POST /api/assistant/run`. Привязка `chat_id` в `panel_settings.telegram_allowed_chats`. Долгие задания идут в пуле (`TELEGRAM_AGENT_WORKER_THREADS`, по умолчанию 2) — разные chat_id не блокируют long-poll. Уточнения агента (`asks`) — inline-кнопки; ответ — следующим сообщением (префикс «Уточнения:»).

Токены в документы не копировать. События также на Панели («Последние события»): завершённые задания — `telegram_agent` (chat, used, asks); сбой run — `telegram_agent_error`.

## Browser vision (опционально)

`AGENT_VISION_ENABLED=true`, VL-модель в Ollama (`AGENT_VISION_MODEL`, напр. `qwen2.5vl:7b`). Скриншот viewport → подсказка click/type — **fallback** после селекторов и autofill в Playwright, не замена штатного логина.

Ограничения: капча и 2FA — вручную (`submit_login_code`, оператор в VNC); vision не гарантирует обход Meta. На одной GPU держите **по очереди** чат-модель и VL (`keep_alive: 0` / выгрузка), не параллельно.
