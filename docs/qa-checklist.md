# Чек-лист глубокой проверки приложения

Метод: для каждого блока — **(A)** тесты, **(B)** ручной smoke UI/API, **(C)** аудит кода. Статус: OK / FAIL / GAP.

Связанные документы: [overview.md](overview.md), [assistant-handbook.md](assistant-handbook.md), [accounts-sessions.md](accounts-sessions.md), [generation.md](generation.md), [costs.md](costs.md), [qa-api-coverage.md](qa-api-coverage.md).

## Последний автоматический прогон (2026-09-30)

| Проверка | Статус |
| --- | --- |
| `python -m pytest tests/ -q` | **OK** — 951 passed |
| `cd frontend && npm test -- --run` | **OK** — 396 passed |
| Path traversal на reference | **OK** — `tests/unit/test_generation_security.py` |
| `generation.md` multimodal | **OK** — синхронизирован с кодом |
| API матрица | **OK** — `test_api_coverage_smoke.py` (health, events, maintenance, docker whitelist) |
| SQLite WAL + busy_timeout | **OK** — `app/db/session.py`, `test_sqlite_pragmas.py` |
| UNIQUE (platform, username) | **OK** — `init_db` + index test |

## 0. Подготовка

- [ ] `.env` по `.env.example` — **ручной** (см. `AGENT_BASE_URL`: не копировать пустое `=` для локального Ollama)
- [x] `python -m pytest tests/ -q`
- [x] `cd frontend && npm test -- --run`
- [x] SQLite: `_PENDING_COLUMNS`, WAL, `uq_account_platform_username` — `test_db_models`, `test_sqlite_pragmas`
- [x] `SessionLocal` через `app.db` в `deps` / WS auth — не захваченный импорт
- [ ] Docker smoke — **ручной**: `docker compose up -d`, `curl http://127.0.0.1:8000/api/health`, `wget -qO- http://127.0.0.1:3000/healthz`
- [ ] Общий том `./data`: api + worker на одном `app.db` (WAL снижает `database is locked`; тройной `init_db` entrypoint+lifespan+worker идемпотентен)

## 1. Auth и операторы

- [x] Логин, 401, роли — `test_api_routes`, `test_operators_api`, `/api/auth/me`
- [x] Operators/settings только owner — `OwnerDep`; open mode: settings 403 без auth (`require_owner`)
- [x] `POST /api/assistant/run`: `allow_browser` только owner — `test_assistant_run` (operator → False)
- [x] Stream: `allow_browser` только owner + флаг UI — `assistant.py` talk_streaming
- [x] Browser API: `account_password` / `account_login` только owner — `test_auth_browser_secrets.py`
- [x] Tools: `list_operators` без entry_path для operator; `mask_account_secrets` на account_details/list_accounts — `test_assistant_tools`
- [x] `account_logs`: редакция Пароль / session_id / email_password в строках — `_redact_diag_message`
- [x] Нет tools на запись settings/env — `test_tool_specs_have_create_but_no_settings_writes`
- [ ] Полный audit `Event.message` в worker — **ручной** spot-check

## 2. Прокси

- [x] Pool MINIMAL/FULL, geo, IG probes — `test_proxies_pool`
- [x] REST CRUD, delete 409, `geo_mismatch_warning` — `test_api_routes`
- [x] Connection test + API `geo_mismatch` — `test_connection_test`
- [x] Worker/browser/login без `proxy_id` — `test_worker`, `first_login_service`, tools
- [x] `ensure_account_session` читает `test_connection.ok` — `test_login_autonomy`
- [x] Tools: `list_proxies` geo + mask URL operator; `create_proxy` health — `test_assistant_tools`
- [ ] `_HEALTH_CACHE` in-process (API vs worker) — **known limitation**, как VNC multi-worker

## 3. Аккаунты и сессии

- [x] IG challenge payload — `test_login_autonomy`, `test_first_login_service`
- [x] Studio VNC / gates — `test_studio_login_service`, `test_api_studio_login`, `LOGIN_ORCH_BROWSER_TOOLS`
- [x] REST `session_id` только Instagram (PUT/POST) — `test_api_studio_login` (не стирает playwright YT)
- [x] `ensure_account_session` + VNC busy + `test_connection.ok` — `test_login_autonomy`
- [x] `get_session` soft `ready: false`; operator без полного sessionid — `test_assistant_tools`
- [x] Tools mask: `import_cookies`, `mint_mobile_session`, `save_browser_session` — `mask_session_tool_payload`
- [x] Handbook vs VNC при `login_account` — handbook + `agentManual.ts` (Assistant test)
- [ ] REST `GET .../session` — только IG sessionid (Studio → 404); UI SessionSetupModal — **документировано**

