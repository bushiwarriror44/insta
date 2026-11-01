# Чек-лист: аккаунты, прокси, сессии, публикация

Метод для каждого пункта: **Шаг → Ожидание → Где смотреть → Частые поломки**.  
Статус: `OK` / `FAIL` / `SKIP` / `GAP` (ограничение продукта, не баг).

Связанные документы: [accounts-sessions.md](accounts-sessions.md), [publishing.md](publishing.md), [assistant-handbook.md](assistant-handbook.md), общий gate: [qa-checklist.md](qa-checklist.md) §2–3–7–15.

Журнал ручного прогона (staging): [qa-accounts-publish-run-log.md](qa-accounts-publish-run-log.md).

## Журнал (заполняет QA)

| Дата | Версия / commit | Исполнитель | §0 | §1–§4 | §5–§6 | pytest §10 | Примечание |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-01 | local | agent | **DOC OK** | §1–§4 doc rev | **DOC OK** §6–§7 | §6 **21** + §7 **34** pytest; Vitest **8** | ревизия §0–§7; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | **DOC OK** | §1–§4 doc rev | **DOC OK** §5 | §5 **111** pytest + Vitest **21** | ревизия §0–§5; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | **DOC OK** | §1–§4 doc rev | SKIP | §4 **44** pytest + Vitest **9** | ревизия §0–§4; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | **DOC OK** | §1–§3 doc rev | SKIP | §3 **145** pytest + Vitest **14** | ревизия §0–§3; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | **DOC OK** | §1–§2 doc rev | SKIP | §2 **19** pytest + Vitest **4** | ревизия §0–§2; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | **DOC OK** | §1 doc rev | SKIP | §1 **40** passed; hints **20**; Vitest hints **14** | ревизия §0–§1; [run-log](qa-accounts-publish-run-log.md) |
| 2026-11-01 | local | agent | SKIP | SKIP | SKIP | **115+154 passed**, Vitest **67** | commit `7604b54`; детали в [qa-accounts-publish-run-log.md](qa-accounts-publish-run-log.md) |

---

```mermaid
flowchart TB
  subgraph prep [Подготовка]
    Proxy[Прокси healthy]
    Acc[Account platform plus proxy_id]
    Sess[Session per platform]
  end
  subgraph conn [Подключение]
    TC[test_connection]
    FL[first_login / browser / import]
  end
  subgraph pub [Публикация]
    ENQ[enqueue / publish_now]
    WK[reels-worker]
    Plat[IG instagrapi or Studio Playwright]
  end
  Proxy --> Acc --> Sess --> TC
  TC -->|fail| FL
  TC -->|ok| ENQ --> WK --> Plat
```

---

## 0. Подготовка среды (обязательно перед сценариями)

| # | Проверка | Шаг | Ожидание | Где смотреть | Частые проблемы |
| --- | --- | --- | --- | --- | --- |
| 0.1 | Стек жив | `docker compose up -d --build` (или api+worker локально) | `GET /api/health` → ok; UI открывается | Браузер, `curl` | worker не поднят → очередь не едет |
| 0.2 | Общий `data/` | У `reels-api` и `reels-worker` один том `./data` → `/app/data` (`docker-compose.yml`) | Один `app.db`, WAL; сессии на диске видны обоим | `data/app.db`, `data/playwright/`, `data/sessions/` | разные тома → worker «не видит» cookies |
| 0.3 | Preflight worker | `docker compose exec reels-worker python -m app.cli preflight` | ffmpeg; предупреждение если Playwright cache пуст | CLI вывод | publish/uniquify падает без ffmpeg |
| 0.4 | Воркер включён | Тумблер «Агент» / worker alive | `diagnose` → `worker.ours_alive` или heartbeat не stale | UI Панель, чат `diagnose` | задачи `queued` вечно |
| 0.5 | Роли | owner vs operator | operator: нет паролей/sessionid в API; browser secrets — owner | `GET /api/auth/me`, Accounts UI | «не могу войти» = роль |
| 0.6 | VNC (если Studio/IG browser) | `BROWSER_VNC_ENABLED=true` в `.env` | `browser-vnc-diag` / UI «Браузер» не 503 | [accounts-sessions.md](accounts-sessions.md) | headless challenge без VNC |
| 0.7 | Playwright (API / IG browser) | `docker compose exec reels-api python -m app.cli install-playwright`; Windows: `PLAYWRIGHT_BROWSERS_PATH` | `preflight` без «кэш playwright пуст»; browser/first-login не 503 | `.env.example`, §3.5 user_hint | GAP в Docker без install — run-log |

