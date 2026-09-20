# GPU-образ для Salad: чат + Wan 1.3B

Не входит в `docker compose` админ-VPS. Сборка на своём ПК, публикация на Docker Hub, одна Container Group на Salad.

Внутри: Ollama `qwen3:32b` (в каталоге Qwen3 нет 20B; 32B — следующий размер после 8B/14B), Wan 2.1 T2V 1.3B, nginx `:8080` (`/v1` и `/api` → Ollama, `/generate` → видео). На 24 GB VRAM чат и ролик по очереди: 32B Q4 занимает ~20 GB, перед Wan панель делает `keep_alive: 0`.

## Сборка (Windows, Docker Desktop)

Свободно ~70 ГБ диска (32B тяжелее 8B). Сборка 2–4 часа (качает модель и веса).

```powershell
cd C:\Users\PC\Desktop\insta\docker\salad-gpu
docker login
docker build -t ТВОЙ_ЛОГИН/insta-gpu:chat-wan .
docker push ТВОЙ_ЛОГИН/insta-gpu:chat-wan
```

На hub.docker.com репозиторий `insta-gpu` сделай **Public**, иначе Salad не скачает без логина.

## Salad

Stop старых групп (Ubuntu / чистый Ollama). Create container group:

- Image: `ТВОЙ_ЛОГИН/insta-gpu:chat-wan`
- 1 replica, RTX 3090, RAM ≥ 16 GB
- HTTP, порт контейнера **8080**
- Auth на шлюзе лучше выключить до правки панели (`Salad-Api-Key`); хост никуда не светить

Жди Ready (первый узел качает толстый образ, это не тарится). Потом GPU-часы.

## Админка (Utah)

```bash
AGENT_BASE_URL=https://НОВЫЙ-ХОСТ.salad.cloud/v1
AGENT_MODEL=qwen3:32b
WAN_BASE_URL=https://НОВЫЙ-ХОСТ.salad.cloud/generate
```

```bash
cd /opt/insta && docker compose up -d --force-recreate reels-api reels-worker
```

Проверка с VPS: `curl -sS https://НОВЫЙ-ХОСТ.salad.cloud/` → `Ollama is running`. Рендер в панели — backend `local`.

Не пользуешься — **Stop** группы, иначе идёт почасовка. Start снова качает образ на новый ПК.

Stop/Start из панели: карточка **GPU Salad** на `/administration` (`SALAD_API_KEY` + имена org/project/group в `.env` админ-VPS). Это не тумблер «Агент» в шапке (тот крутит `reels-worker`). API при старте группу сам не поднимает. Ключ в чат и документы не копировать.