## 4. Нижний чат

- [x] UI `TOOLS` без browser/wait; run — `tool_specs(allow_browser=True)` — `test_assistant_run`
- [x] `/run` и `/stream`: `allow_browser` только owner — `test_run_endpoint_*`, `test_stream_*`
- [x] `run_tool`: browser только run; LOGIN_ORCH `browser_status` в stream — `test_run_tool_*`
- [x] Stream ask/created/tool steps — `test_stream_emits_ask_and_stops`, `test_assistant_stream_cut`
- [x] `create_render` + reference sanitize via `run_tool` — `test_assistant_tools`, `test_generation_security`
- [x] GPU busy → чат retryable — `test_gpu_slot`
- [x] Sync `POST /api/assistant` без `allow_browser` (UI только stream) — by design

## 5. Генерация

- [x] T2V / I2V / V2V / slideshow — `test_generation_inputs`, `test_fal_backend`, `test_chain`
- [x] `image_slideshow` → backend `slideshow` (API + `create_render`, даже если запросили `fal`) — `test_factory_interactive`, `test_assistant_tools`
- [x] Enqueue: healthcheck на **фактическом** backend после coerce; референс на диске — на воркере (`resolve`), не при POST — by design
- [x] Референс: library `filename` sanitize + traversal — `test_generation_security`, `test_api_generations_reference_filename_sanitized`, `test_run_tool_create_render_sanitizes_reference_filename`
- [x] V2V trim ≤15 с — `test_generation_service` (`ensure_video_reference`)
- [x] Воркер: resolve fail / unsupported backend / budget defer без `attempts` / success → `MediaAsset` — `test_generation_service`
- [x] Chain `auto` → фактический `job.backend` — `test_chain`
- [x] API: backends, cancel (только `queued`), retry (health) — `test_factory_interactive`
- [x] Compose API: минимум 2 клипа — `CompositionIn` + `test_composition_requires_two_clips`; чат `compose` — `test_assistant_tools`
- [x] Plan → `GenerationJob` — `test_factory_merge`
- [x] GPU: `local` + `gpu_slot`, чат `video_busy` — `test_gpu_slot`, блок 4
- [x] Оператор может ставить fal-рендеры (AuthDep) — by design; бюджет — `refuses` в `run_generation_job`

## 6. Библиотека и склейка

- [x] Две библиотеки: upload-лист → `video_source_dir` (`POST /api/videos`); каталог `MediaAsset` → `media_dir` (рендер/склейка) — by design; `save_upload` не в HTTP
- [x] Upload/list/archive/GET traversal — `test_api_routes`
- [x] `asset_media_path`: removed / missing / resolve — `test_media.py`
- [x] Склейка: API+чат ≥2 клипа; воркер ≥2 — `test_composition_requires_two_clips`, `test_composing_service`
- [x] `run_composition` → `MediaAsset` composed — `test_composing_service`
- [x] API compositions cancel/retry; reject removed clip — `test_factory_interactive`
- [x] Чат `compose` reject removed asset — `test_assistant_tools`
- [x] ffmpeg filter graph — `test_compose.py` (не воркер)

## 7. Публикация (PostJob, worker, jobs API, чат)

- [x] `POST /api/jobs` + `enqueue_publish`: `filename` через `_resolve_source_file` (traversal → 404) — `test_api_routes`, `test_assistant_tools`
- [x] `asset_id` publish → `media_dir` (`asset_media_path`) — блок 6 + `enqueue_publish`
- [x] `hold_for_review` → `awaiting_review`; API approve/retry/reschedule — `test_review`, `test_api_routes`
- [x] `publish_now`: `test_connection.ok`; auto-`approve_job` при hold — `test_assistant_tools`
- [x] Worker: `_claim_due_job` только `queued` (не `awaiting_review`/pause/cooldown) — `test_worker`
- [x] `_process_job`: IG/YT/TikTok/feed, cap, proxy, backoff — `test_worker`, `test_reels_publisher`, `test_studio_playwright`
- [x] Planner/agent → те же PostJob — `test_planner`, `test_factory_merge`
- [x] Очередь worker: plan → generation → composition → publish — `worker.py` (один job за тик)
- [x] Operators: полный доступ к jobs/publish — by design

