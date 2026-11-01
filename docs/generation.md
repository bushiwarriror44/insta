# Рендер, склейка и контент-план

## Бэкенды видео

Очередь рендера вызывает [`VideoBackend`](../app/generation/base.py). Имя в задаче: `fal`, `huggingface`, `pollinations`, `local`, `hfspace` или **`auto`**.

По умолчанию `VIDEO_BACKEND=auto`: воркер идёт по `VIDEO_BACKEND_CHAIN` (fal → huggingface → pollinations → local → hfspace). Retryable ошибка или сеть — следующий движок. Не-retryable (плохой промпт) — стоп. Успех пишет в `job.backend` фактическое имя, не `auto`. Если все упали — одна ошибка со списком причин, цитировать как есть.

При заданном `WAN_BASE_URL` и `LOCAL_RENDER_REQUIRES_CONFIRM=true` (по умолчанию) цепочка **не вызывает** `local` сама: в `last_error` будет маркер `LOCAL_SWITCH_OFFER:` — в чате и на `/renders` модалка «Переключай» ставит retry с `backend=local` **только** если этот маркер есть (и Wan доступен). Явный `backend=local` / `generate_wan` — без подтверждения. После `create_render` чат сам вызывает `wait_render`, если модель не сделала это в том же ответе.

| Имя | Что нужно | Стоимость в `cost_usd` |
| --- | --- | --- |
| `fal` | `FAL_API_KEY`, модель Wan 2.5 5 или 10 с | прайс fal за секунду (`0.05` USD/с Wan 2.5 в коде) |
| `huggingface` | свой `HF_TOKEN`, `HF_VIDEO_MODEL` | 0 |
| `pollinations` | `POLLINATIONS_VIDEO_URL`; при 401/403 — проверьте `POLLINATIONS_API_KEY` (неверный ключ хуже пустого). В `auto` отказ по ключу **retryable** → следующий движок (`local`, …) | 0 |
| `local` | `WAN_BASE_URL` (Comfy/Wan на отдельной GPU, не в compose панели). Образ чат+Wan для Salad: [`docker/salad-gpu`](../docker/salad-gpu/README.md). Хост `*.salad.cloud` не держит один POST на всё время ролика: панель шлёт `X-Async: 1` и опрашивает задачу (шлюз Salad рвёт тишину через ~100 с, HTTP 524). Прямой GPU без Salad остаётся синхронным, пока не задан `WAN_ASYNC=true` | 0 |
| `hfspace` | `HF_SPACE_ID`, experimental | 0 |
| `slideshow` | `ffmpeg` в PATH на воркере | 0 |

Чужие утекшие ключи и скрейп случайных GitHub-обёрток не подключаются.

## Промпт + референс (I2V / V2V / Ken Burns)

У задачи рендера: `input_mode` (`text_only`, `image_to_video`, `video_to_video`, `image_slideshow`) и `reference_json` — массив `{ "role": "start_image"|"motion_video"|…, "asset_id" или "filename" }`. Файл `filename` — только из библиотеки загрузок (`data/videos/source`), `asset_id` — из `MediaAsset`.

| Режим | Референс | Бэкенды |
| --- | --- | --- |
| `image_to_video` | фото (`start_image`) | `fal` (upload + `FAL_MODEL_I2V`), `local` (`image_base64` в JSON Wan) |
| `video_to_video` | короткий mp4 (`motion_video`, обрезка до 15 с) | `fal` (`video_url`), `local` (`video_base64`) |
| `image_slideshow` | фото | только `slideshow` (Ken Burns, без ML) |

Цепочка `auto` **пропускает** движки без `supports_i2v` / `supports_v2v`. Для slideshow при `input_mode=image_slideshow` backend принудительно `slideshow`. `GET /api/generations/backends` возвращает флаги `supports_i2v`, `supports_v2v`, `supports_slideshow`.

Чат и UI: `POST /api/generations` / `create_render` с `reference_filename`, `reference_asset_id`, `reference_role`, `input_mode`. Промпт обязателен; `account_id` по желанию; `backend` по умолчанию `auto`. Если healthcheck выбранного (или всей цепочки) не проходит — ошибка **как есть**. Живость: `GET /api/generations/backends`, в чате `list_render_backends` и `diagnose`.

В нижнем чате агента **Ctrl+V** вставляет картинку (upload в библиотеку) и передаёт `filename` модели для `create_render` + `image_to_video`. Во время `wait_render` в чате видна панель прогресса рендера (статус и стадия).

`local` перед запросом к `WAN_BASE_URL` выгружает модели Ollama (`keep_alive: 0`) и держит `data/gpu_slot.lock`, чтобы чат не забрал VRAM посреди ролика. Чат в это время отвечает, что GPU занята рендером. На одной 24 GB карте чат и видео всё равно не живут одновременно.

