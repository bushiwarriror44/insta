# Аккаунты, прокси и сессии

Правило: **прокси обязателен**. Один аккаунт привязан к одной записи прокси. Смена прокси меняет IP — это осознанное действие («Сменить прокси» / `attach_proxy` / `rotate-proxy`).

Площадки в одной БД различаются парой `(platform, username)`.

## Лимиты и флаги аккаунта

| Поле | Смысл |
| --- | --- |
| `daily_post_cap` | потолок постов в сутки (1–20) |
| `min_gap_hours` | минимальный промежуток |
| `active_hour_start` / `active_hour_end` | часы активности в TZ аккаунта; конец строго больше начала |
| `timezone` | IANA; при создании часто берётся с прокси |
| `caption_profile` | стиль подписи: `nature` / `lifestyle` / `fitness` / `food` / `travel`, **не** прокси |
| `hold_for_review` | тумблер «проверка»: новая публикация из **чата** → `awaiting_review`, пока не `approve_job`. UI «запланировать» ставит `queued`. `publish_now` после успешной проверки сам одобряет |
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

Вход:

- Пароль (+ TOTP / backup-коды / IMAP email) в карточке.
- `first_login` — stealth Playwright, заполняет логин/пароль, только Instagram. CLI: `python -m app.cli first-login USER`.
- `mint_mobile_session` — выпустить mobile-сессию instagrapi.
- Живой браузер в UI (кнопка «Браузер») — VNC, вход руками, «Сохранить» пишет cookies. Из нижнего чата не стартует. Из `POST /api/assistant/run`: `start_browser`.

`session_id` в `update_account` / создании — **только Instagram**. На YouTube инструмент отвечает отказом.

## YouTube Shorts и TikTok (Studio)

Нет Data API и Content Posting API. Загрузка — Playwright, UI Studio на **английском**.

Сессия: cookies Google/YouTube или `tiktok.com` в `data/playwright/<username>/state.json`. Проверка подключения: прокси жив **и** на диске есть cookies площадки. Это **не** доказательство, что Google/TikTok ещё считают сессию живой. Антибот и срок кук панель не лечит.

Пароль аккаунта в карточке **не** логинит Google как instagrapi логинит Instagram. Сценарий: импорт cookies **или** живой браузер → войти руками (или `start_browser` + `save_browser_session`) → `publish_now`.

`media_id` после YouTube — URL страницы Studio, не id ролика Data API. TikTok: подпись до ~2200 символов.

Instagram-app User-Agent в Chromium Studio **не** подставляется.

## Проверка подключения

Кнопка «Подключение» / `test_connection`:

- Instagram: прокси + sessionid/файл + опционально Instagram reachable.
- YouTube/TikTok: прокси + Playwright state; `instagram_reachable` **не** валит Studio.

`publish_now` сначала делает ту же проверку; если не ok — задачу не ставит, ошибку цитирует.

## Живой браузер (VNC)

Нужны `BROWSER_VNC_ENABLED=true` и стек в контейнере. Старт: `POST /api/accounts/{username}/browser/start`. Код 2FA: `.../browser/code`. Сохранение: `.../browser/save`. Диагностика: `python -m app.cli browser-vnc-diag`.

Tools run-режима: `start_browser`, `browser_status`, `save_browser_session`, `submit_browser_code`.
