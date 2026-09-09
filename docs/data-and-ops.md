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

Хвост `data/app.log` — tool `diagnose` (по умолчанию ~80 строк) и страница Обслуживание / Активность через `job_logs`. Полный файл чат не читает целиком.

Docker: `python -m app.cli` не подменяет compose. Логи сервисов — `docker compose logs reels-api` (и соседние `reels-*`) или чат `docker_logs`. Нет Docker CLI — инструмент вернёт `available: false`; не выдумывать.

## Бэкап

«Снять копию» на Обслуживании и `take_backup` копируют **только SQLite** в `data/backups/` (`BACKUP_DIR`). Имя `app-<UTC-штамп>.db`. Старые копии режутся (`BACKUP_KEEP`, по умолчанию 14). Не SQLite — ошибка «only SQLite is backed up».

**Restore нет в UI и в чате.** HTTP `POST /api/maintenance/backups/restore` с `{"name": "app-….db"}` существует в API, но кнопки и tools его не вызывают. Восстановление вручную: остановить API/воркер, подменить файл БД, поднять процессы. Копии `state.json`, сессий и роликов бэкап **не** включает.

Список копий: `GET /api/maintenance/backups`.

## Диагностика

1. `diagnose` — воркер (pid / heartbeat), Ollama (reachable, модели), свежие ошибки, хвост лога.
2. `test_connection` / «Подключение» — прокси + сессия на диске; для Studio это не «Google ещё пускает».
3. Челлендж Instagram — Telegram (если задан) и файл в `data/challenges/`; CLI `provide-code`.
4. VNC: `python -m app.cli browser-vnc-diag` на хосте контейнера.
5. `preflight` — грубые дыры перед стартом воркера.

Не списывать любую ошибку на «прокси»: цитировать поле `ошибка` инструмента.

## Telegram

Необязательно. `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID` в `.env`. Если оба заданы, воркер шлёт короткие алерты (челлендж, blocked, мёртвый прокси и т.п.) и пишет `Event` в БД даже при сбое доставки. Токен в документы не копировать. Это не чат панели и не «подключить Ollama к Telegram».

События также на Панели («Последние события»).