**Автоматика gate:** `python -m pytest tests/ -q`, `cd frontend && npm test -- --run`. Фокус после login/hints — §10.

---

## 1. Прокси (пул, health, привязка к аккаунту)

### 1.1 Создание и CRUD

| # | Шаг | Ожидание | UI / API | Частые проблемы |
| --- | --- | --- | --- | --- |
| 1.1.1 | Создать прокси с уникальной `label`, URL `http://user:pass@host:port` | **200**, запись в списке | Accounts → «Прокси»; `POST /api/proxies` | неверный URL → health fail |
| 1.1.2 | Повторный `POST` с тем же `label` | **200 upsert** — обновляет URL/country/timezone (`upsert_proxy`) | API | не путать с 409 при delete |
| 1.1.3 | Удалить прокси **с** привязанными аккаунтами | 409, аккаунты не orphan | API | |
| 1.1.4 | Удалить прокси без аккаунтов | **200** `{"ok": true}` | API | |

### 1.2 Health-check и гео

| # | Шаг | Ожидание | UI / API | Частые проблемы |
| --- | --- | --- | --- | --- |
| 1.2.1 | «Проверить» один прокси | `is_healthy`, IP, `last_geo_country` | карточка прокси | `PROXY_HEALTH_URL` недоступен с VPS |
| 1.2.2 | Пакетная проверка | прогресс N/N, таблица обновилась | вкладка «Проверка» | |
| 1.2.3 | Фильтр geo-mismatch | строки с `geo_mismatch_warning` | фильтр на proxy-check | advertised country ≠ фактический IP |
| 1.2.4 | Фильтр ig-bad | `instagram_reachable === false` только для IG probe | proxy-check | **GAP:** кэш health in-process — API и worker могут расходиться ([qa-checklist.md](qa-checklist.md) §2) |
| 1.2.5 | Чат `test_proxy` / `test_proxies` | тот же смысл, что UI | Assistant | operator: URL маскируется |
| 1.2.6 | Прокси fail в «Подключение» | toast/`user_hint` с `action_key=attach_proxy` | §3.5, Accounts connection modal | см. §4 proxy step |

### 1.3 Привязка прокси к аккаунту

| # | Шаг | Ожидание | UI / API | Частые проблемы |
| --- | --- | --- | --- | --- |
| 1.3.1 | Создать аккаунт **без** существующего `proxy_label` | 400 «прокси не найден» | форма / `POST /api/accounts` | правило: прокси обязателен |
| 1.3.2 | Создать IG `@user1` на `proxy-A` | `proxy_id` set, timezone от прокси если placeholder | Accounts | |
| 1.3.3 | Создать второй аккаунт **той же** площадки с тем же username | upsert существующей строки `(platform, username)` | API | UNIQUE index |
| 1.3.4 | «Сменить прокси» / `PUT /api/accounts/{username}/proxy` | новый `proxy_id`, предупреждение о смене IP | UI | старые cookies могут быть привязаны к старому IP |
| 1.3.5 | Два аккаунта на **одном** прокси | разрешено (осознанный риск) | | бан по IP на всех |

**Автоматика:** `tests/unit/test_proxies_pool.py`, `test_api_routes.py` (proxies), `test_connection_test.py` (proxy check/batch), `test_assistant_tools.py` (`create_proxy`, `test_proxy`).

---

## 2. Создание аккаунтов по площадкам

| Площадка | Обязательно при создании | Сессия (тип) | Пароль / 2FA | Особенности UI |
| --- | --- | --- | --- | --- |
| **Instagram** | proxy, username, password (или `account_line` / `vendor_line`) | `session_id` (web), файл `session_*.json` (mobile), Playwright state | TOTP, backup codes, IMAP | `login_surface` mobile/desktop; fingerprint device |
| **YouTube** | proxy, username; пароль **опционален** в API | Playwright `data/playwright/<user>/state.json` | Google login в карточке | **`session_id` в API → 400** |
| **TikTok** | proxy, username; пароль **опционален** в API | тот же Playwright path | как Google | Studio UI **английский** |

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 2.1 | UI: platform instagram / youtube / tiktok | поля формы меняются (IG: session, surface; Studio: без session_id) | путаница session_id для YT |
| 2.2 | `account_line` (UI «строка продавца») и/или `vendor_line` | username, password, email, email_password распарсены | неверный формат → 400 |
| 2.3 | `POST /api/accounts`, `caption_profile`, caps, active hours | **201** на create; upsert при повторе `(platform, username)` — см. §1.3.3; end > start | не путать **201** с proxies **200** |
| 2.4 | `hold_for_review=true` | `POST /api/jobs` и UI enqueue → **`awaiting_review`**; чат **`publish_now`** после ok connection → auto-`approve_job` → **`queued`** | см. §5.3.1–5.3.2 |
| 2.5 | Чат `create_account` / `create_accounts` | partial success: `created` + `failed` | выдуманный proxy_label |
| 2.6 | CLI `add-account --platform instagram\|youtube\|tiktok` | пароль **обязателен** в CLI; все три платформы | `session_id` в CLI **не** валидируется как в API — см. §9 GAP |
| 2.7 | Повтор `POST` с тем же `(platform, username)` | upsert существующей строки | см. §1.3.3 |

