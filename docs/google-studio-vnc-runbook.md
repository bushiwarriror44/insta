# YouTube Studio / Google signin/rejected — runbook оператора

Страница **«Couldn't sign you in»** (`accounts.google.com/.../signin/rejected`) после email — отказ anti-bot Google к **Playwright Chromium** (или к IP прокси), а не сбой noVNC или paste API. HEAD `HTTP 200` на studio.youtube.com **не** означает, что интерактивный вход разрешён.

Подробнее о сессиях: [accounts-sessions.md](accounts-sessions.md).

## Быстрый обход (рекомендуется): импорт `state.json` с домашнего Chrome

1. На **доверенном ПК** откройте обычный **Google Chrome** (не Chromium), желательно с residential IP того же региона, что прокси аккаунта.
2. Войдите в [studio.youtube.com](https://studio.youtube.com) до рабочего интерфейса (2FA при необходимости).
3. Сохраните Playwright storage state в `state.json` (cookies + localStorage):
   - экспорт через админку с машины, где логин уже прошёл (`GET /api/accounts/{username}/playwright-state`), **или**
   - локальный скрипт Playwright: `context.storage_state(path="state.json")` после ручного логина.
4. Скопируйте файл на VPS (путь записи для YouTube):
   - `data/playwright/youtube/<username>/state.json`
   - пример:
     ```bash
     scp state.json root@VPS:/opt/insta/data/playwright/youtube/AuraBluekudsv/state.json
     ```
5. В админке: **Подключение** для аккаунта (при необходимости с probe Studio).
6. Используйте VNC дальше только для **2FA / обновления сессии**, не как основной способ первого Google-login.

Импорт через чат: `import_cookies` — см. [assistant-handbook.md](assistant-handbook.md).

## Проверки на VPS

```bash
cd /opt/insta
docker compose exec reels-api ls -la data/playwright/youtube/<username>/
docker compose exec reels-api python -m app.cli proxy-studio-check <username>
docker compose exec reels-api python -m app.cli browser-vnc-diag <username>
```

## Прокси

- Смените mobile/residential IP, если после импорта Studio снова ведёт на вход или rejected.
- Строки про `instagram login reachable=False` в логах VNC **не** относятся к YouTube.

## В VNC до импорта (низкий шанс успеха)

- Не жмите «Google автозаполнение».
- Ввод email с клавиатуры noVNC (не обязательно «Вставить в VNC») — отказ может повториться на том же IP.
- «Вставить в VNC» **не** обходит rejected: Google решает по браузеру и IP, не по способу ввода.

## Опция: branded Google Chrome в VNC (`BROWSER_VNC_CHANNEL=chrome`)

Снижает часть эвристик против bundled Chromium, **не** заменяет плохой IP прокси.

1. В контейнере один раз:
   ```bash
   docker compose exec reels-api bash /app/scripts/install_google_chrome_bookworm.sh
   docker compose exec reels-api python -m app.cli install-playwright --browser chrome
   ```
2. В `.env` или `docker-compose.yml` для `reels-api`: `BROWSER_VNC_CHANNEL=chrome`
3. Перезапуск: `docker compose up -d reels-api`

Headless Studio login (воркер): опционально `PLAYWRIGHT_STUDIO_CHANNEL=chrome` — только если Chrome установлен в **том же** образе.
