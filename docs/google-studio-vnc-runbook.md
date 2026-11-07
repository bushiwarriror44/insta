# YouTube Studio / Google signin/rejected — runbook оператора

Страница **«Couldn't sign you in»** (`accounts.google.com/.../signin/rejected`) после email — отказ anti-bot Google к **браузеру под CDP (Playwright)** и/или к IP прокси, а не сбой noVNC. HEAD `HTTP 200` на studio.youtube.com **не** означает, что интерактивный вход разрешён.

## Первый вход из админки (рекомендуется): native Chrome без Playwright

По умолчанию `STUDIO_VNC_NATIVE_CHROME=true`: YouTube/TikTok VNC запускает **google-chrome-stable** subprocess с `--user-data-dir` на volume, **без** Playwright и без `--remote-debugging-port`. Логин — только с клавиатуры noVNC; «Вставить» и «Код» в этом режиме недоступны.

1. Карточка YouTube → **Браузер** → дождитесь в логах `native Chrome (без CDP)`.
2. В noVNC войдите в Google / Studio (email, пароль, 2FA).
3. **Сохранить сессию** — API останавливает Chrome, экспортирует `data/playwright/youtube/<username>/state.json` из профиля.
4. **Проверка подключения** с `probe_studio=true`.

Профиль Chrome: `data/playwright/youtube/<username>/chrome_profile/`. Отключить native: `STUDIO_VNC_NATIVE_CHROME=false` (fallback на Playwright — выше риск `signin/rejected`).

Если rejected **и в native Chrome** — смените прокси (mobile/residential), не только канал браузера.

## ERR_NO_SUPPORTED_PROXIES (страница «This site can’t be reached»)

Chrome **не принимает** логин/пароль в `--proxy-server` (`http://user:pass@host:port` → ошибка). В native-режиме API поднимает **локальный forwarder** на `127.0.0.1` и передаёт Chrome только `http://127.0.0.1:<port>`; учётные данные уходят на upstream через `Proxy-Authorization`.

Если ошибка остаётся: проверьте, что прокси аккаунта — **HTTP** с логином (не SOCKS5 с паролем; для SOCKS+auth — `STUDIO_VNC_NATIVE_CHROME=false` или смените прокси). В логах сессии ищите `native_chrome proxy=… (auth=forwarder)`.

## Чёрный экран noVNC / «Native Chrome завершился»

Обычно Chrome **вышел сразу** (часто `SingletonLock` после прошлого краша). API снимает **устаревший** lock перед стартом и пишет stderr в  
`data/playwright/youtube/<username>/chrome_profile/native_chrome.stderr`.

1. В логе сессии (админка) — шаг `native_chrome` / `poll` / текст про Singleton.
2. Закройте браузер в UI, при необходимости на VPS (только если Chrome не запущен):

```bash
docker compose exec reels-api rm -f \
  data/playwright/youtube/<username>/chrome_profile/SingletonLock \
  data/playwright/youtube/<username>/chrome_profile/SingletonSocket \
  data/playwright/youtube/<username>/chrome_profile/SingletonCookie
```

3. Перезапустите VNC. Путь профиля — `youtube/`, не `Platform.youtube/`.

Подробнее о сессиях: [accounts-sessions.md](accounts-sessions.md).

## Запасной путь: импорт `state.json` с домашнего Chrome

1. На **доверенном ПК** откройте обычный **Google Chrome** (не Chromium), желательно с residential IP того же региона, что прокси аккаунта.
2. Войдите в [studio.youtube.com](https://studio.youtube.com) до рабочего интерфейса (2FA при необходимости).
3. Сохраните Playwright storage state в `state.json` (cookies + localStorage):
   - экспорт через админку с машины, где логин уже прошёл (`GET /api/accounts/{username}/playwright-state`), **или**
   - локальный скрипт Playwright: `context.storage_state(path="state.json")` после ручного логина.
4. **Основной путь (без SSH):** в админке откройте браузер YouTube для аккаунта → **«Загрузить Playwright state»** → выберите файл. UI вызовет `POST .../cookies/import` и сразу **Проверку подключения** с `probe_studio=true`. Успех в toast: state на диске, Studio probe OK.
5. **Fallback для ops:** `scp` на VPS:
   - `data/playwright/youtube/<username>/state.json`
   - пример:
     ```bash
     scp state.json root@VPS:/opt/insta/data/playwright/youtube/AuraBluekudsv/state.json
     ```
   Затем вручную **Подключение** (probe Studio) в админке.
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

## Branded Google Chrome в VNC и на воркере (по умолчанию в Docker)

Образ `reels-api` / `reels-worker` собирается с **google-chrome-stable**; `docker-compose.yml` задаёт `BROWSER_VNC_CHANNEL=chrome` и `PLAYWRIGHT_STUDIO_CHANNEL=chrome`. Снижает часть эвристик против bundled Chromium, **не** заменяет плохой IP прокси.

Проверка после `docker compose build`:

```bash
docker compose exec reels-api python -m app.cli browser-vnc-diag
```

**Старый образ без Chrome** или локально без пересборки:

```bash
docker compose exec reels-api bash /app/scripts/install_google_chrome_bookworm.sh
```

Затем `BROWSER_VNC_CHANNEL=chrome` в `.env` / compose. На **ARM** или сборке с `INSTALL_GOOGLE_CHROME=0` оставьте `chromium`.

Chromium в volume: по-прежнему `docker compose exec reels-api python -m app.cli install-playwright` (Instagram и fallback).