## 8. Контент-агент (PlanJob, planning)

- [x] Промпт/схема идеи — `test_agent_planner`
- [x] `plan_for_channel` → `GenerationJob` — `test_factory_merge`, `test_planning_service`
- [x] `run_plan_job` (done, retryable fail, dead) — `test_planning_service`
- [x] `gather_sources`: битый источник → `last_status`, план не падает — `test_planning_service`
- [x] `queue_ideas`: multi-shot `post_group`, unknown soundtrack → Event — `test_planning_service`
- [x] Budget gate / `blocked` до плана — `test_planning_service`
- [x] `week` / `spread_over_days` → `days_ahead_for_plan` при publish — `test_planning_service`, `test_factory_interactive`
- [x] API `/plan`, `/preview`, `/week` — `test_api_routes`, `test_factory_interactive`
- [x] Preview: реальные jobs, `auto_schedule=false` (рендер воркером всё равно) — `test_factory_interactive`, `test_assistant_tools`; см. `docs/generation.md`
- [x] Чат: `plan_account`, `preview_plan`; `wait_plan` только run — `test_assistant_tools`, `test_assistant_run`
- [x] Источники URL/file (allowlist, private IP, traversal) — `test_agent_sources`
- [x] Clarifications: open gate, `settled` в промпте — `test_clarifications`
- [x] AgentRun через `run_agent` — косвенно merge/preview tests
- [x] Worker order: plan → generation → composition → publish — `worker.py`, блок 7
- [x] UI `/agent` — `Agent.test.tsx`
- [x] **GAP:** `replan_post` / `posts_in_a_week` не в API/UI (только `planning.py`)

## 9. GPU (Salad, gpu_slot, local Wan)

- [x] `gpu_slot.lock`: stale снимается; второй `hold_for_video` → retryable `GenerationError` — `test_gpu_slot`
- [x] `video_busy` блокирует `_prepare_runtime` (чат retryable) — `test_gpu_slot`, блок 4
- [x] `local`: `unload_loaded` под lock, POST `WAN_BASE_URL` — `test_gpu_slot`
- [x] `run_generation_job` + занятый lock → re-queue, `attempts` — `test_generation_gpu_slot`
- [x] `GET/POST /api/gpu` (owner), probes `chat_ok`/`wan_ok`, stopped → false, без утечки секретов — `test_salad_gpu`
- [x] `prepare_for_chat` (старт, pull, warm) — `test_salad_prepare`
- [x] Idle-stop: anchor, lock, queued `local`/`auto`+WAN+`local` в chain — `test_salad_idle`
- [x] Чат: `salad_configured` → `prepare_for_chat` перед runtime; `touch` на completion — `chat.py` + prepare tests
- [x] UI: `SaladGpuCard`, Connection menu — `SaladGpuCard.test.tsx`, `Administration.test.tsx`
- [x] Chain `auto` может уйти в fal без lock — `test_chain` (блок 5)
- [x] **GAP:** `gpu_slot.lock` и `data/` должны быть общими для API и worker; иначе координации VRAM нет (как VNC in-memory, §12)

## 10. Диагностика и backup

- [x] `DiagnosticCollector`: lines, finish, login fail → Event — `test_diagnostic_collector`
- [x] Account credential logging / proxy endpoint — `test_account_diagnostics`
- [x] Connection test → `GET /api/diagnostic-runs` list/get — `test_connection_test`
- [x] Invalid `kind` filter → 400 — `test_connection_test`
- [x] UI log panel — `DiagnosticLogPanel.test.tsx`; Activity/Accounts wiring
- [x] Чат `diagnose`: worker heartbeat, posting/login/proxy, Ollama, errors, backends, app.log tail — `test_assistant_tools`
- [x] Чат `docker_logs`: whitelist compose, engine fallback — `test_assistant_tools`, `test_api_coverage_smoke`
- [x] Maintenance: `GET /runtime`, context POST — `test_runtime`, `test_api_coverage_smoke`, `Maintenance.test.tsx`
- [x] Backup: `take` / `prune` / `list` / `restore` + `resolve_backup` (только `app-*.db`) — `test_backup_service`
- [x] API `POST/GET /api/maintenance/backups`, `POST .../restore` — `test_factory_interactive`; чат `take_backup` — `test_assistant_tools`
- [x] **GAP:** restore в UI и чате нет; после API restore — перезапуск API/worker вручную (live DB перезаписывается)
- [x] **GAP:** `diagnose` не включает Salad/GPU card (§9); publish `DiagnosticCollector` в worker — без отдельного E2E

