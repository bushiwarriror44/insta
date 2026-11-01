# Журнал прогона: аккаунты / прокси / сессии / публикация

Шаблон для staging-QA по [qa-accounts-publish-checklist.md](qa-accounts-publish-checklist.md).  
Статусы: **OK** / **FAIL** / **SKIP** (нет доступа) / **GAP** (ожидаемое ограничение).

## Автоматический gate (локально / CI)

| Дата (UTC) | Commit | Команда | Результат |
| --- | --- | --- | --- |
| 2026-11-01 | local | §6–§7 Vitest (connection + probe_mobile) | **8 passed** — см. «Ревизия §6–§7» |
| 2026-11-01 | local | §6–§7 E2E / паритет (narrow pytest) | **21** + **34** passed — см. «Ревизия §6–§7» |
| 2026-11-01 | local | §5 публикация (narrow pytest) | **111 passed** — см. «Ревизия §5» |
| 2026-11-01 | local | §4 подключение (narrow pytest) | **44 passed** — см. «Ревизия §4» |
| 2026-11-01 | local | §3 сессии (narrow pytest) | **145 passed** — см. «Ревизия §3» |
| 2026-11-01 | local | §2 создание аккаунтов (narrow pytest) | **19 passed** — см. «Ревизия §2» |
| 2026-11-01 | local | §1 прокси (narrow pytest) | **40 passed** — см. «Ревизия §0–§1» |
| 2026-11-01 | `7604b54` | *(локальный прогон)* | §10 pytest focus (7 модулей) | **115 passed** |
| 2026-11-01 | `7604b54` | *(локальный прогон)* | §10 + прокси/diagnostics/studio API | **154 passed** |
| 2026-11-01 | *(локальный прогон)* | Vitest `Accounts.test.tsx` + `SessionSetupModal.test.tsx` | **67 passed** |

Команды:

```bash
# §1 прокси (ревизия 2026-11-01)
python -m pytest tests/unit/test_proxies_pool.py tests/unit/test_connection_test.py -k "proxy_check or proxy_check_batch or proxy_unhealthy or proxies_list_geo or run_account_connection_test_no_proxy or passes_attached_proxy" tests/unit/test_api_routes.py -k "test_proxies" tests/unit/test_assistant_tools.py::test_create_proxy_runs_health_check tests/unit/test_assistant_tools.py::test_test_proxy_reports_geo_mismatch -q

python -m pytest tests/unit/test_login_autonomy.py tests/unit/test_connection_test.py tests/unit/test_first_login_service.py tests/unit/test_studio_login_service.py tests/unit/test_worker.py tests/unit/test_reels_publisher.py tests/api/test_accounts_first_login.py -q

python -m pytest tests/unit/test_proxies_pool.py tests/unit/test_account_diagnostics.py tests/unit/test_api_studio_login.py -q

cd frontend && npm test -- --run src/pages/__tests__/Accounts.test.tsx src/components/__tests__/SessionSetupModal.test.tsx
```

**Не покрыто автоматикой:** §5.4 реальная публикация в сеть (не прогонялась в этой сессии).

---

## Прогон `accounts/` (2026-11-01, локально, Docker + host Python)

Источник: `scripts/import_accounts_folder.py` → 6 прокси `am-mobile-01..06`, 10 IG, 10 YT, 3 TT.  
Папка `accounts/` в `.gitignore`. Сводки без секретов: `data/qa_connection_test_summary.json`, `data/qa_studio_login_summary.json`.

| Блок | Результат | Заметка |
| --- | --- | --- |
| Импорт прокси | **OK** (6/6) | Health OK; `am-mobile-03` при импорте — geo warn (факт RU vs AM в URL) |
| Импорт аккаунтов | **OK** (23) | Round-robin прокси |
| §4 test_connection | **13 OK / 10 FAIL** | FAIL только IG: нет sessionid/Playwright IG state |
| Studio first-login (YT+TT) | **OK** (13/13) | `scripts/qa_batch_studio_login.py --imported-only` |
| IG first-login (пилот) | **FAIL** | Playwright: форма входа не найдена; mobile API: «Instagram is out of date» |
| Docker Playwright | **GAP → READY (код)** | Было: `playwright_browsers_available=False` в контейнере; см. «Session GAP fixes» — `setup_docker_playwright` |
| §0.1 стек | **OK** | `reels-api` :8000, frontend :3000, worker healthy |
| §5.4 publish E2E | **SKIP** | Нет тестового ролика + IG без сессии |

