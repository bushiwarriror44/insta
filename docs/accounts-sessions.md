# Аккаунты, прокси и сессии

Правило: **прокси обязателен**. Один аккаунт привязан к одной записи прокси. Смена прокси меняет IP — это осознанное действие («Сменить прокси» / `attach_proxy` / `rotate-proxy`).

Чат при ошибке входа или прокси: секции «Если вход сломался» / «Если прокси сломался» в [`assistant-handbook.md`](assistant-handbook.md) + tool `diagnose` (блоки `login` / `proxies`).

Площадки в одной БД различаются парой `(platform, username)`.

## Чеклист стабильности (операции)

**Общее:** один аккаунт — один прокси; после смены прокси — `test_connection`; timezone аккаунта согласовать с прокси (смотрите `geo_mismatch`); Docker: volume `playwright-browsers` + `install-playwright`, не терять каталог `./data`.

**Instagram:** единый `login_surface` в карточке, в `first-login` и в `browser/start`; не включать `probe_mobile` без нужды (может сжечь web-cookie); не смешивать web (`state.json` / sessionid) и mobile dump; IMAP/TOTP в карточке до автовхода; стабильные профили на диске (`web_desktop_profile.json`, `playwright_chrome_major`) не сбрасывать без причины.

**YouTube / TikTok:** `proxy-studio-check` до VNC; первый вход — VNC с `STUDIO_VNC_NATIVE_CHROME=true` (native Chrome без CDP, см. [runbook](google-studio-vnc-runbook.md)); при повторном `signin/rejected` или сбое — импорт `state.json` с домашнего Chrome; `BROWSER_VNC_CHANNEL=chrome`, `PLAYWRIGHT_STUDIO_CHANNEL=chrome`, при медленном прокси — `BROWSER_GOTO_TIMEOUT_SEC=90`; перед публикацией — `test_connection?probe_studio=true`.

**Браузер Instagram (опционально):** `PLAYWRIGHT_INSTAGRAM_CHANNEL=chrome` в `.env`, если в образе установлен `google-chrome-stable` (как для Studio).

## Лимиты и флаги аккаунта

| Поле | Смысл |
| --- | --- |
| `daily_post_cap` | потолок постов в сутки (1–20) |
| `min_gap_hours` | минимальный промежуток |
| `active_hour_start` / `active_hour_end` | часы активности в TZ аккаунта; конец строго больше начала |
| `timezone` | IANA; при создании часто берётся с прокси |
| `caption_profile` | стиль подписи: `nature` / `lifestyle` / `fitness` / `food` / `travel`, **не** прокси |
| `hold_for_review` | тумблер «проверка»: enqueue (UI/API/чат) → `awaiting_review`, пока не `approve_job`. `publish_now` после ok `test_connection` сам одобряет → `queued` |
| `login_surface` | `mobile` или `desktop` — эмуляция Playwright / `first_login`, **только Instagram** |
| `cooldown_until` | мягкий бан / пауза площадки |

Статусы аккаунта: `active`, `paused`, `challenge`, `blocked`, `cooldown`.

## Прокси

URL вида `http://user:pass@host:port`. Метка уникальна. Health-check: IP (`PROXY_HEALTH_URL`), для Instagram ещё доступность login-хоста. «Проверить» / `test_proxy` / `test_proxies`. Чат не удаляет прокси.

## Instagram

Клиент: **instagrapi**, private mobile API, не Graph.

Две сессии, их нельзя смешивать как одну:

1. **Web** — cookie `sessionid` в БД, импорт Dolphin/Playwright, живой браузер. Файл Playwright: `data/playwright/<username>/state.json`.
2. **Mobile dump** — `data/sessions/session_*.json` после `mint_mobile_session` / логина instagrapi.

`probe_mobile` (проверка «как приложение») может **сжечь** web-cookie Dolphin. Не включать без нужды.

**Fingerprint** — Android-устройство в `data/devices/device_*.json`. Один на аккаунт, навсегда. Чужой отпечаток не импортировать. Для YouTube/TikTok fingerprint **нет**.

Стабильный браузерный Playwright-профиль Instagram (не путать с mobile dump instagrapi): **desktop** — UA/locale/viewport в `data/playwright/<username>/web_desktop_profile.json`; **mobile** — major Chrome в `device_settings.playwright_chrome_major` того же device-файла (задаётся при первом mobile VNC / `first_login`).

Вход:

- Пароль (+ TOTP / backup-коды / IMAP email + опционально `imap_host`) в карточке. Таб-строка продавца (`username`, пароль, email, пароль почты) — поле `vendor_line` при создании или вставка в `account_line` без `:`.
- `login_instagram` / `first_login` — stealth Playwright, при challenge опрос IMAP, затем при необходимости mobile API с `make_handler`. CLI: `python -m app.cli first-login USER`.
- `mint_mobile_session` — выпустить mobile-сессию instagrapi.
- Живой браузер в UI (кнопка «Браузер») — VNC, вход руками, «Сохранить» пишет cookies. Из нижнего чата не стартует. Из `POST /api/assistant/run`: `start_browser`.

`session_id` в `update_account` / создании — **только Instagram**. На YouTube инструмент отвечает отказом.

## YouTube Shorts и TikTok (Studio)

