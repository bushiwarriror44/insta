# Матрица API ↔ тесты (ориентир для QA)

Роутеры из [`app/api/main.py`](../app/api/main.py). Поиск упоминаний в `tests/`: `rg '/api/' tests`.

| Роутер | Префикс / зона | Основные тесты |
| --- | --- | --- |
| health | `/health` | `test_api_routes` |
| panel | панель | `test_panel_settings` |
| auth | логин | `test_api_routes`, `test_operators_api` |
| settings | настройки | `test_panel_settings` |
| operators | операторы | `test_operators_api` |
| dashboard | сводка | `test_api_routes` |
| accounts | аккаунты, first-login | `test_api_routes`, `test_accounts_first_login`, `test_api_studio_login` |
| browser | VNC WS | `test_browser_websocket`, `test_browser_session_manager` |
| proxies | прокси | `test_proxies_pool`, `test_api_routes` |
| videos | загрузка медиа | `test_api_routes` |
| jobs | очередь постов (enqueue, cancel, approve, retry, PATCH) | `test_api_routes` (traversal, hold, approve/retry/reschedule), `test_review`, `test_worker`, `test_assistant_tools` |
| diagnostics | DiagnosticRun | `test_diagnostic_collector`, `test_connection_test`, `test_account_diagnostics` |
| publications | публикации | `test_api_routes`, `test_publications_stats` |
| events | события | `test_api_routes`, `test_api_coverage_smoke` |
| factory | generations, compose, agent (`/plan`, `/preview`, `/week`, sources, questions, agent-runs) | `test_factory_interactive`, `test_factory_merge`, `test_planning_service`, `test_agent_planner`, `test_agent_sources`, `test_clarifications`, `test_generation_*`, `test_composing_service`, `test_media` |
| gpu | Salad Start/Stop, probes | `test_salad_gpu`, `test_salad_prepare`, `test_salad_idle`, `test_gpu_slot`, `test_generation_gpu_slot` |
| admin_notes | заметки | `test_admin_notes` |
| worker | start/stop | `test_worker_api`, `test_worker_control` |
| assistant | chat, run | `test_assistant_tools`, `test_assistant_run`, `test_assistant_stream_cut` |
| screenshots | снимки | `test_screenshots_api`, assistant |
| maintenance | runtime, backups; restore **owner-only** | `test_backup_service`, `test_factory_interactive`, `test_operators_api` (`test_operator_cannot_restore_database_backup`) |

## Frontend ↔ Vitest

Маршруты из [`frontend/src/App.tsx`](../frontend/src/App.tsx). Прогон: `cd frontend && npm test -- --run`.

| Зона / route | Тест |
| --- | --- |
| App shell, auth states, routes | `src/__tests__/App.test.tsx` |
| `/` Dashboard | `pages/__tests__/Dashboard.test.tsx` |
| `/login` | `pages/__tests__/Login.test.tsx` |
| `/accounts` | `pages/__tests__/Accounts.test.tsx` |
| `/publishing`, `/upload` | `Publishing.test.tsx`, `Upload.test.tsx` |
| `/agent` | `pages/__tests__/Agent.test.tsx` |
| `/renders` | `pages/__tests__/Renders.test.tsx` |
| `/calendar` | `pages/__tests__/Calendar.test.tsx` |
| `/activity` | `pages/__tests__/Activity.test.tsx` |
| `/maintenance` | `pages/__tests__/Maintenance.test.tsx` |
| `/administration` | `pages/__tests__/Administration.test.tsx` |
| `/operators`, `/settings` | `Operators.test.tsx`, `Settings.test.tsx` |
| Layout, CommandPalette | `components/__tests__/Layout.test.tsx`, `CommandPalette.test.tsx` |
| Assistant, SessionSetup, IG browser | `Assistant.test.tsx`, `SessionSetupModal.test.tsx`, `InstagramBrowserPanel.test.tsx` |
| Мануалы / hints | `lib/__tests__/agentManual.test.ts` |
| API client | `api/__tests__/client.test.ts`, `assistant.test.ts` |

## CLI ↔ pytest

Точка входа: `python -m app.cli` ([`app/cli.py`](../app/cli.py)). Прогон: `pytest tests/unit/test_cli.py -q`.

