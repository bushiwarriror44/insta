# Нижний чат и автономный run

Два входа в одну Ollama (`AGENT_BASE_URL`, модель `AGENT_MODEL`). Tools пишут в ту же SQLite, что кнопки панели. Справочник модели — сжатый [`assistant-handbook.md`](assistant-handbook.md); этот файл — для оператора.

## Три точки входа

| Вход | Тело | Раунды | Browser-tools |
| --- | --- | --- | --- |
| Нижний чат UI | `POST /api/assistant` и `POST /api/assistant/stream` | 6 (`ROUNDS`) | нет |
| Автономный HTTP | `POST /api/assistant/run` | 12 (`RUN_ROUNDS`) | да |
| CLI | `python -m app.cli ask "…"` | 12 | да |

Чат UI шлёт `messages` (история), плюс по желанию `page`, `account_id`, `job_id`. Stream — тот же контракт, события SSE. В доке кнопка «Мануал» и подсказка текущего экрана; во время tool-стрима — одно предложение про шаг. SSE `type=tool` несёт `name`.

Run шлёт **один** `prompt`, без истории. Страницы панели `open_page` не обязан открывать. Живой Playwright можно стартовать.

Нужны живой API и Ollama. Если баннер «Агент остановлен» — воркер мёртв; чат может поставить задачу, но рендер / склейка / публикация из очереди не поедут, пока воркер не запущен.

## Пример промпта (run / `cli ask`)

Один текст, без секретов в логах:

```text
Создай прокси label=res-de-1 url=http://USER:PASS@HOST:PORT страна DE TZ Europe/Berlin.
Создай аккаунт instagram @alice на этом прокси, пароль из карточки уже будет.
Сделай first_login (desktop). Поставь рендер: «туман над лесом», 5 секунд,
дождись готовности, опубликуй ролик сейчас на этот аккаунт.
```

Для YouTube/TikTok **не** пишите «войди паролем Google». Сценарий Studio: прокси + аккаунт `platform=youtube` или `tiktok` → импорт cookies **или** `start_browser` → руками войти в Studio → `save_browser_session` → `publish_now` с файлом из библиотеки.

Instagram: `first_login` / `mint_mobile_session` работают с паролем (+ TOTP). YouTube и TikTok — cookies Playwright в `data/playwright/<user>/state.json`, не instagrapi.

После `create_render` в run обязателен `wait_render`, иначе `publish_now` увидит ещё не готовый файл.

## Что чат не делает

Удаления; создать/отозвать оператора; секретный путь и мастер-пароль; поле «Контекст» Ollama; drag слотов календаря; DropZone / «Скачать ZIP». Restore бэкапа нет в чате. Живой браузер из **нижнего** чата не стартует (`start_browser` только в run).

Нет username / `proxy_label` / url прокси / какой ролик / JSON cookies / промпта рендера / id клипов — модель должна `ask_operator`, не выдумывать.

## Tools: UI-чат vs run

Все строки ниже есть в нижнем чате, кроме помеченных «только run».

### Смотреть

| Tool | Назначение |
| --- | --- |
| `overview` | сводка: аккаунты, клипы, публикации, рендеры |
| `list_accounts` / `account_details` | список / карточка (включая секреты карточки) |
| `list_posts` / `list_clips` / `list_renders` / `list_compositions` / `list_proxies` | очереди и библиотека |
| `list_render_backends` | какие движки рендера живы (`auto` / fal / …) |
| `list_errors` | свежие ошибки |
| `job_logs` | логи публикации + открыть на Активности |
| `list_operators` | как устроены доступы (не создать/отозвать) |
| `list_project_files` / `read_project_file` | файлы **внутри** репозитория и `data/` |
| `get_session` | Instagram: sessionid; Studio: есть ли state.json и имена cookies |
| `page_guide` | секция handbook другой страницы |
| `diagnose` | воркер, блоки posting / login / proxies, Ollama, движки рендера, ошибки БД, хвост `data/app.log` |
| `docker_logs` | только `reels-api` / `reels-worker` / `reels-ollama` / `reels-frontend` / `reels-ollama-pull` |

### Открыть в UI (чат панели)

`open_page`, `open_clip`, `open_post`, `open_account`. `screenshot_page` — снимок в `data/screenshots`, только если попросили. В run открывать страницы не обязательно.

### Аккаунты и прокси

`create_account` / `create_accounts` (до 20): нужны `username` и существующий `proxy_label`; Instagram обычно ещё пароль. `update_account` (лимиты, `hold_for_review`, `login_surface`, `session_id` только Instagram). `pause_account` / `resume_account`. `create_proxy` / `create_proxies` / `update_proxy` / `attach_proxy`. Удаления нет.

### Сессия

`export_cookies` / `import_cookies`, `export_fingerprint` / `import_fingerprint` (только Instagram), `export_playwright_state`. `first_login` и `mint_mobile_session` — только Instagram. `test_proxy` / `test_proxies`, `test_connection` / `test_connections` (`probe_mobile` — Instagram, может сжечь web-cookie).

### Публикация, план, рендер

`enqueue_publish`, `publish_now`, `approve_job`, `retry_job`, `cancel_job` (нужен confirm), `reschedule_job`. `plan_account` / `preview_plan`. `add_source` / `check_source` / `answer_question`. `create_render`, `retry_render`, `cancel_render` (confirm). `compose` (минимум два `clip_ids`), `retry_composition`, `cancel_composition`. `refresh_stats` по `publication_id`. `start_worker`; `stop_worker` после confirm. `take_backup`. `ask_operator`.

### Только run / `cli ask`

| Tool | Назначение |
| --- | --- |
| `start_browser` | живой Playwright + VNC (IG / YouTube Studio / TikTok Studio). Нужны аккаунт и прокси, `BROWSER_VNC_ENABLED` |
| `browser_status` | сеанс жив или нет |
| `save_browser_session` | cookies → `state.json` (Instagram ещё sessionid) |
| `submit_browser_code` | код 2FA в живой браузер |
| `wait_render` | ждать fal `done`/`failed` после `create_render` |

Из UI те же действия — кнопки «Браузер» / «Сохранить» / код 2FA, не нижний чат.

## Ответ модели

В JSON: `reply`, `used` (какие tools), `asks` (вопросы оператору), `open_url` / `opened`, `images`, `created.accounts` / `created.proxies`. Частичный успех `create_accounts` / `create_proxies`: поля `created` и `failed` — не все строки обязаны пройти.

Дальше: [cli.md](cli.md), [api.md](api.md).
