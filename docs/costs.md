# Что, когда, где и в каком объёме оплачивать

Списания выполняются в кабинетах поставщиков. Панель сохраняет только оценку `cost_usd` в SQLite. Ключи, адреса GPU, `entry_path` и токены в этот файл не копируются.

Оценка показывается колонкой `$` на `/renders` и суммой прогона на `/agent`. Часы Salad, счёт VPS и оплата прокси в `cost_usd` не входят. Журнал действий прогона: `GET /api/agent-reports/logs`.

## Что

| Система | Зачем панели | Платить |
| --- | --- | --- |
| Админ-VPS | `reels-frontend`, `reels-api`, `reels-worker`, SQLite в `data/` | хостеру. Профиль `ollama` на этой машине не используется |
| Salad GPU | чат и распознавание экрана, образ `takeoishchi31/insta-gpu:ollama-vision`, порт контейнера 8080 | пока группа Running |
| Clore / Vast | тот же `.env` вместо Salad | кабинету GPU-хоста. Одновременно с Salad не используются |
| fal.ai | бэкенд `fal`, ключ `FAL_API_KEY` | за секунду ролика, сумма пишется в `cost_usd` |
| Qubax | бэкенд `qubax`, ключ на странице Qubax или `QUBAX_API_KEY` | 0,50 USD за каждые 5 с, сумма пишется в `cost_usd` |
| Hugging Face | `huggingface` / `hfspace`, `HF_TOKEN` | по кабинету HF; в `cost_usd` записывается 0 |
| Pollinations | `pollinations` | 0 в `cost_usd` |
| slideshow | ffmpeg Ken Burns | 0 в `cost_usd` |
| Локальный Wan | в интерфейсе отключён | 0 в `cost_usd` |
| Прокси | Instagram / YouTube / TikTok | продавцу прокси |
| Telegram | `TELEGRAM_BOT_TOKEN` | Bot API отдельной платы не требует |
| Docker Hub | публичный образ для Salad | по тарифу Hub, публичный репозиторий обычно без платы |
| Graph / YouTube Data API / TikTok Content Posting | не вызываются | отдельной платы нет |

Чат на Salad — `qwen3:30b-a3b`, распознавание экрана — `qwen2.5vl:7b`. В память видеокарты одновременно загружается одна модель.

## Когда

- VPS оплачивается по счёту хостера, пока машина включена.
- Salad тарифицируется с готовности группы до остановки. Простой в статусе Running входит в счёт. Первая загрузка образа на узел в счёт GPU не входит. Повторный запуск после остановки скачивает образ снова.
- Запуск и остановка: карточка GPU Salad на `/administration`, методы `GET /api/gpu`, `POST /api/gpu/start`, `POST /api/gpu/stop`. Тумблер воркера в шапке эту группу не переключает. Чат эти методы не вызывает.
- fal записывает `cost_usd` после успешного ролика с `backend=fal`, в том числе если ролик выбран цепочкой `auto`.
- Qubax записывает свою оценку после успешного ролика.
- Чат и PlanJob используют модель, пока адрес `AGENT_BASE_URL` отвечает.
- Прокси оплачиваются, пока аккаунты ходят на площадки.

## Где

- Salad: кабинет, кредиты USDC / EURC / RENDER в сети Solana. Запуск и остановка группы — карточка GPU Salad на `/administration`.
- fal: кабинет fal.ai.
- Hugging Face: billing Hugging Face.
- Qubax: кабинет Qubax.
- Прокси: кабинет продавца.
- VPS: счёт хостера.
- В панели балансы кабинетов не запрашиваются. Карточка «Оплата» на `/administration`.

## Объём

fal Wan 2.5 (`fal-ai/wan-25-preview/text-to-video` и `image-to-video`): `0.05` USD за секунду выхода, расчёт в [`app/generation/fal.py`](../app/generation/fal.py). Ролик 5 с — `0.25` USD, 10 с — `0.50` USD. Модель, которой нет в таблице коэффициентов, даёт `0.0`.

Qubax: `0.50` USD за каждые 5 с, расчёт в [`app/generation/qubax.py`](../app/generation/qubax.py).

Ставка Salad за час в репозитории не задана. Остановка неиспользуемой группы выполняется карточкой GPU Salad.

`huggingface`, `pollinations`, `slideshow` и локальный Wan: `cost_usd=0`.