**Автоматика:**

```text
tests/unit/test_vendor_line.py
tests/unit/test_cli.py (add-account, platform youtube)
tests/unit/test_factory_merge.py (same username / different platform)
tests/unit/test_api_routes.py (create, hold_for_review enqueue, youtube without password)
tests/unit/test_assistant_tools.py (create_account, create_accounts partial)
frontend/src/pages/__tests__/Accounts.test.tsx (platform cards, add payload)
```

---

## 3. Сессии и cookies (отдельно на аккаунт)

### 3.1 Instagram — web sessionid

| # | Шаг | Ожидание | Файлы / API | Частые проблемы |
| --- | --- | --- | --- | --- |
| 3.1.1 | Вставить `session_id` в модалке «Сессия» / `PUT .../session` | сохранён в БД; **не** авто-`testConnection` после save (by design) | `SessionSetupModal.tsx` | |
| 3.1.2 | Импорт Dolphin JSON | cookies → sessionid | `POST .../cookies/import` | неверный формат |
| 3.1.3 | Экспорт cookies | JSON Dolphin или txt | `GET .../cookies/export` | |
| 3.1.4 | `GET .../session` | IG: sessionid (operator: маска); без exportable sessionid → **404** «Сессия не найдена» | | **GAP:** Studio с cookies на диске — не IG sessionid; UI Studio через browser/import, не этот GET ([qa-checklist.md](qa-checklist.md) §3) |
| 3.1.5 | После `session_id` (POST upsert или `PUT .../session`, **только IG**) | `clear_session_file` + `clear_playwright_state` — legacy IG `data/playwright/<user>/state.json`; scoped `youtube/`/`tiktok/` **не** трогаются | `accounts.py` | YT/TT: API отклоняет `session_id` — см. `test_api_studio_login` |

### 3.2 Instagram — mobile (instagrapi)

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 3.2.1 | «Mint mobile session» / `POST .../mint-mobile-session` | файл `data/sessions/session_*.json` | нет proxy / bad password |
| 3.2.2 | `test_connection` **без** `probeMobile` | web path ok | |
| 3.2.3 | `test_connection` **с** `probeMobile: true` (query `probe_mobile=true`) | mobile probe только IG; Studio → fail «probe_mobile только для Instagram» | **риск сжечь web Dolphin** — handbook |
| 3.2.4 | Device fingerprint | один `data/devices/device_*.json` на аккаунт; импорт POST fingerprint | чужой fingerprint → бан |

### 3.3 Instagram — Playwright / VNC

| # | Шаг | Ожидание | API | Частые проблемы |
| --- | --- | --- | --- | --- |
| 3.3.1 | `POST .../browser/start` | VNC URL, status | `app/api/routes/browser.py` | **GAP:** in-memory sessions — несколько uvicorn workers |
| 3.3.2 | Вход руками → `POST .../browser/save` | `state.json` обновлён | | |
| 3.3.3 | 2FA → `POST .../browser/code` | | | |
| 3.3.4 | `first-login` headless | ladder logs: reuse → playwright → mobile_api → … | `ConnectionLadder` | challenge → нужен VNC |
| 3.3.5 | Чат `start_browser` | **owner:** `POST /api/assistant/run` (browser tools включены); stream — только с `allow_browser` в теле **и** owner. **Operator:** browser tools недоступны. В оркестрации входа — `save_browser_session` / `browser_status` / code tools (`LOGIN_ORCH_BROWSER_TOOLS`) | | нижний stream без `allow_browser` → ToolError |