Команды повторного прогона:

```powershell
python scripts/import_accounts_folder.py
python -m app.cli refresh-app-versions data/app_versions.json
python -m app.cli sync-device-app-profiles
docker compose exec reels-api python -m app.cli install-playwright
python scripts/qa_batch_connection_test.py --imported-only
$env:PLAYWRIGHT_BROWSERS_PATH="$env:LOCALAPPDATA\ms-playwright"
python scripts/qa_batch_studio_login.py --imported-only
```

Instagram: импорт sessionid через UI «Сессия», VNC/browser login, или обновление mobile-клиента в коде; затем `first-login` / `mint-mobile-session`.

### Пилот после фикса IG (2026-11-01)

| Изменение | Статус |
| --- | --- |
| `instagrapi>=3.0.14`, `set_app` в `build_client` | **OK** |
| `sync-device-app-profiles`, `data/app_versions.json` | **OK** (449.0.0.52.84) |
| Mobile API «out of date» | **Исправлено** — CAA login 200, до email-challenge |
| Playwright форма (`chunyingshaonu`) | **FAIL** (скрин `data/playwright/chunyingshaonu/login_debug.png`) |
| Пилот `first-login` chunyingshaonu | **CHALLENGE** — код на email; IMAP onet.pl AUTH failed |
| Пилот `first-login` qingtiannuhai8 | **SKIP** | не гонялся (ожидается тот же challenge/IMAP) |

Дальше: проверить `email_password` в `accounts/inst.txt`, код через UI / `data/challenges/<user>.code`, или VNC.

### Follow-up: user_hint coverage + UX (2026-11-01)

| Изменение | Статус |
| --- | --- |
| `challenge_required` / rate-limit hints в connection_test | **OK** (unit `test_account_hints`) |
| `action_key` → toast actions; без авто-открытия модала сессии | **OK** |
| `operator_message` в финальном ответе агента | **OK** (`merge_operator_message_into_reply`) |
| Playwright: challenge до «форма не найдена» | **OK** (код) |
| Import `inst.txt`: warn IMAP/onet.pl | **OK** (`import_accounts_folder.py`) |
| Пилот first-login 2–3 IG (live) | **DONE** | host 2026-11-01 — см. «Пилот IG host» ниже |

### Пилот IG host (2026-11-01, Windows, `PLAYWRIGHT_BROWSERS_PATH`)

Скрипты: [`scripts/qa_imap_probe.py`](../scripts/qa_imap_probe.py), [`scripts/qa_batch_ig_first_login.py`](../scripts/qa_batch_ig_first_login.py). Сводки: `data/qa_imap_probe.json`, `data/qa_ig_first_login_summary.json` (без паролей).

| Наблюдение | Статус | Детали |
| --- | --- | --- |
| IMAP onet.pl (10 ящиков) | **FAIL** | все `AUTHENTICATIONFAILED` на `imap.poczta.onet.pl`; 4-е поле `inst.txt` не принимается как пароль IMAP |
| Mobile API (mint / ladder) | **PARTIAL** | IG password OK → **email challenge** на 4/4 пилотах mint; код не подтягивается без IMAP |
| `qingtiannuhai8` mint | **FAIL** | отдельно «Instagram is out of date» (device profile — `patch_device_app_profile_file` + retry) |
| Playwright first-login mobile (`yunshangshaonu`) | **FAIL** | «поля формы входа не найдены» → fallback API → тот же email challenge |
| Ручной код | **READY** | fix: `provide-code` / `data/challenges/<username>.code` (не email); см. `challenge.py` |
| IG `test_connection` | **0/10 OK** | после прогона — session по-прежнему none |

