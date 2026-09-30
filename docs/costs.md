# Что, когда, где и в каком объёме оплачивать

Панель не касса: списаний из UI нет. Деньги берут кабинеты снаружи. Ключи, GPU-URL, `entry_path` и токены в этот файл и в чат-ответы про оплату не копировать.

`cost_usd` в SQLite (колонка `$` на Рендерах и в прогонах Агента) — оценка **ролика fal**. Часы Salad, счёт VPS и прокси туда не попадают.

## Что

| Система | Зачем панели | Платить |
| --- | --- | --- |
| Админ-VPS | `reels-frontend`, `reels-api`, `reels-worker`, SQLite в `data/` | да, хостеру. Ollama сюда не ставить (6 GB мало) |
| Salad GPU | `AGENT_BASE_URL` + `WAN_BASE_URL`, образ [`docker/salad-gpu`](../docker/salad-gpu/README.md) | да, пока группа Running |
| Clore / Vast | тот же `.env` вместо Salad, не оба сразу | да, кабинету GPU-хоста |
| fal.ai | бэкенд `fal`, ключ `FAL_API_KEY` | да, за секунду ролика |
| HuggingFace | `huggingface` / `hfspace`, `HF_TOKEN` | по кабинету HF; в `cost_usd` панель пишет 0 |
| Pollinations | `pollinations`, ключ необязателен | 0 в панели |
| Прокси | Instagram / YouTube / TikTok, не чат и не Ollama | да, продавцу прокси |
| Telegram | алерты `TELEGRAM_BOT_TOKEN` | API бота бесплатный |
| Docker Hub | публичный образ для Salad | обычно бесплатно |
| Graph / YouTube Data API / TikTok Content Posting | не используются | не платить |

## Когда

- VPS — по счёту хостера, пока машина жива.
- Salad — с Ready до Stop. Простой в статусе Running тарится. Первый pull образа на узел — нет. Start после Stop снова качает образ на другой ПК. Start/Stop — карточка **GPU Salad** на `/administration` (`POST /api/gpu/start|stop`), не кабинет Salad и не тумблер воркера в шапке. Чат группу не стартует.
- fal — успешный ролик с фактическим `backend=fal` (в т.ч. из цепочки `auto`).
- `local` — часы GPU-хоста, не строка `$` в таблице.
- Чат и PlanJob — пока нода `AGENT_BASE_URL` Running. Одна 24 GB карта: чат XOR видео (`gpu_slot.lock`).
- Прокси — пока аккаунты ходят в площадки.

## Где

- Salad: кабинет (кредиты USDC / EURC / RENDER в Solana, не USDT). Start/Stop группы — карточка GPU Salad на `/administration`.
- fal: dashboard fal.ai.
- HF: billing Hugging Face.
- Прокси: кабинет продавца.
- VPS: счёт хостера.
- В панели: колонка `$` на `/renders` и прогоны `/agent`; карточка «Оплата» на `/administration`. Балансы кабинетов панель не читает.

## Объём

fal Wan 2.5 (`fal-ai/wan-25-preview/text-to-video` и `image-to-video`): `0.05` USD за секунду выхода — из кода [`app/generation/fal.py`](../app/generation/fal.py), не из кабинета. Клип 5 с = `0.25`, 10 с = `0.50`. Другая модель в таблице кода — свой коэффициент; неизвестная — `0.0`, не выдумывать.

Режим `image_slideshow` (бэкенд `slideshow`, ffmpeg Ken Burns): `cost_usd=0`, без fal/GPU-модели.

Salad $/час в репозиторий не зашит: смотри баланс в кабинете. Не пользуешься — Stop группы с карточки GPU Salad.

`huggingface` / `pollinations` / `local` / `hfspace`: `cost_usd=0`. Если цепочка дошла до `local` на Salad — идут GPU-часы.

Не поднимать `reels-ollama` на админ-VPS. Не держать Salad Running «на всякий случай».
