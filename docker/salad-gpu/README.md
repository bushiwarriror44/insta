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

Не пользуешься — **Stop** группы, иначе идёт почасовка. Start снова качает образ на новый ПК. Панель сама гасит группу после простоя (`SALAD_IDLE_STOP_MINUTES`, по умолчанию 20): см. карточку GPU Salad.

## Прогрев qwen3:32b без пересборки

Шлюз Salad рвёт публичный HTTPS примерно через 100 с. Пока 32B грузится в VRAM, чат снаружи получает 524. Прогрев идёт **внутри** контейнера, на `127.0.0.1:11434`.

В текущем образе nginx слушает только IPv4 `:8080`, Ollama уже на `[::]:11434`. Для чата порт шлюза — **11434**, auth выкл. `/generate` (Wan) с этого порта не открывается.

Группа → Edit → Command, вставить целиком (заменяет пустой Command, `start.sh` всё равно стартует):

```text
/bin/bash -c 'set -eu; /opt/gpu/start.sh & spid=$!; ( i=0; while [ "$i" -lt 90 ]; do curl -sf http://127.0.0.1:11434/ >/dev/null && break; i=$((i+1)); sleep 2; done; python -c '"'"'import json,urllib.request; b=json.dumps({"model":"qwen3:32b","prompt":"hi","stream":False,"keep_alive":"30m"}).encode(); urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=b, headers={"Content-Type":"application/json"}), timeout=600).read()'"'"' ) >/tmp/warmup.log 2>&1 & wait "$spid"'
```

Save перезапускает реплику. Образ на Hub не пересобирать. Старые группы держать Stop.

Stop/Start из панели: карточка **GPU Salad** на `/administration` (`SALAD_API_KEY` + имена org/project/group в `.env` админ-VPS). Нижний чат сам поднимает группу и один раз прописывает команду прогрева. Это не тумблер «Агент» в шапке (тот крутит `reels-worker`). Ключ в чат и документы не копировать.