Нет Data API и Content Posting API. Загрузка — Playwright, UI Studio на **английском**.

Сессия: cookies Google/YouTube; стабильный desktop-профиль (UA/locale/viewport) в studio_desktop_profile.json рядом со state или `tiktok.com` в `data/playwright/<username>/state.json`. Проверка подключения: прокси жив **и** на диске есть cookies площадки. Это **не** доказательство, что Google/TikTok ещё считают сессию живой. Антибот и срок кук панель не лечит.

Автовход: **`login_account`** / кнопка «Создать сессию» (`POST …/first-login`) — headless Studio, при challenge VNC. Пароль + email (Google) в карточке. Импорт cookies или `start_browser` + `save_browser_session` — по-прежнему валидны.

`media_id` после YouTube — URL страницы Studio, не id ролика Data API. TikTok: подпись до ~2200 символов.

Instagram-app User-Agent в Chromium Studio **не** подставляется.

## Проверка подключения

Кнопка «Подключение» / `test_connection`:

- Instagram: прокси + sessionid/файл + опционально Instagram reachable.
- YouTube/TikTok: прокси + Playwright state; `instagram_reachable` **не** валит Studio.

`publish_now` сначала делает ту же проверку; если не ok — задачу не ставит, ошибку цитирует.

Для YouTube/TikTok опционально **`probe_studio=true`**: headless открытие Studio с cookies на диске; поле `studio_liveness_ok` (при `false` — warn hint, `overall_ok` может остаться true).

Для Instagram опционально **`probe_web=true`**: headless открытие instagram.com с Playwright `state.json`; поле `web_liveness_ok` (при `false` — warn, `overall_ok` обычно остаётся true в режиме cookies-only).

## Playwright / Docker (§0.7)

- **Windows host:** `PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright` после `python -m app.cli install-playwright`.
- **Docker (`reels-api` / `reels-worker`):** volume `playwright-browsers` смонтирован в `/ms-playwright`; env `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`. Один раз: `scripts/setup_docker_playwright.ps1` (или `.sh`) → `install-playwright` + `preflight`.
- **Staging gate:** `PREFLIGHT_STRICT_PLAYWRIGHT=1` — `preflight` падает, если Chromium не установлен.

## Живой браузер (VNC)

Нужны `BROWSER_VNC_ENABLED=true` и стек в контейнере. Старт: `POST /api/accounts/{username}/browser/start`. Код 2FA: `.../browser/code`. Сохранение: `.../browser/save`. Диагностика: `python -m app.cli browser-vnc-diag`.

Производительность noVNC: в UI заданы **quality=3** и **compression=8** (меньше трафика, грубее картинка). YouTube/TikTok используют compactный desktop **1024×640** на Xvfb (`BROWSER_STUDIO_VNC_WIDTH` / `BROWSER_STUDIO_VNC_HEIGHT`); Instagram desktop остаётся 1280×800.

YouTube/TikTok в VNC: при старте открывается Studio (ladder: Studio → Google accounts при fail). Если страница пустая — в UI будет **warning**; кнопки «Открыть Studio» / «Google автозаполнение». Навигация идёт **в фоне** — noVNC подключается до завершения `goto`. `browser-vnc-diag` в `docker compose exec` **не видит** in-memory сессию API — смотрите `GET .../browser/status`.

**Google «Couldn't sign you in» / `accounts.google.com/.../signin/rejected`:** отказ anti-bot (Chromium/Playwright в Docker, IP прокси). После email URL часто сразу `signin/rejected` — это **не** баг paste API.

**Обход rejected:**

1. Вход в **домашнем Google Chrome** → Studio открыт.
2. Импорт `state.json`: в панели браузера YouTube — **«Загрузить Playwright state»** (импорт + автоматический probe Studio); файл попадает в `data/playwright/youtube/<username>/state.json`. Альтернатива: `scp` — см. [google-studio-vnc-runbook.md](google-studio-vnc-runbook.md).
3. При загрузке через UI probe Studio уже выполняется; иначе — **Подключение** / `test_connection` в админке.
4. Смена прокси при повторном отказе; VNC — для 2FA, не для первого login.
5. В Docker по умолчанию `BROWSER_VNC_CHANNEL=chrome` и Chrome в образе (runbook) — не заменяет плохой IP.

**Буфер и VNC:** кнопки на панели копируют в локальный буфер ОС; `POST /api/accounts/{username}/browser/paste` вставляет текст в сфокусированное поле Chromium (Playwright). Для обмена с noVNC используйте иконку буфера в панели noVNC или сочетание из подсказки в UI (зависит от сборки noVNC).

Проверка прокси на Google с VPS (URL прокси из БД, без ручной подстановки USER/PASS):

```bash
bash deploy/proxy-studio-check.sh
docker compose exec reels-api python -m app.cli proxy-studio-check AuraBluekudsv
```

Эквивалент двух `curl -x … -I` на `studio.youtube.com` и `accounts.google.com`. При FAIL — смените прокси или IP; VNC не поможет.

Docker: для Studio в `reels-api` рекомендуется **≥2 GB** `mem_limit` (см. `docker-compose.yml`).

Tools run-режима: `start_browser`, `browser_status`, `save_browser_session`, `submit_browser_code`.
