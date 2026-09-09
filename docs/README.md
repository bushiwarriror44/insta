# Документация панели

Панель публикует короткие видео в **Instagram**, **YouTube Shorts** и **TikTok** с этой машины. Graph / YouTube Data API / TikTok Content Posting API и OAuth **не используются**.

Этот каталог — руководства для оператора. Чат внизу панели читает только сжатый [`assistant-handbook.md`](assistant-handbook.md); его не раздувать.

**Не публикуйте** в тикеты и чаты: секретный путь панели (`entry_path`), мастер-пароль, `ADMIN_TOKEN`, пароли аккаунтов, TOTP, cookies, URL прокси с логином.

## С чего начать

1. Скопировать `.env.example` → `.env`, задать `ADMIN_TOKEN` (и при необходимости ключ fal, Telegram).
2. Локально: `python -m app.cli init-db`, затем `python -m app.cli run-api` (API `:8000`) и фронтенд Vite `:5173`.
3. Docker: `docker compose up -d --build` — UI обычно на `:3000`, API `:8000`.
4. Открыть панель по **секретному пути** из настроек (страница «Настройки» / `python -m app.cli status`). Корень без пути отдаёт ошибку.
5. Сначала прокси, потом аккаунт, потом сессия площадки, потом ролик из библиотеки и воркер.

Подробности запуска: [setup.md](setup.md).

## Оглавление

| Файл | О чём |
| --- | --- |
| [overview.md](overview.md) | Площадки, неофициальные клиенты, три «агента», что не для этой панели |
| [setup.md](setup.md) | `.env`, локальный запуск, Docker `reels-*` |
| [panel.md](panel.md) | Все страницы UI, кнопки, что делает чат |
| [accounts-sessions.md](accounts-sessions.md) | Прокси, Instagram vs Studio, автовход, VNC |
| [publishing.md](publishing.md) | Библиотека, очередь, статусы, uniquify |
| [generation.md](generation.md) | fal.ai, склейка, контент-план на странице «Агент» |
| [assistant.md](assistant.md) | Нижний чат vs `POST /api/assistant/run` и `cli ask` |
| [cli.md](cli.md) | Команды `python -m app.cli …` |
| [data-and-ops.md](data-and-ops.md) | Каталоги `data/`, логи, бэкап, Telegram |
| [api.md](api.md) | Auth, OpenAPI, chat/run, браузерные маршруты |
| [assistant-handbook.md](assistant-handbook.md) | Справочник модели чата (не раздувать) |

Вложенный каталог `content-factory/` в репозитории **не** является рабочим стеком этой панели.