| Зона / команда | Тесты в `test_cli.py` |
| --- | --- |
| init-db, import-proxies | `test_init_db`, `test_import_proxies_*`, `test_import_proxies_invalid_json_exits` |
| add-proxy | `test_add_proxy_*` |
| add-account (+ `--platform`) | `test_add_account_*`, `test_add_account_platform_youtube` |
| enqueue-post, plan-week | `test_enqueue_post_*`, `test_plan_week_*` |
| pause/resume, rotate-proxy, provide-code | `test_pause_*`, `test_rotate_*`, `test_provide_code_*` |
| list-accounts, status | `test_list_accounts`, `test_status_*` |
| ask (assistant run) | `test_ask_invokes_assistant_with_browser` |
| preflight | `test_preflight_*` |
| run-worker, install-playwright, first-login | `test_run_worker_*`, `test_install_playwright_*`, `test_first_login_*` |
| export-account, refresh-app-versions | `test_export_account_*`, `test_refresh_app_versions` |

## Security ↔ тесты

| Зона | Тесты |
| --- | --- |
| Auth / operators / owner routes | `test_operators_api`, `test_api_routes`, `test_panel_settings` |
| Browser secrets + VNC WS | `test_auth_browser_secrets`, `test_browser_websocket`, `test_browser_session_manager` |
| Assistant RBAC (`allow_browser`, masks) | `test_assistant_run`, `test_assistant_tools` |
| Path traversal (media, jobs, generation) | `test_media`, `test_api_routes`, `test_generation_security`, `test_factory_interactive` |
| Backup restore RBAC + names | `test_backup_service`, `test_operators_api`, `test_factory_interactive` |
| Project file sandbox | `test_assistant_tools` |
| Signed screenshots | `test_screenshots_api` |
| Docker logs whitelist | `test_assistant_tools` |

## Regression ↔ pytest (§14)

Сквозные сценарии после опасного diff. Полный чеклист — [qa-checklist.md §14](qa-checklist.md#14-регрессии-фокус-diff).

| Сценарий | pytest |
| --- | --- |
| Login autonomy (VNC gate, ensure, challenge) | `test_login_autonomy.py`, `test_session_manager.py`, `test_login_tools.py`, `test_first_login_service.py`, `test_studio_login_service.py`, `test_api_studio_login.py`, `test_assistant_run.py` |
| Login orch frozenset + tool catalog | `test_regression_focus.py` |
| Slideshow worker → `slideshow` backend | `test_generation_service.py` (`test_run_generation_job_slideshow_resolves_slideshow_backend`) |
| Multimodal enqueue / chain / security | `test_generation_inputs.py`, `test_fal_backend.py`, `test_chain.py`, `test_generation_security.py`, `test_factory_interactive.py`, `test_assistant_tools.py` |
| Docs ↔ generation / handbook / costs | `test_docs_generation_regression.py`, `test_assistant_handbook.py` |

Фокус-команда:

`pytest tests/unit/test_login_autonomy.py tests/unit/test_session_manager.py tests/unit/test_generation_service.py tests/unit/test_chain.py tests/unit/test_docs_generation_regression.py tests/unit/test_regression_focus.py -q`

## Release ↔ pytest (§15)

Финальный gate — [qa-checklist.md §15](qa-checklist.md#15-релиз).

| Зона | pytest / команда |
| --- | --- |
| Полный backend / frontend | `pytest tests/ -q`; `cd frontend && npm test -- --run` |
| Compose layout + shared `data/` | `test_release_readiness.py` |
| CLI library enqueue + preflight | `test_cli.py` |
| Handbook release bundle | `test_release_readiness.py`, `test_assistant_handbook.py` |
| Регрессии перед релизом | §14 фокус-команда + полный pytest |

**Ручной GAP (не в CI):** IG/Studio login, реальный fal/local render, publish smoke с `hold_for_review`; docker health curl (§0).

## Пробелы (GAP) — приоритет ручной проверки

- `maintenance` — restore в UI нет (API restore только owner; take backup — operator ok)
- E2E Playwright publishers на реальных площадках (только unit/mocks)
- Multimodal render на реальном fal/local (только unit + API mock)

Обновлять матрицу после добавления роутов: `rg "include_router" app/api/main.py`.
