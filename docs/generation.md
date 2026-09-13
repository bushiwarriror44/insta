# Рендер, склейка и контент-план

## Бэкенды видео

Очередь рендера вызывает [`VideoBackend`](../app/generation/base.py). Имя в задаче: `fal`, `huggingface`, `pollinations`, `local`, `hfspace` или **`auto`**.

По умолчанию `VIDEO_BACKEND=auto`: воркер идёт по `VIDEO_BACKEND_CHAIN` (fal → huggingface → pollinations → local → hfspace). Retryable ошибка или сеть — следующий движок. Не-retryable (плохой промпт) — стоп. Успех пишет в `job.backend` фактическое имя, не `auto`. Если все упали — одна ошибка со списком причин, цитировать как есть.

| Имя | Что нужно | Стоимость в `cost_usd` |
| --- | --- | --- |
| `fal` | `FAL_API_KEY`, модель Wan 2.5 5 или 10 с | прайс fal за секунду |
| `huggingface` | свой `HF_TOKEN`, `HF_VIDEO_MODEL` | 0 |
| `pollinations` | `POLLINATIONS_VIDEO_URL` (ключ необязателен) | 0 |
| `local` | `WAN_BASE_URL` (Comfy/Wan на отдельной GPU, не в compose панели) | 0 |
| `hfspace` | `HF_SPACE_ID`, experimental | 0 |

Чужие утекшие ключи и скрейп случайных GitHub-обёрток не подключаются.

Чат и UI: `POST /api/generations` / `create_render`. Промпт обязателен; `account_id` по желанию; `backend` по умолчанию `auto`. Если healthcheck выбранного (или всей цепочки) не проходит — ошибка **как есть**. Живость: `GET /api/generations/backends`, в чате `list_render_backends` и `diagnose`.

`local` перед запросом к `WAN_BASE_URL` выгружает модели Ollama (`keep_alive: 0`) и держит `data/gpu_slot.lock`, чтобы чат не забрал VRAM посреди ролика. Чат в это время отвечает, что GPU занята рендером. На одной 24 GB карте чат и видео всё равно не живут одновременно.

После постановки статус `queued`: рендерит **воркер**. В автономном run после `create_render` нужен `wait_render`, иначе `publish_now` упрётся в ещё не готовый файл.

Таблица `/renders`: полоса статусов, селект движка, «Поставить рендер», «Отменить» (только `queued`), «Повторить». Чат: `list_renders`, `cancel_render` (с confirm), `retry_render` (`auto` снова идёт по цепочке).

## Склейка

`POST /api/compositions` / `compose`: минимум **два** `clip_ids` из библиотеки, опционально саундтрек (`audio_asset_id`), аккаунт, заголовок. Нет id — чат спрашивает. Не загрузка с диска оператора.

Отмена / повтор — как у рендера (`cancel_composition`, `retry_composition`). Список: `list_compositions`. На Активности — полоса «Склейки».

## Страница «Агент» (контент-план)

Это **не** нижний чат. Модель по брифу и источникам предлагает ролики и ставит `PlanJob` / генерации.

Поля UI: аккаунт, пресет, бриф, «Сколько роликов» (1–20), «Длительность, с» (5–10), «Сразу ставить в расписание» (`auto_schedule`).

- «Запланировать» — `plan_account` в очередь воркера (`auto_schedule` по умолчанию true, длительность 5 с, если не задали).
- «План на неделю» — тот же план со `spread_over_days=7` (`week=true` в чате).
- «Превью» — `preview_plan`: прогон **без** постановки в авторасписание (`auto_schedule=false` на превью).

Источники: URL (allowlist хостов в настройках reference) или файл в каталоге reference. «Проверить» / `check_source`. Чат: `add_source`. Удаление источника — UI.

Открытые вопросы агента: «Ответить» / `answer_question`. Пока вопрос открыт, план может не ехать.

Воркер должен работать, иначе `PlanJob` останется `queued`.

Таблица прогонов — `AgentRun` (модель, ошибка, cost). Это логи контент-агента, не нижнего чата.