Синхронный `POST /generate` через публичный хост `*.salad.cloud` не дожидается Wan: шлюз отвечает **524** примерно через 100 с, хотя контейнер ещё рендерит. Для таких URL (и при `WAN_ASYNC=true`) воркер сразу получает `job_id` и опрашивает `GET /generate/jobs/{id}`, затем скачивает mp4. Нужны образ GPU с этим API и пересобранный `reels-worker`. **409** на `/generate` значит, что GPU уже занята другим роликом (часто хвост после 524 на старом образе), а не то, что `WAN_BASE_URL` неверный.

После постановки статус `queued`: рендерит **воркер**. В автономном run после `create_render` нужен `wait_render`, иначе `publish_now` упрётся в ещё не готовый файл.

## Сколько ждать (local Salad vs fal)

| Бэкенд | 5 с T2V, типично | Почему |
| --- | --- | --- |
| `fal` | ~1–5 мин | Очередь fal.ai, Wan 2.5 в облаке |
| `local` (Salad Wan 1.3B) | **10–25 мин** на первый клип после cold start; не «5 секунд ролика = 5 секунд генерации» | `t5_cpu`, offload, одна 24 GB карта; см. [`generate_server.py`](../docker/salad-gpu/generate_server.py) |
| Таймаут воркера | `GENERATION_TIMEOUT_SECONDS` (дефолт в коде **1920 с**, на Salad минимум **1920** = Wan 1800 с + буфер; в `.env.example` **2100**) | Ошибка **`local: таймаут ожидания Wan`** = опрос async-задачи не дождался `done`; UI читает `poll_timeout_ms` из `GET /api/generations/{id}` |

Карточка GPU (`GET /api/gpu`) для `*.salad.cloud`: **`wan_async_ok`** — POST с `X-Async: 1` отвечает **202/409/400**, а не синхронный mp4 (**200** без `job_id`). Если `wan_ok` и `wan_async_ok=false` — обновите Command (`wan-async-patch`) и `generate_server.py` с Utah.

Диагностика с VPS: `curl -sS -X POST "$WAN_BASE_URL" -H 'Content-Type: application/json' -H 'X-Async: 1' -d '{"prompt":"","duration_s":5}'` → **400** или **202** = async API есть; **200** mp4 = старый sync (524 на длинном рендере).

Таблица `/renders`: полоса статусов, селект движка, «Поставить рендер», «Отменить» (только `queued`), «Повторить». Чат: `list_renders`, `cancel_render` (с confirm), `retry_render` (`backend: local` — на Wan), после `create_render` / `generate_wan` — **`wait_render`** (чат занят до done/failed). Что оплачивать и куда: [costs.md](costs.md).

## Склейка

`POST /api/compositions` / `compose`: минимум **два** `clip_ids` из каталога `MediaAsset` (рендеры/склейки в `media_dir`), не по `filename` из upload-листа `video_source_dir`. Опционально саундтрек (`audio_asset_id`), аккаунт, заголовок. Нет id — чат спрашивает.

Отмена / повтор — как у рендера (`cancel_composition`, `retry_composition`). Список: `list_compositions`. На Активности — полоса «Склейки».

## Страница «Агент» (контент-план)

Это **не** нижний чат. Модель по брифу и источникам предлагает ролики и ставит `PlanJob` / генерации.

Поля UI: аккаунт, пресет, бриф, «Сколько роликов» (1–20), «Длительность, с» (5–10), «Сразу ставить в расписание» (`auto_schedule`).

- «Запланировать» — `plan_account` в очередь воркера (`auto_schedule` по умолчанию true, длительность 5 с, если не задали).
- «План на неделю» — тот же план со `spread_over_days=7` (`week=true` в чате).
- «Превью» — `preview_plan` / `POST …/preview`: сразу вызывает агента и пишет реальные `GenerationJob` с `auto_schedule=false` (после рендера **не** ставятся `PostJob`). Это не dry-run: воркер всё равно рендерит очередь. Отличие от «Запланировать» — нет `PlanJob` и нет авторасписания.

Источники: URL (allowlist хостов в настройках reference) или файл в каталоге reference. «Проверить» / `check_source`. Чат: `add_source`. Удаление источника — UI.

Открытые вопросы агента: «Ответить» / `answer_question`. Новые вопросы не пишутся в БД, пока есть открытый (ответы из прошлых планов попадают в промпт).

Воркер нужен для «Запланировать» / `plan_account`: иначе `PlanJob` останётся `queued`. Для превью воркер нужен только чтобы отрендерить созданные генерации.

Таблица прогонов — `AgentRun` (модель, ошибка, cost). Это логи контент-агента, не нижнего чата.