## 11. Frontend parity (UI ↔ API / handbook)

- [x] Роуты [`App.tsx`](../frontend/src/App.tsx): index, accounts, publishing, `/upload`→publishing, agent, renders, calendar, activity, maintenance, administration, operators, settings — `App.test.tsx`
- [x] Страницы Vitest: Dashboard, Login, Accounts, Publishing, Upload (redirect), Agent, Renders, Calendar, Activity, Maintenance, Administration, Operators, Settings — `frontend/src/pages/__tests__/*`
- [x] Навигация и роли: бейджи review/questions — `Layout.test.tsx`; owner-only Настройки/Доступы/Администрирование в палитре — `CommandPalette.test.tsx`; operator → home с `/administration` — `Administration.test.tsx`
- [x] Встроенные мануалы: `AGENT_PAGE_MANUAL` / `CHAT_MANUAL` / `pageHint` / `toolHint` — `agentManual.test.ts`; превью без PlanJob, вопросы не блокируют план — паритет с [`generation.md`](generation.md), [`clarifications.py`](../app/services/clarifications.py)
- [x] Agent UI: plan/week/preview/sources/questions — `Agent.test.tsx`; toast превью без календаря
- [x] Чат dock: stream, tools, мануал — `Assistant.test.tsx`; API assistant — `api/__tests__/assistant.test.ts`
- [x] Аккаунты / сессия / VNC panel — `Accounts.test.tsx`, `SessionSetupModal.test.tsx`, `InstagramBrowserPanel.test.tsx`
- [x] Публикация / рендеры / GPU card — `Publishing.test.tsx`, `Renders.test.tsx`, `SaladGpuCard.test.tsx`
- [x] HTTP client paths — `api/__tests__/client.test.ts`
- [x] **GAP:** restore копии БД только `POST /api/maintenance/backups/restore` (UI «Снять копию» есть, restore нет; см. §10)
- [x] **GAP:** handbook «Только в UI» — drag календаря, Ctrl+K, загрузка dropzone, произвольный `start_browser` из чата; чат ≠ все кнопки
- [x] **GAP:** `replan_post` / `posts_in_a_week` — нет UI (§8)

## 12. Security

- [x] RBAC: owner vs operator — см. **§1** (`OwnerDep` operators/settings/gpu docs; `AuthDep` остальное)
- [x] Restore БД: `POST /api/maintenance/backups/restore` — **только owner** (`DocsOwnerDep`; open mode ok); list/take — operator ok — `test_operator_cannot_restore_database_backup`, `test_factory_interactive`
- [x] Backup имена: `resolve_backup` (`app-*.db`, без traversal) — `test_backup_service`, `test_factory_interactive`
- [x] Media library: `storage_name` + `media.resolve` / `asset_media_path` — `test_media`
- [x] Upload / enqueue: `_safe_name`, `_resolve_source_file` — `test_api_routes` (`test_enqueue_job_rejects_path_traversal`, upload)
- [x] Generation refs: `resolve_generation_inputs` + `asset_media_path` + library `resolve` — `test_generation_security`, `test_generation_inputs`
- [x] API generations `reference_filename` sanitize — `test_factory_interactive`
- [x] Project files (чат): `_inside_project` — `test_assistant_tools` (`read_project_file`)
- [x] Docker logs whitelist — `test_assistant_tools` (`docker_logs`)
- [x] Screenshots: HMAC `verify` + `media.resolve` — `test_screenshots_api`
- [x] Browser API: пароль/login только owner; operator VNC через UI API — `test_auth_browser_secrets`
- [x] VNC WebSocket: `verify_ws_token`, активная сессия — `test_browser_websocket`, `test_browser_session_manager`
- [x] Assistant: `allow_browser` / `start_browser` в чате только owner; `POST /api/assistant/run` — `test_assistant_run` (§1)
- [x] **GAP (deployment):** open mode без токена = synthetic owner (§1)
- [x] **GAP:** `BrowserSessionManager` in-memory — несколько uvicorn workers не шарят VNC (§1, §11)
- [x] **GAP:** `gpu_slot.lock` + общий `data/` для API и worker (§9)
- [x] **GAP:** restore в UI нет (§10/§11); `browser/start` для operator by design (секреты скрыты)