### 3.4 YouTube / TikTok — Studio cookies

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 3.4.1 | Импорт Playwright storage state | IG: `data/playwright/<user>/state.json`; YT/TT: `data/playwright/<platform>/<user>/state.json` | cookies google/youtube или tiktok.com |
| 3.4.2 | `first-login` Studio headless | ladder `studio_headless` / VNC | антибот Google |
| 3.4.3 | `test_connection` | ok = proxy healthy **и** cookies на диске | **не** доказывает живость у Google/TikTok ([accounts-sessions.md](accounts-sessions.md)) |
| 3.4.4 | `instagram_reachable` на прокси | **не** валит Studio check | ложное «IG плохой → Studio fail» — не должно |
| 3.4.5 | UI Studio: английский Chrome | селекторы upload | локаль UI ≠ en → FAIL upload |

**Автomatika §3:**

```text
tests/unit/test_api_routes.py (session PUT/GET, cookies import/export, mint-mobile)
tests/unit/test_api_studio_login.py (session_id rejected YT, playwright preserved)
tests/unit/test_mint_mobile_session.py
tests/unit/test_session_manager.py
tests/unit/test_session_export.py
tests/unit/test_playwright_session.py
tests/unit/test_first_login_service.py
tests/unit/test_studio_login_service.py
tests/unit/test_connection_ladder.py
tests/unit/test_connection_test.py (studio, probe_mobile, youtube without IG reach)
tests/unit/test_login_autonomy.py
tests/api/test_accounts_first_login.py
tests/unit/test_assistant_tools.py (import_cookies, get_session mask, mint)
frontend/src/components/__tests__/SessionSetupModal.test.tsx (no auto testConnection after save)
```

### 3.5 Подсказки оператору (`user_hint`)

После `first-login` и «Подключение» API возвращает поле `user_hint` (severity, title, message, steps). UI показывает короткий **toast** и при необходимости **баннер** под логом (модал «Настройка сессии», панель проверки на «Аккаунты»). Агент в JSON инструментов `login_account`, `test_connection`, `ensure_account_session` получает те же `user_hint`, `next_steps` и при сбое — `operator_message`; в ответе оператору агент должен процитировать `message` и первый шаг из `steps`, а не сырой `error`.

| # | Шаг | Ожидание |
| --- | --- | --- |
| 3.5.1 | IG first-login: challenge / IMAP fail | toast info/warn с русским текстом; steps в баннере |
| 3.5.2 | `test_connection`: session_missing / geo_mismatch | toast; action «Настроить сессию» (`open_session_setup`) — **session_missing/challenge**, не geo (geo — warn без action) |
| 3.5.3 | Чат `test_connection` после UI | тот же смысл в `user_hint`, что в toast |

**Автomatika §3.5:**

```text
tests/unit/test_account_hints.py
tests/unit/test_login_autonomy.py (user_hint on challenge payload)
tests/unit/test_login_tools.py (operator_message)
tests/unit/test_assistant_chat_helpers.py (merge_operator_message_into_reply)
frontend/src/lib/__tests__/accountHints.test.ts
frontend/src/components/__tests__/SessionSetupModal.test.tsx (user_hint banner/toast where covered)
```

---

## 4. «Подключение» (`test_connection`) — глубокая матрица

Источник логики: [`connection_test.py`](../app/accounts/connection_test.py).  
API: `POST /api/accounts/{username}/test-connection` — по умолчанию **cookies-only** (`probe_mobile=false`); mobile probe: query `probe_mobile=true` (только IG). Ответ обогащается полем `user_hint` — см. §3.5.

| # | Сценарий | Шаг | Ожидание `overall_ok` | Логи (DiagnosticLogPanel) |
| --- | --- | --- | --- | --- |
| 4.1 | IG: proxy ok + sessionid | Подключение на карточке / модал «Подключение» | ok | proxy_health, session_storage, session_probe, instagram_auth |
| 4.2 | IG: нет session | cookies-only проверка | fail, `error_code=session_missing` | `session_source: none` |
| 4.3 | IG: proxy dead | | fail на proxy step | proxy / proxy_health error |
| 4.4 | IG: geo_mismatch | cookies-only при наличии cookies | **`overall_ok` true** + warn (`user_hint` / toast); `geo_mismatch` true | mobile probe — отдельная политика |
| 4.5 | YT: proxy ok + state с cookies площадки | | ok | `session_probe`: Playwright state, «Cookies Studio на диске…» |
| 4.6 | YT: state без cookies | | fail | session_probe error |
| 4.7 | TT: аналог YT | та же ветка Studio в коде | как 4.5–4.6 | отдельного TT unit-теста нет — покрытие studio/YT |
| 4.8 | «Проверить все» на Accounts | последовательный `testConnection` **без** `probeMobile`; обновление строк прокси/сессии | summary «N с cookies» | **GAP:** долго при 50+ аккаунтах (UI sequential) |
| 4.9 | fail / session_missing | **нет** авто-открытия SessionSetup (§3.5); toast + action «Настроить сессию»; кнопка в модале «Подключение» | operator открывает вручную | |
| 4.10 | `publish_now` при fail connection | | **PostJob не создаётся**; ошибка из `test_connection` | gate перед постингом |