**Следующий шаг для сессии:** исправить **пароль IMAP** каждого `@onet.pl` в `accounts/inst.txt` (или UI «Пароль почты») и повторить `mint` **или** во время challenge: `python -m app.cli provide-code USER 123456`. Параллельные batch-прогоны не запускать — SQLite WAL (восстановлено re-import).

**Команды:**

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="$env:LOCALAPPDATA\ms-playwright"
python scripts/qa_imap_probe.py
python scripts/qa_batch_ig_first_login.py --imported-only --mint-only --usernames USER --pause-sec 5
python scripts/qa_batch_ig_first_login.py --imported-only --first-login-only --surface mobile --usernames USER
python -m app.cli provide-code USER 123456
python scripts/qa_batch_connection_test.py --imported-only
```

---

## Session GAP fixes (2026-11-01, код)

| Область | Статус | Команды / артефакты |
| --- | --- | --- |
| Studio liveness | **READY** | `POST .../test-connection?probe_studio=true`; `python scripts/qa_studio_liveness_batch.py --imported-only` → `data/qa_studio_liveness_summary.json` |
| Studio publish smoke | **READY** | `python scripts/qa_studio_publish_smoke.py --username-yt USER --username-tt USER`; `--execute` — enqueue с hold; approve + worker |
| IG challenge без IMAP | **READY** | `first-login USER --verification-code КОД`; `provide-code USER КОД`; UI SessionSetup показывает `data/challenges/<user>.code` |
| Docker Playwright | **READY** | `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` в compose; `scripts/setup_docker_playwright.ps1`; опц. `PREFLIGHT_STRICT_PLAYWRIGHT=1` |

```powershell
# Docker browsers (один раз на volume)
.\scripts\setup_docker_playwright.ps1

# YT/TT cookies vs живая Studio
python scripts/qa_studio_liveness_batch.py --imported-only

# Staging smoke (без сети по умолчанию — dry enqueue)
python scripts/qa_studio_publish_smoke.py --username-yt ElizabetKnoxrxvsx --username-tt JoelleBuursma9681