## 13. CLI ([`app/cli.py`](../app/cli.py))

- [x] Bootstrap: `_bootstrap` → `init_db` + logging; общая SQLite с API/worker — `test_init_db`
- [x] DB: `init-db` — `test_init_db`
- [x] Прокси: `add-proxy` (health / skip), `import-proxies` JSON — `test_add_proxy_*`, `test_import_proxies_*`, `test_import_proxies_invalid_json_exits`
- [x] Аккаунты: `add-account` (proxy, timezone, update, `--platform` instagram/youtube/tiktok) — `test_add_account_*`, `test_add_account_platform_youtube`
- [x] Очередь: `enqueue-post` (hold_for_review, `--when`), `plan-week` — `test_enqueue_post_*`, `test_plan_week_*`
- [x] Worker/API: `run-worker`, `install-playwright` — `test_run_worker_*`, `test_install_playwright_*`; `run-api` — **ручной** / setup
- [x] `preflight`: `playwright_browsers_available` (не только `/ms-playwright`) — `test_preflight_*`
- [x] Assistant: `ask` = `POST /api/assistant/run` (`allow_browser`, `viewer_role=owner`) — `test_ask_invokes_assistant_with_browser`; см. [`test_assistant_run.py`](../tests/unit/test_assistant_run.py)
- [x] Ops: `first-login`, `provide-code`, pause/resume, `rotate-proxy`, `list-accounts`, `status`, `export-account`, `refresh-app-versions` — соответствующие тесты в `test_cli.py`
- [x] `status`: entry_path скрыт по умолчанию, `--show-entry-path` — `test_status_hides_entry_path_by_default`, `test_status_show_entry_path_flag`
- [x] `browser-vnc-diag` — **ручной** на VPS (curl/wscat hints)
- [x] Документация команд: docstring в `cli.py`, [`docs/setup.md`](setup.md), handbook `cli ask`
- [x] **GAP:** CLI без Bearer/RBAC — shell на хосте = полный доступ к БД + `ask` с browser tools (§12 deployment)
- [x] **GAP:** `enqueue-post --video` — любой путь на диске, не library validation как API
- [x] **GAP:** нет CLI для maintenance restore / backup (только API §10)

## 14. Регрессии (фокус diff)

Сквозные сценарии, которые ломались при рефакторинге. Не дублирует полный аудит §3/§5 — только якоря и команда после «опасного» diff.

### Login autonomy

| Файл pytest | Инвариант |
| --- | --- |
| `test_login_autonomy.py` | VNC busy gate, `ensure_account_session`, challenge payload, `test_connection` |
| `test_session_manager.py` | при валидной сессии instagrapi **не** вызывает `login()` |
| `test_login_tools.py` | вспомогательные login tools |
| `test_first_login_service.py`, `test_studio_login_service.py`, `test_api_studio_login.py` | studio / REST session |
| `test_assistant_run.py` | browser tools только в run, не в chat-only |
| `test_regression_focus.py` | якорь `LOGIN_ORCH_BROWSER_TOOLS`; VNC-часть ⊆ `BROWSER_TOOL_NAMES`; `preview_plan` в `tool_specs` |

### Multimodal render

| Файл pytest | Инвариант |
| --- | --- |
| `test_generation_service.py` | `test_run_generation_job_slideshow_resolves_slideshow_backend` — worker всегда `get_backend("slideshow")`, даже при инъекции `backend=fal` |
| `test_generation_inputs.py`, `test_fal_backend.py`, `test_chain.py` | coerce режимов, chain skip unsupported |
| `test_generation_security.py` | path traversal reference |
| `test_factory_interactive.py`, `test_assistant_tools.py` | enqueue slideshow / `create_render` |
| `test_generation_gpu_slot.py` | GPU slot (не-slideshow jobs с явным `backend=` без изменений) |

GAP: нет e2e IG publish в CI (см. §15 smoke).

### Docs ↔ код

| Файл pytest | Документ |
| --- | --- |
| `test_docs_generation_regression.py` | `generation.md` (preview без PlanJob, slideshow backend, `video_source_dir`) |
| `test_docs_generation_regression.py`, `test_assistant_handbook.py` | `assistant-handbook.md` (`preview_plan`, `GenerationJob`, `auto_schedule=false`) |
| `test_docs_generation_regression.py` | `costs.md` ↔ `app/generation/fal.py` Wan 2.5 `0.05` |

**Рекомендация после diff** (login + render + docs):