**Автomatika §4:**

```text
tests/unit/test_connection_test.py (4.1–4.6, geo, proxy dead, API happy path)
tests/unit/test_account_hints.py (connection hints: session_missing, geo warn)
tests/unit/test_assistant_tools.py (publish_now gate, test_connections batch)
frontend/src/pages/__tests__/Accounts.test.tsx (connection modal, probeMobile, «Проверить все»)
tests/unit/test_account_diagnostics.py (credential log shape — optional)
```

---

## 5. Публикация контента (по площадкам)

Статусы **`PostJob`** vs pipeline (`GenerationJob` / `CompositionJob`) — см. [publishing.md](publishing.md). Воркер забирает только **`queued`**; при остановленном агенте job может висеть без `running`.

### 5.1 Источник медиа

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 5.1.1 | Upload в библиотеку (DropZone) | файл в `data/videos/source` | |
| 5.1.2 | `asset_id` из рендера | путь в `media_dir` | |
| 5.1.3 | `filename` с `../` | 404 / sanitize | API vs **GAP:** CLI `enqueue-post --video` произвольный путь |
| 5.1.4 | `feed_photo` + не-image | fail на воркере | |
| 5.1.5 | V2V reference >15s trim | обрезка на generation, не publish | |

### 5.2 Тип поста vs platform

| platform | default `post_type` | файл |
| --- | --- | --- |
| instagram | reel (also feed_photo, feed_video) | video / photo |
| youtube | youtube_short | video |
| tiktok | tiktok | video, caption ≤ ~2200 |

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 5.2.1 | Publish без `post_type` (чат) | `post_type_for(platform)` — [`scheduling.py`](../app/services/scheduling.py) | |
| 5.2.2 | Несовместимый post_type / media | API `POST /api/jobs`: `_check_post_type`, image vs video | «для {platform} нельзя публиковать …» |
| 5.2.3 | YouTube success | `media_id` = Studio URL, не Data API id | |

### 5.3 Очередь и review

| # | Шаг | Ожидание | Частые проблемы |
| --- | --- | --- | --- |
| 5.3.1 | `hold_for_review` + enqueue (UI **или** `POST /api/jobs` / чат `enqueue_publish`) | **`awaiting_review`** (`initial_job_status`) | worker не claim — нужен «Одобрить» в Activity |
| 5.3.2 | `hold_for_review` + чат **`publish_now`** | `awaiting_review` → **auto-`approve_job`** после ok `test_connection` → **`queued`** | отличие от ручного enqueue |
| 5.3.3 | Worker claim | только **`queued`**, не `awaiting_review` | пост «завис» в review |
| 5.3.4 | Approve / cancel / retry | `POST .../jobs/{id}/approve`; UI Activity | missing source → 409 |
| 5.3.5 | `daily_post_cap`, `min_gap`, active hours | defer / skip slot | timezone аккаунта |
| 5.3.6 | `cooldown` / `challenge` / `blocked` на аккаунте | `_claim_due_job` не claim; `_process_job` requeue | нужен `provide-code` / resume |
| 5.3.7 | Uniquify (ffmpeg) | out в `data/videos/out`; fail ≠ «Instagram отклонил» | |
| 5.3.8 | `paused` | enqueue/API/чат job **можно** создать; worker **не claim** paused; если job уже в работе — requeue + warn в DiagnosticRun | не путать с «409 на enqueue» — см. §6 E2E-6 |

### 5.4 E2E smoke (staging, реальная сеть)

Из [qa-checklist.md](qa-checklist.md) §15 — **нет в CI**:

| # | Сценарий | Минимальные шаги | Критерий успеха |
| --- | --- | --- | --- |
| 5.4.1 | IG reel | connection ok → enqueue короткий mp4 → worker running → done | permalink/log |
| 5.4.2 | YT Short | Studio session → youtube_short → done | Studio URL в логе |
| 5.4.3 | TikTok | аналог | |
| 5.4.4 | Без сети | hold_for_review + API enqueue | `awaiting_review`, worker idle |

**Автomatika §5 (без реальной сети):**

