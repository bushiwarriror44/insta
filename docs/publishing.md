# Публикация и библиотека

## Откуда ролик

- Загрузка в UI (DropZone) → файлы в `data/videos/source` (и записи `MediaAsset`).
- Рендер fal → клип в библиотеке.
- Склейка нескольких клипов → новый ассет.
- Чат **не** читает произвольный диск оператора: только `filename` в библиотеке или `asset_id`.

Типы файла: видео для `reel` / `feed_video` / `youtube_short` / `tiktok`; `feed_photo` — картинка.

## Типы поста

`reel`, `feed_photo`, `feed_video`, `youtube_short`, `tiktok`.

`publish_now` / `enqueue_publish` без `post_type` берут тип из площадки аккаунта (`post_type_for`). В UI тип выбирается вручную.

Поля как в превью библиотеки: `title`, `caption` / `caption_template`, `description`, `tags`, `when` (ISO UTC).

## Статусы `PostJob`

| Статус | Смысл |
| --- | --- |
| `awaiting_review` | ждёт «Одобрить» (`hold_for_review` + постановка из чата) |
| `queued` | воркер заберёт, когда наступит `scheduled_for` |
| `running` | uniquify + загрузка |
| `done` | площадка приняла |
| `failed` | ошибка, можно `retry_job` |
| `dead` | исчерпаны попытки (`JOB_MAX_ATTEMPTS`) |
| `cancelled` | отмена |

Рендер / склейка / план используют `PipelineStatus`: `queued` / `running` / `done` / `failed` / `dead` / `cancelled` — **без** `awaiting_review`.

## Очередь vs «сейчас»

- **Запланировать** / `enqueue_publish`: слот в календаре, воркер сам. Дата: `when` или позже `reschedule_job`. Drag в календаре — только UI.
- **Опубликовать сейчас** / `publish_now`: сначала `test_connection`; при ok — в очередь (часто «прямо сейчас») и при `awaiting_review` — авто-`approve_job`. Воркер при этом **сам не запускается**: если баннер «Агент остановлен», задача висит.

Воркер: тумблер на Панели/Агенте, `start_worker`, или контейнер `reels-worker`.

## Uniquify и backoff

Перед загрузкой ffmpeg меняет ролик (кроп, цвет, звук, метаданные), чтобы не слать байт-в-байт копию. Выход: `data/videos/out`. Падение uniquify — ошибка джобы, не «Instagram отклонил».

После ошибки — exponential backoff, `next_attempt_at`. Жёсткие баны / challenge переводят аккаунт в `cooldown` / `challenge`. Код челленджа: CLI `provide-code` или UI.

## Календарь и активность

Календарь — те же `PostJob` по `scheduled_for`. Активность — три полосы (публикации, рендеры, склейки), логи `job_logs`.

Статистика просмотров: «Обновить статистику» / `refresh_stats` по id **публикации** (`PostLog`), не job id.

## Воркер не равен чату

Пока воркер мёртв, рендер fal, склейка и публикация из очереди не едут. Чат может поставить задачу и написать «воркер не запущен».