```bash
python -m pytest tests/unit/test_login_autonomy.py tests/unit/test_session_manager.py tests/unit/test_generation_service.py tests/unit/test_chain.py tests/unit/test_docs_generation_regression.py tests/unit/test_regression_focus.py -q
```

Полный прогон: `python -m pytest tests/ -q` и `cd frontend && npm test -- --run`.

- [x] Login autonomy — таблица выше
- [x] Multimodal render — worker slideshow routing + тест
- [x] Docs generation / handbook / costs — doc-guard тесты

## 15. Релиз

Финальный gate перед выкладкой: автоматика + операции + ручной smoke. Регрессии по diff — §14.

### Автоматический gate

| Проверка | pytest / vitest |
| --- | --- |
| Полный backend | `python -m pytest tests/ -q` |
| Frontend | `cd frontend && npm test -- --run` |
| API матрица | `test_api_coverage_smoke.py` |
| Handbook + system prompt | `test_assistant_handbook.py` |
| Docs generation / costs | `test_docs_generation_regression.py` |
| Регрессии §14 | `test_regression_focus.py`, фокус-команда в §14 |
| Compose + release semantics | `test_release_readiness.py` |
| CLI enqueue library + preflight | `test_cli.py` (`enqueue-post`, `preflight` ffmpeg) |

- [x] pytest + vitest green (см. шапку чеклиста)
- [x] `enqueue-post` только под `video_source_dir` — `resolve_library_media_path` в `app/services/media.py`
- [x] `preflight` проверяет ffmpeg (slideshow / uniquify)

### Операционный gate

- [ ] Docker smoke — **ручной** (§0): `docker compose up -d --build`, `curl http://127.0.0.1:8000/api/health`, `wget -qO- http://127.0.0.1:3000/healthz`
- [ ] Общий том `./data` у `reels-api` и `reels-worker` — якорь `test_release_readiness.py`
- [ ] `docker compose exec reels-worker python -m app.cli preflight` (Playwright, прокси, ffmpeg)

### Ручной smoke (прокси / ключи / staging)

| Сценарий | Что сделать |
| --- | --- |
| Instagram | `ensure_account_session` или first-login; `test_connection` ok — без `PostJob` |
| Studio YT/TT | `studio_login` / UI «Браузер»; cookies в `test_connection` |
| T2V | `create_render` (staging `FAL_API_KEY` или local `WAN_BASE_URL`); `wait_render` |
| Slideshow | `image_slideshow` + ref в `video_source_dir`; worker + ffmpeg |
| Publish без выхода в сеть | `hold_for_review` на аккаунте → enqueue / API → статус `awaiting_review` (worker не берёт job); **не** `publish_now` (он auto-approve). Отмена `cancel` или approve только на staging |

`preview_plan` / «Превью» — **не** dry-run: реальные `GenerationJob` и рендер воркером ([`generation.md`](generation.md)).

- [ ] Smoke: 1 IG + 1 Studio path, 1 T2V + 1 slideshow, publish с `hold_for_review` — **ручной**

### Handbook / UI (release bundle)

- [x] login + render + costs — §14 doc-guards
- [x] `hold_for_review`, `preview_plan` + воркер для рендера — `test_release_readiness.py`, `agentManual.test.ts`

### Rollup GAP (не блокируют локальный gate)

| Тема | Где |
| --- | --- |
| Open mode без токена | §1 |
| VNC in-memory multi-worker | §1, §12 |
| `gpu_slot.lock` + общий `data/` | §9 |
| Restore backup только API | §10, §11 |
| CLI shell = full access; нет CLI backup/restore | §13 |
| Нет `.github` CI | только локальный прогон |
| E2E publish на площадках | этот §15 smoke |

### Известные ограничения (документировать при инцидентах)

| Ограничение | Якорь pytest |
| --- | --- |
| Multi-worker VNC in-memory | `test_browser_session_manager` |
| `gpu_slot.lock` + shared `data/` | `test_generation_gpu_slot`, `test_gpu_slot` |
| Local Wan binary contract | `test_generation_*`, `docker/salad-gpu` |
| fal V2V `FAL_MODEL_V2V` | `test_fal_backend` |
| maintenance / events — узкие тесты | `test_api_coverage_smoke`, `test_backup_service` |

- [x] Известные ограничения зафиксированы в таблице выше

Полная версия с таблицами — в плане Cursor `app_qa_checklist` (не редактировать из репозитория).