```text
tests/unit/test_worker.py (claim, caps, gap, cooldown, IG/YT/TT dispatch, uniquify)
tests/unit/test_reels_publisher.py (IG publish paths, errors)
tests/unit/test_review.py (initial_job_status, approve)
tests/unit/test_api_routes.py (enqueue, hold_for_review, approve/cancel/retry, feed_photo)
tests/unit/test_factory_merge.py (post_type_for)
tests/unit/test_assistant_tools.py (enqueue_publish, publish_now, approve_job, path traversal)
frontend/src/pages/__tests__/Upload.test.tsx
frontend/src/pages/__tests__/Publishing.test.tsx (enqueue payload)
```

§5.4 E2E — **GAP/SKIP** в CI (см. run-log). Ручной smoke YouTube/TikTok (очередь + `hold_for_review`):

```powershell
python scripts/qa_studio_publish_smoke.py --username-yt USER --username-tt USER
# реальный upload через worker после approve:
python scripts/qa_studio_publish_smoke.py --username-yt USER --execute
python -m app.cli preflight   # worker должен быть up
```

Сводка: `data/qa_studio_publish_smoke.json`. Liveness cookies (без upload): `python scripts/qa_studio_liveness_batch.py --imported-only` → `data/qa_studio_liveness_summary.json`; API `POST .../test-connection?probe_studio=true`.

---

## 6. Сквозные сценарии (выявляют «стыки»)

| ID | Сценарий | Шаги | Что часто ломается | CI / automatika |
| --- | --- | --- | --- | --- |
| E2E-1 | Новый IG end-to-end | proxy → account → session (import OR first-login) → test ok → upload → publish → done | probe_mobile после web; worker off | **GAP/SKIP** staging; unit — §3–§5 narrow |
| E2E-2 | Смена прокси после login | login ok → rotate proxy → test fail until re-login | IP/session mismatch | **AUTO OK** rotate/attach: `test_cli` `rotate-proxy`, `test_assistant_tools` `attach_proxy`; re-login **SKIP** |
| E2E-3 | Два platform same username | `@brand` instagram + `@brand` youtube | путаница в UI фильтров; enqueue без `account_id` | **AUTO OK** `test_same_username_allowed_on_different_platforms`, `test_enqueue_rejects_duplicate_username_without_account_id` |
| E2E-4 | Studio через browser only | без пароля → start_browser → save → test ok → publish | VNC disabled | **GAP/SKIP** staging; §3 browser/VNC |
| E2E-5 | Чат «подключись и опубликуй» | `test_connections` + `publish_now` | worker не стартует, но job создан | **AUTO OK** `publish_now_*`, `test_connections`; **GAP** мёртвый worker — `note` в ответе (§9) |
| E2E-6 | Pause account | pause → **worker не постит** (job в очереди возможен) | ожидание «enqueue заблокирован» — **не так** | **AUTO OK** `test_claim_due_job_skips_paused_accounts`, §5.3.8; `pause_account` |
| E2E-7 | Proxy / job mid-flight | **7a:** delete in-use → **409**; **7b:** proxy unhealthy во время job → defer/requeue + Event | literal delete при running job — редко | **7a AUTO OK** `test_proxies_delete_blocked_when_in_use`; **7b AUTO OK** `test_process_job_proxy_unhealthy_temporary`; delete mid-flight **GAP** |

**Автomatika §6 (partial, без staging):**

```text
tests/unit/test_factory_merge.py (same_username)
tests/unit/test_cli.py (rotate-proxy, pause/resume)
tests/unit/test_worker.py (claim skip paused, proxy unhealthy job)
tests/unit/test_api_routes.py (proxies delete 409, enqueue duplicate username)
tests/unit/test_assistant_tools.py (attach_proxy, pause, publish_now, test_connections)
tests/unit/test_first_login_service.py (attach_proxy chain)
```

---

## 7. Чат vs UI — паритет (регрессии)

| Действие | UI | Чат tool | Должно совпадать |
| --- | --- | --- | --- |
| Создать аккаунт | Accounts form | `create_account(s)` | proxy обязателен |
| Прокси | Proxies tab | `create_proxy`, `test_proxies` | health |
| Импорт cookies | Session modal | `import_cookies` | форматы json/txt |
| Подключение | Модал «Подключение» (`probeMobile: false`) | `test_connection(s)` (default `probe_mobile=False`) | overall_ok / user_hint |
| Проверка сессии (SessionSetup) | «Проверить сессию» — IG: `probeMobile: true` | чат без флага ≠ этот UI-путь | см. footnote **probe_mobile** |
| Публикация | Library / Calendar / Upload | `publish_now`, `enqueue_publish` | preflight `test_connection`; `publish_now` auto-approve при review (§5.3.2) |
| Pause / resume | Accounts → Пауза / Возобновить | `pause_account`, `resume_account` | статус в БД, proxy/password не трогаются |
| Прокси на аккаунт | attach в UI | `attach_proxy`; CLI `rotate-proxy` | label + health |
| Browser | InstagramBrowserPanel | `start_browser` (run, owner) | secrets только owner |
| Диагностика | DiagnosticLogPanel | `diagnose`, `describe` в чате | login/proxies/posting/worker блоки (§8) |
| Operator role | UI без паролей в списках | `as_owner=False` — mask session/proxy/account | `test_*_masks_*`, `test_attach_proxy_masks_url_for_operator` |