# IG mint + код (один аккаунт, не параллельно)
python -m app.cli first-login USER --verification-code 123456
python scripts/qa_batch_ig_first_login.py --imported-only --mint-only --usernames USER --pause-sec 5
```

---

## Prod merge migration (шаблон)

См. [`docs/migration-server-merge.md`](../docs/migration-server-merge.md).

| Шаг | Дата | Результат | Заметка |
| --- | --- | --- | --- |
| Локальный export | | | `python scripts/export_migration_bundle.py --out data/migration-bundle-….tar.gz` |
| Сервер backup | | | Maintenance → «Снять копию» |
| import --dry-run | | | `migration_import_report.json` |
| import merge | | | `--prefix qa-` |
| connection test | | | YT/TT ok, IG по факту |

---

## Ревизия чек-листа §6–§7 (2026-11-01)

Сверка §6 «Сквозные сценарии» и §7 «Чат vs UI» с worker ([`worker.py`](../app/scheduler/worker.py)), proxies delete ([`proxies.py`](../app/api/routes/proxies.py)), assistant tools/UI ([`Accounts.tsx`](../frontend/src/pages/Accounts.tsx)).

| Пункт | Статус | Заметка |
| --- | --- | --- |
| E2E-1 IG full chain | **GAP/SKIP** | staging; unit — §3–§5 narrow |
| E2E-2 rotate proxy | **AUTO OK** + **SKIP** re-login | `test_rotate_proxy`, `attach_proxy`; re-login вручную |
| E2E-3 same username | **AUTO OK** | factory merge + enqueue 409 без `account_id` |
| E2E-4 browser-only studio | **GAP/SKIP** | VNC/staging |
| E2E-5 chat publish | **AUTO OK** + **GAP** worker | `publish_now`, `test_connections`; dead worker `note` |
| E2E-6 pause | **DOC OK** | §5.3.8; enqueue не блокируется; worker skip claim |
| E2E-7 proxy mid-flight | **AUTO OK** + **GAP** | delete in-use 409; unhealthy job defer; literal delete mid-flight — manual |
| §7 parity table | **DOC OK** | probe_mobile paths, operator mask, pause/attach/diagnose |
| §7 footnotes | **DOC OK** | health cache + probe_mobile + operator |

**§6 narrow pytest:** **21 passed**.  
**§7 narrow pytest:** **34 passed**.  
**§7 Vitest:** **8 passed** — `Accounts.test.tsx` **7** (connection) + `client.test.ts` **1** (probe_mobile).

```bash
python -m pytest tests/unit/test_factory_merge.py tests/unit/test_cli.py tests/unit/test_worker.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py tests/unit/test_first_login_service.py -k "same_username or rotate_proxy or claim_due_job_skips_paused or process_job_proxy or proxies_delete or publish_now or test_connections or attach_proxy or pause" -q
python -m pytest tests/unit/test_assistant_tools.py tests/unit/test_assistant_chat_helpers.py -k "describe or diagnose or create_account or create_accounts or import_cookies or test_connection or publish_now or mask or attach_proxy or pause or list_operators or get_session" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "connection"
cd frontend && npx vitest run src/api/__tests__/client.test.ts -t "probe_mobile"
```

---

## Ревизия чек-листа §5 (2026-11-01)

Сверка §5 «Публикация» с [`jobs.py`](app/api/routes/jobs.py), [`review.py`](app/services/review.py), worker/publishers; выравнивание **§2.4** / [accounts-sessions.md](accounts-sessions.md) / [publishing.md](publishing.md) по `hold_for_review`.

| Пункт | Статус | Заметка |
| --- | --- | --- |
| §5.1 медиа | **DOC OK** | path traversal chat; GAP CLI §5.1.3 |
| §5.2 post_type | **AUTO OK** | `post_type_for`, API `_check_post_type`, worker dispatch YT/TT |
| §5.3.1–5.3.2 hold/review | **DOC OK** | enqueue → `awaiting_review`; `publish_now` → auto-approve |
| §5.3.3–5.3.7 worker queue | **AUTO OK** | claim skip review, caps, uniquify |
| §5.3.4 approve/cancel/retry | **AUTO OK** | `test_api_routes` jobs + `test_review` |
| §5.4 E2E сеть | **GAP/SKIP** | вне CI |

**§5 narrow pytest:** **111 passed**.  
**§5 Vitest:** **21 passed** — `Upload.test.tsx` **4** + `Publishing.test.tsx` **17**.

```bash
python -m pytest tests/unit/test_worker.py tests/unit/test_reels_publisher.py tests/unit/test_review.py tests/unit/test_factory_merge.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py -k "post_type or claim or cap or gap or cooldown or uniquify or youtube or tiktok or feed_photo or awaiting or approve or publish or reel or enqueue or jobs or hold_for_review or cancel or retry or enqueue_publish or publish_now or approve_job or path_traversal" -q
cd frontend && npx vitest run src/pages/__tests__/Upload.test.tsx
cd frontend && npx vitest run src/pages/__tests__/Publishing.test.tsx
```

---

## Ревизия чек-листа §4 (2026-11-01)

Сверка §4 «Подключение» с [`connection_test.py`](app/accounts/connection_test.py), API `user_hint`, UI ConnectionModal / «Проверить все».

| Пункт | Статус | Заметка |
| --- | --- | --- |
| 4.1–4.3 IG paths | **AUTO OK** | `test_connection_test` happy / no session / proxy unhealthy |
| 4.4 geo_mismatch | **DOC OK** | cookies-only: `overall_ok` true + warn; automatika hints |
| 4.5–4.6 YT Studio | **AUTO OK** | youtube ok/fail without IG reach |
| 4.7 TT | **DOC OK** | та же studio-ветка; отдельного TT unit нет |
| 4.8 test all | **DOC OK** | sequential cookies-only; Vitest «Проверить все» |
| 4.9 SessionSetup UX | **DOC OK** | toast + кнопка; Vitest обновлён (клик «Настроить сессию») |
| 4.10 publish gate | **AUTO OK** | `publish_now_does_not_enqueue`, youtube skips |
| 4.8 scale 50+ | **GAP** | sequential UI |

**§4 narrow pytest:** **44 passed**.  
**§4 Vitest:** **9 passed** — `-t "connection"` (7) + `-t "Проверить все"` (2).

```bash
python -m pytest tests/unit/test_connection_test.py tests/unit/test_account_hints.py tests/unit/test_assistant_tools.py -k "connection or geo or session_missing or proxy or youtube or probe or instagram_reachable or happy or unhealthy or auth_failure or no_proxy or attached_proxy or publish_now_does_not_enqueue or publish_now_youtube_skips or test_connections" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "connection"
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "Проверить все"
```

---

## Ревизия чек-листа §3 (2026-11-01)

Сверка §3 «Сессии и cookies» + §3.5 `user_hint` с API/UI/assistant; §4 не менялся.

| Пункт | Статус | Заметка |
| --- | --- | --- |
| §3.1 IG web sessionid | **DOC OK** | GET session 404 без sessionid; clear playwright IG-only |
| §3.1.1 no auto testConnection | **AUTO OK** | `SessionSetupModal.test.tsx` |
| §3.2 mobile / probe_mobile | **DOC OK** | query `probe_mobile`; Studio reject |
| §3.3 Playwright / VNC / chat browser | **DOC OK** | owner `/run`, stream `allow_browser`, operator без browser tools |
| §3.3.1 multi-worker VNC | **GAP** | §9 |
| §3.4 Studio paths + connection | **DOC OK** | scoped `playwright/<platform>/<user>/`; `test_youtube_connection_ok_without_instagram_reach` |
| §3.5 user_hint | **AUTO OK** | `test_account_hints`, Vitest accountHints + modal |
| Staging §3.1 IG session | **FAIL** | см. матрицу (10/10 без sessionid) — не повторялось |

**§3 narrow pytest:** **145 passed** (combined `-k`, см. команды ниже).  
**§3 Vitest:** **14 passed** — `SessionSetupModal` **10** + `accountHints` **4**.

```bash
python -m pytest tests/unit/test_api_routes.py tests/unit/test_api_studio_login.py tests/unit/test_mint_mobile_session.py tests/unit/test_session_manager.py tests/unit/test_session_export.py tests/unit/test_playwright_session.py tests/unit/test_first_login_service.py tests/unit/test_studio_login_service.py tests/unit/test_connection_ladder.py tests/unit/test_connection_test.py tests/unit/test_login_autonomy.py tests/api/test_accounts_first_login.py tests/unit/test_assistant_tools.py tests/unit/test_account_hints.py tests/unit/test_login_tools.py tests/unit/test_assistant_chat_helpers.py -k "session or cookies or mint_mobile or studio or youtube or probe_mobile or instagram_reachable or import_cookies or get_session or first_login or login_autonomy or account_hints or operator_message or merge_operator or orch or challenge or playwright_session or ladder or mint_mobile_session or export_session" -q
cd frontend && npx vitest run src/components/__tests__/SessionSetupModal.test.tsx
cd frontend && npx vitest run src/lib/__tests__/accountHints.test.ts
```

---

## Ревизия чек-листа §2 (2026-11-01)

Сверка §2 «Создание аккаунтов» с API/UI/CLI; правки чек-листа и §9 GAP (CLI `session_id` на Studio).

| Пункт | Статус | Заметка |
| --- | --- | --- |
| 2.1 UI platform cards | **AUTO OK** | Vitest `platform-card-youtube`, IG-only fields |
| 2.2 account_line / vendor_line | **AUTO OK** | `test_vendor_line.py` |
| 2.3 POST **201**, caps/hours | **DOC OK** | upsert → §1.3.3 |
| 2.4 hold_for_review | **AUTO OK** | `test_enqueue_job_hold_for_review_awaits`, `test_publish_now_auto_approves_when_hold_for_review` |
| 2.5 create_account(s) partial | **AUTO OK** | `test_assistant_tools` |
| 2.6 CLI all platforms | **DOC OK** | `test_cli.py` add-account youtube; пароль обязателен в CLI |
| 2.7 upsert duplicate POST | **DOC OK** | cross-ref §1.3.3, `test_factory_merge` same username |
| CLI `--session-id` YT/TT | **GAP** | §9 чек-листа; API 400, CLI без проверки |

**§2 narrow pytest:** **19 passed** (combined `-k`, см. команды ниже).  
**§2 Vitest:** **4 passed** — `-t "add-account"` (3) + `-t "platform card"` (1); на Windows не использовать `\|` в одной shell-строке без кавычек.

```bash
python -m pytest tests/unit/test_vendor_line.py tests/unit/test_cli.py tests/unit/test_factory_merge.py tests/unit/test_api_routes.py tests/unit/test_assistant_tools.py -k "add_account or same_username or hold_for_review or youtube_account_create or create_account or create_accounts or vendor_line" -q
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "add-account"
cd frontend && npx vitest run src/pages/__tests__/Accounts.test.tsx -t "platform card"
```

---

## Ревизия чек-листа §0–§1 (2026-11-01)

Сверка [qa-accounts-publish-checklist.md](qa-accounts-publish-checklist.md) с кодом; правки документации (без смены API прокси).

| Пункт | Статус | Заметка |
| --- | --- | --- |
| §0.1 стек | **OK** | ранее Docker healthy (см. прогон `accounts/`) |
| §0.2 `data/` | **DOC OK** | `./data` → `/app/data` в compose зафиксировано в чек-листе |
| §0.3 preflight | **SKIP** | ручной прогон в worker не повторялся |
| §0.4 worker | **OK** | `reels-worker` up |
| §0.5 роли | **SKIP** | |
| §0.6 VNC | **SKIP** | |
| §0.7 Playwright | **GAP** | Docker: нужен `install-playwright`; Windows: `PLAYWRIGHT_BROWSERS_PATH` |
| §1.1 CRUD | **DOC OK** | POST upsert **200**; delete busy **409**; delete ok **200** |
| §1.2 health/geo | **AUTO OK** | **40** pytest (pool, proxy check, api routes, assistant) |
| §1.3 bind account | **AUTO OK** | покрыто `test_api_routes` accounts+proxy |

---

## Backlog: ревизия §2–§10 (шаблон)

| Раздел | Фокус сверки | Статус | Pytest/Vitest (из §10) |
| --- | --- | --- | --- |
| §2 Создание аккаунтов | platform, account_line/vendor_line, CLI 3 platforms, 201/upsert | **DONE** | §2 narrow **19** pytest + Vitest **4** (см. «Ревизия §2») |
| §3 Сессии | SessionSetupModal, §3.5 user_hint, ladder, REST session/cookies | **DONE** | §3 narrow **145** pytest + Vitest **14** (см. «Ревизия §3») |
| §4 Подключение | test_connection matrix, user_hint, publish gate, UI batch | **DONE** | §4 narrow **44** pytest + Vitest **9** (см. «Ревизия §4») |
| §5 Публикация | worker, review, post_type, enqueue UI/API, publish_now | **DONE** | §5 narrow **111** pytest + Vitest **21** (см. «Ревизия §5») |
| §6–§7 E2E / паритет | E2E partial, чат vs UI, probe_mobile, pause | **DONE** | §6 **21** + §7 **34** pytest; Vitest **8** (см. «Ревизия §6–§7») |
| §8–§9 FAIL / GAP | health cache, VNC workers | **TODO** | документ vs код |
| §10 порядок прогона | команды актуальны | **PARTIAL** | обновлено в чек-листе 2026-11-01 |

---

## Матрица staging (3 platform × proxy / session / publish)

Заполнить на VPS/staging с реальными прокси и тестовыми аккаунтами.

| Блок | Instagram | YouTube | TikTok | Общий статус | Issue / log |
| --- | --- | --- | --- | --- | --- |
| §1 Прокси CRUD + health | **OK** | 6× `am-mobile-*`, см. прогон `accounts/` |
| §2 Создание аккаунта | **OK** | import 23 аккаунта |
| §3.1 IG web sessionid | **FAIL** | 10/10 без сессии; first-login blocked |
| §3.2 IG mobile mint | **SKIP** | нет sessionid |
| §3.3 IG browser/VNC | **SKIP** | не прогонялось |
| §3.4 Studio cookies | **OK** | 10 YT + 3 TT Playwright state |
| §4 test_connection 4.x | **PARTIAL** | 13 OK studio; 10 IG FAIL (session_missing) |
| §5.3 publish queue/review | | | | **SKIP** | unit: `test_worker`, `test_review` OK |
| §5.4 E2E publish (сеть) | | | | **SKIP** | by design вне CI |
| §6 E2E-1 … E2E-7 | | | | **SKIP** | |

### §0 Окружение (ручное)

| # | Статус | Заметка |
| --- | --- | --- |
| 0.1 Стек жив | **OK** | Docker compose healthy |
| 0.2 Общий `data/` | **OK** | host import + контейнеры |
| 0.3 Preflight worker | **SKIP** | |
| 0.4 Воркер включён | **OK** | `reels-worker` up |
| 0.5 Роли owner/operator | **SKIP** | |
| 0.6 VNC | **SKIP** | |
| 0.7 Playwright | **GAP** | install-playwright / `PLAYWRIGHT_BROWSERS_PATH` — см. ревизию §0–§1 |

---

## Соответствие автотестов разделам чек-листа

| Раздел чек-листа | Pytest / Vitest |
| --- | --- |
| §1 прокси | `test_proxies_pool`, `test_api_routes` (`test_proxies_*`), `test_connection_test` (proxy check), `test_assistant_tools` (`create_proxy`, `test_proxy`) |
| §2 аккаунты | `test_vendor_line`, `test_cli` (add-account), `test_factory_merge`, `test_api_routes` (create/hold/youtube), `test_assistant_tools` (create_*), Vitest `Accounts.test.tsx` (platform/add) |
| §3 сессии | `test_api_routes` (session/cookies/mint), `test_api_studio_login`, `test_mint_mobile_session`, `test_session_manager`, `test_session_export`, `test_playwright_session`, `test_first_login_service`, `test_studio_login_service`, `test_connection_ladder`, `test_connection_test` (studio/probe), `test_login_autonomy`, `test_accounts_first_login`, `test_assistant_tools` (import/get_session), `test_account_hints`, `test_login_tools`, `SessionSetupModal.test.tsx`, `accountHints.test.ts` |
| §4 connection | `test_connection_test`, `test_account_hints` (connection), `test_assistant_tools` (publish_now gate, test_connections), Vitest `Accounts.test.tsx` (connection modal, «Проверить все»); `test_account_diagnostics` — optional credential logging |
| §5 publish | `test_worker`, `test_reels_publisher`, `test_review`, `test_api_routes` (jobs), `test_factory_merge` (post_type_for), `test_assistant_tools` (enqueue/publish_now), Vitest `Upload.test.tsx`, `Publishing.test.tsx` |
| §6 E2E partial | `test_factory_merge` (same_username), `test_cli` (rotate/pause), `test_worker` (paused claim, proxy unhealthy), `test_api_routes` (proxies delete, enqueue username), `test_assistant_tools` (attach, publish_now), `test_first_login_service` (attach_proxy) |
| §7 parity | `test_assistant_tools` (create/import/test/publish/mask/pause/diagnose), `test_assistant_chat_helpers` (describe), Vitest `Accounts.test.tsx` (-t connection), `client.test.ts` (-t probe_mobile) |
| UI Accounts | `Accounts.test.tsx`, `SessionSetupModal.test.tsx` |

---

## Обнаруженные расхождения (не staging)

| Тема | Наблюдение | Действие |
| --- | --- | --- |
| Geo mismatch | `health_check_record` возвращает `(ok=True, err=«не совпадает»)` при warn | Тесты `test_proxies_pool` приведены в соответствие; UI фильтр geo-mismatch — §1.2.3 |

При следующем staging-прогоне: скопировать таблицу «Матрица staging», заменить **SKIP** на OK/FAIL, приложить скрины DiagnosticLogPanel и `PostJob` id.
