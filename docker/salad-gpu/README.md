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

После правки зависимостей Wan (например `dashscope`) образ нужно собрать и запушить заново, затем Stop/Start группы Salad, чтобы подтянулся новый digest. Панель Utah (`reels-worker`) для этого не пересобирается.

### Wan без пересборки образа (быстро)

Старый образ на Hub без `dashscope` можно починить **на узле** за пару минут:

1. **Через панель** (после `git pull` и пересборки только `reels-api`): одно сообщение в нижний чат с настроенным Salad — панель обновит Command и выполнит `pip install dashscope` перед `start.sh` (маркер `wan-dashscope` в команде). Реплика перезапустится один раз.
2. **Вручную в Salad** → Edit → Command: после `set -eu` добавьте строку  
   `python -m pip install -q dashscope`  
   перед `/opt/gpu/start.sh`. Save перезапускает контейнер; качается только пакет (~1–2 мин), не весь образ.

Пересборка `docker build` на ПК по-прежнему нужна для **новых** узлов с нуля, но для уже работающей группы достаточно варианта 1 или 2.

### Async Wan без пересборки образа (HTTP с Utah)

Если на VPS только **IP без HTTPS**, можно раздавать свежий `generate_server.py` с **reels-api** (порт **8000**):

1. В `.env` на Utah:
   - `SALAD_GPU_PATCH_PUBLIC_BASE=http://ВАШ_ПУБЛИЧНЫЙ_IP:8000`
   - `SALAD_GPU_PATCH_TOKEN=` длинная случайная строка (`openssl rand -hex 24`)
   - `WAN_BASE_URL` уже указывает на Salad `/generate`
2. Откройте **TCP 8000** в firewall VPS (Salad-узлы качают файл по HTTP).
3. `docker compose up -d --build reels-api` (файл лежит в образе из репозитория).
4. Проверка с ПК:  
   `curl -fsSL "http://IP:8000/api/salad-gpu/generate_server.py?token=ТОКЕН" | head`
5. Одно сообщение в нижний чат (или Start GPU в админке) — панель допишет в Command короткий `curl … -o /opt/gpu/generate_server.py` (маркер `wan-async-patch`). **Не** вставляйте base64 вручную.

После Running: `POST` на `/generate` с `X-Async: 1` → **202** и `job_id`.

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

Публичный шлюз Salad обрывает один долгий `POST /generate` через ~100 с (**524**), хотя Wan внутри ещё работает. Панель для `*.salad.cloud` сама включает async (`X-Async: 1` + опрос). Это есть в образе только после пересборки `generate_server.py` и в `reels-worker` после деплоя панели. Пока образ старый, 524 останется. Если Utah уже новый, а Salad — нет, повторный рендер часто даёт **409** (`GPU already rendering`): прошлый ролик ещё крутится. Stop/Start сбрасывает lock, но без нового образа 524 вернётся.

Проверка с VPS после пуша образа: `POST` на `/generate` с заголовком `X-Async: 1` и телом `{"prompt":"test"}` должен ответить **202** и JSON с `job_id`. Ответ **200** с mp4 или долгий запрос без 202 — образ всё ещё старый.

Не пользуешься — **Stop** группы, иначе идёт почасовка. Start снова качает образ на новый ПК. Панель сама гасит группу после простоя (`SALAD_IDLE_STOP_MINUTES`, по умолчанию 120): см. карточку GPU Salad.

## Прогрев qwen3:32b без пересборки

Шлюз Salad рвёт публичный HTTPS примерно через 100 с. Пока 32B грузится в VRAM, чат снаружи получает 524. Прогрев идёт **внутри** контейнера, на `127.0.0.1:11434`.

Шлюз Salad стучится в контейнер по IPv6. nginx должен слушать `[::]:8080` с `ipv6only=off` (`/v1`, `/api`, `/generate`). Если в образе остался только `listen 8080`, снаружи будет страница 503 и чат зависнет на «Жду Ollama», хотя реплика в портале RUNNING. Ollama внутри — на `127.0.0.1:11434`; прогрев туда же.

Нижний чат один раз дописывает в команду прогрева правку этого nginx (`gateway-ipv6`) и перезапускает реплику. Образ на Hub для этого пересобирать не нужно.

Публичный порт шлюза:

- **8080**, если в `.env` админки задан `WAN_BASE_URL` (чат и Wan на одном хосте). Нижний чат сам выставляет этот порт через Salad API, если группа стоит на другом. Ручная смена на 11434 после сообщения в чат откатится обратно на 8080.
- **11434**, если `WAN_BASE_URL` пуст (только чат, прямой Ollama). `/generate` с этого порта не открывается.

Auth на шлюзе лучше выключить.

Группа → Edit → Command, вставить целиком (заменяет пустой Command, `start.sh` всё равно стартует):

```text
/bin/bash -c 'set -eu; /opt/gpu/start.sh & spid=$!; ( i=0; while [ "$i" -lt 90 ]; do curl -sf http://127.0.0.1:11434/ >/dev/null && break; i=$((i+1)); sleep 2; done; python -c '"'"'import json,urllib.request; b=json.dumps({"model":"qwen3:32b","prompt":"hi","stream":False,"keep_alive":"30m"}).encode(); urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/generate", data=b, headers={"Content-Type":"application/json"}), timeout=600).read()'"'"' ) >/tmp/warmup.log 2>&1 & wait "$spid"'
```

Save перезапускает реплику. Образ на Hub не пересобирать. Старые группы держать Stop.

Stop/Start из панели: карточка **GPU Salad** на `/administration` (`SALAD_API_KEY` + имена org/project/group в `.env` админ-VPS). Нижний чат сам поднимает группу и один раз прописывает команду прогрева. Это не тумблер «Агент» в шапке (тот крутит `reels-worker`). Ключ в чат и документы не копировать.