**Проверка паритета подключения:** один аккаунт — UI модал «Подключение» (не «Проверить сессию»), затем чат `test_connection` без `probe_mobile` → тот же `overall_ok` (с учётом **health cache GAP**).

**Footnotes (не регрессия):**

1. **Health cache GAP** — API и worker могут видеть разный proxy health в одном процессе (§9).
2. **probe_mobile** — только IG; UI «Проверить сессию» включает mobile probe; модал «Подключение» и чат по умолчанию — нет.
3. **Operator** — чат скрывает sessionid/proxy userinfo; owner видит полные карточки.

**Автomatika §7:**

```text
tests/unit/test_assistant_tools.py (create_*, import_cookies, test_connection, publish_now, mask, pause, attach_proxy, diagnose)
tests/unit/test_assistant_chat_helpers.py (describe)
frontend/src/pages/__tests__/Accounts.test.tsx (-t connection)
frontend/src/api/__tests__/client.test.ts (-t probe_mobile)
```

## 8. Диагностика при FAIL (что собрать)

1. **UI:** DiagnosticLogPanel на аккаунте после `test_connection` / `first-login` (метод ladder, proxy step, session source).
2. **API:** `GET .../login-debug-screenshot` (если доступен), `GET .../playwright-state` (owner).
3. **Чат:** `diagnose` → блоки `login`, `proxies`, `posting`, `worker`.
4. **Файлы:** `data/playwright/<username>/state.json`, `data/sessions/session_*.json`, `data/devices/device_*.json`.
5. **Worker:** `docker compose logs reels-worker --tail=200` вокруг `PostJob.id`.
6. **Events:** таблица events / `list_errors` в чате — нет ли секретов в plaintext (spot-check).

---

## 9. Известные GAP — не путать с регрессией

| GAP | Симптом «как баг» | Реальность | Закрытие (2026-11) |
| --- | --- | --- | --- |
| Health cache API≠worker | proxy ok в UI, fail в worker | in-process cache | без изменений |
| VNC multi-worker | browser start 404/random | один процесс uvicorn | без изменений |
| Studio test ok, publish fail | cookies протухли у Google | test не проверял живость | **`probe_studio=true`** → `studio_liveness_ok`; [`qa_studio_liveness_batch.py`](../scripts/qa_studio_liveness_batch.py) |
| `test_connection` ok после paste sessionid | publish 401 | mobile vs web session | `probe_mobile` осознанно |
| Open mode без token | полный доступ | deployment choice | без изменений |
| Нет e2e publish в CI | «всё зелёное, прод не постит» | нужен §5.4 smoke | [`qa_studio_publish_smoke.py`](../scripts/qa_studio_publish_smoke.py) (staging, не CI) |
| CLI `add-account --session-id` на YT/TT | session_id в БД, API бы отклонило | API: `session_id` только Instagram ([`accounts.py`](../app/api/routes/accounts.py)); CLI пока без той же проверки | без изменений |
| IG без IMAP onet | mint на email challenge | Meta + пароль IMAP в `inst.txt` | `provide-code` / `first-login --verification-code`; [`qa_batch_ig_first_login.py`](../scripts/qa_batch_ig_first_login.py) |
| Docker Playwright пуст | login/VNC fail в контейнере | volume без Chromium | `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, [`setup_docker_playwright.ps1`](../scripts/setup_docker_playwright.ps1); `PREFLIGHT_STRICT_PLAYWRIGHT=1` |

---

## 10. Рекомендуемый порядок прогона (1–2 дня QA)

1. §0 подготовка + автоматический pytest/vitest.
2. §1 прокси полностью на 2–3 тестовых URL (хороший, мёртвый, geo-mismatch).
3. §2–§4 по **одному** аккаунту на каждую platform (минимум 3 аккаунта).
4. §5.1–5.3 на staging с `hold_for_review` без реальной сети.
5. §5.4 один реальный пост на platform (если допустимо).
6. §6 E2E-1, E2E-2, E2E-5.
7. Заполнить [журнал прогона](qa-accounts-publish-run-log.md): пункт → OK/FAIL → скрин/log → issue.

**Фокус pytest после правок в login/publish:**

```bash
python -m pytest tests/unit/test_login_autonomy.py tests/unit/test_connection_test.py tests/unit/test_first_login_service.py tests/unit/test_studio_login_service.py tests/unit/test_worker.py tests/unit/test_reels_publisher.py tests/api/test_accounts_first_login.py -q
```

Дополнительно (§1 прокси + UI accounts):

```bash
python -m pytest tests/unit/test_proxies_pool.py tests/unit/test_connection_test.py -k "proxy" tests/unit/test_api_routes.py -k "proxies" tests/unit/test_assistant_tools.py -k "proxy or create_proxy" -q
cd frontend && npm test -- --run src/pages/__tests__/Accounts.test.tsx src/components/__tests__/SessionSetupModal.test.tsx src/lib/__tests__/accountHints.test.ts
```

§2 создание аккаунтов (narrow):

```bash
python -m pytest tests/unit/test_vendor_line.py tests/unit/test_cli.py tests/unit/test_factory_merge.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py -k "add_account or same_username or hold_for_review or youtube_account_create or create_account or create_accounts or vendor_line" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "add-account"
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "platform card"
```

§3 сессии (narrow):

```bash
python -m pytest tests/unit/test_api_routes.py tests/unit/test_api_studio_login.py tests/unit/test_mint_mobile_session.py tests/unit/test_session_manager.py tests/unit/test_session_export.py tests/unit/test_playwright_session.py tests/unit/test_first_login_service.py tests/unit/test_studio_login_service.py tests/unit/test_connection_ladder.py tests/unit/test_connection_test.py tests/unit/test_login_autonomy.py tests/api/test_accounts_first_login.py tests/unit/test_assistant_tools.py tests/unit/test_account_hints.py tests/unit/test_login_tools.py tests/unit/test_assistant_chat_helpers.py -k "session or cookies or mint_mobile or studio or youtube or probe_mobile or instagram_reachable or import_cookies or get_session or first_login or login_autonomy or account_hints or operator_message or merge_operator or orch or challenge or playwright_session or ladder or mint_mobile_session or export_session" -q
cd frontend && npx vitest run src/components/__tests__/SessionSetupModal.test.tsx
cd frontend && npx vitest run src/lib/__tests__/accountHints.test.ts
```

§4 подключение (narrow):

```bash
python -m pytest tests/unit/test_connection_test.py tests/unit/test_account_hints.py -k "connection or geo or session_missing or proxy or youtube or probe or instagram_reachable or happy or unhealthy or auth_failure or no_proxy or attached_proxy" tests/unit/test_assistant_tools.py -k "publish_now_does_not_enqueue or publish_now_youtube_skips or test_connections" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "connection"
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "Проверить все"
```

§5 публикация (narrow):

```bash
python -m pytest tests/unit/test_worker.py tests/unit/test_reels_publisher.py tests/unit/test_review.py tests/unit/test_factory_merge.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py -k "post_type or claim or cap or gap or cooldown or uniquify or youtube or tiktok or feed_photo or awaiting or approve or publish or reel or enqueue or jobs or hold_for_review or cancel or retry or enqueue_publish or publish_now or approve_job or path_traversal" -q
cd frontend && npx vitest run src/pages/__tests__/Upload.test.tsx
cd frontend && npx vitest run src/pages/__tests__/Publishing.test.tsx
```

§6 сквозные сценарии (narrow, partial CI):

```bash
python -m pytest tests/unit/test_factory_merge.py tests/unit/test_cli.py tests/unit/test_worker.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py tests/unit/test_first_login_service.py -k "same_username or rotate_proxy or claim_due_job_skips_paused or process_job_proxy or proxies_delete or publish_now or test_connections or attach_proxy or pause" -q
```

§7 чат vs UI (narrow):

```bash
python -m pytest tests/unit/test_assistant_tools.py tests/unit/test_assistant_chat_helpers.py -k "describe or diagnose or create_account or create_accounts or import_cookies or test_connection or publish_now or mask or attach_proxy or pause or list_operators or get_session" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "connection"
cd frontend && npx vitest run src/api/__tests__/client.test.ts -t "probe_mobile"
```

Hints/login:

```bash
python -m pytest tests/unit/test_account_hints.py tests/unit/test_login_autonomy.py tests/unit/test_login_tools.py -q
```
