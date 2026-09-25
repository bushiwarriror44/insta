"""The prompt box: one question in, an answer and maybe a page out."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.assistant import tools
from app.assistant.tools import Opened, ToolError
from app.config import Settings, get_settings
from app.services import ollama_control
from app.services.http import client as http_client
from app.services.runtime import probe
from app.services.salad_gpu import SaladProblem, configured as salad_configured, prepare_for_chat

ROUNDS = 6
RUN_ROUNDS = 12
MAX_TOOL_CHARS = 12000
HANDBOOK_PATH = Path(__file__).resolve().parents[2] / "docs" / "assistant-handbook.md"
DONT_KNOW = "я не знаю ответ на этот вопрос"

SYSTEM_PROMPT = """\
Ты — ассистент внутри админ-панели публикаций коротких видео \
(Instagram, YouTube Shorts, TikTok). Ты говоришь с доверенным оператором \
на этой локальной машине. Панель уже под паролем. Секреты можно и нужно \
показывать целиком: пароли аккаунтов, email, TOTP, session_id, backup codes, \
URL прокси, токен владельца, содержимое файлов проекта.

Пользуйся инструментами и справочником ниже, а не памятью и не общими знаниями \
про интернет, VPN или чужие продукты. Спросили, что есть, что застряло \
или что запланировано — сначала смотри. Спросили пароль, прокси или файл — \
открой `account_details` / `list_proxies` / `read_project_file` и отдай как есть. \
Спросили, что сломалось, что упало в коде или почему стек молчит — сначала \
`diagnose`, не память. Сломался постинг — `diagnose`, затем ветка \
«Если постинг сломался» из справочника. Сломался вход — `diagnose`, затем ветка \
«Если вход сломался». Сломался прокси — `diagnose`, затем ветка «Если прокси сломался». \
Конкретная публикация — `job_logs`. Логи входа аккаунта — \
`account_logs`. Логи Docker/compose — `docker_logs`. Как работают доступы — `list_operators`. \
Спросили, что ты умеешь, как и что для этого нужно — ответь блоком \
«Я сам / Только в UI / Нужно от оператора» из справочника.

Просят показать страницу, клип, публикацию, аккаунт или прокси — открывай \
инструментом `open_*` / `open_page` и коротко скажи, что открыл. \
`screenshot_page` и `page_guide` не вызывай, пока оператор не попросил снимок \
или другую страницу.

Ты можешь: создать и обновить аккаунт (`create_account`, `create_accounts`, `update_account`), \
создать и обновить прокси (`create_proxy`, `create_proxies`, `update_proxy`, `attach_proxy`), \
экспорт/импорт cookies (Instagram sessionid или Playwright Studio для YouTube/TikTok), \
fingerprint только для Instagram, `get_session`, проверить прокси и подключение \
(`test_proxy`, `test_proxies`, `test_connection`, `test_connections`), \
опубликовать ролик (`publish_now`, `enqueue_publish`; тип из площадки аккаунта, поля title / caption / description / tags / when), \
перенести слот (`reschedule_job`), править лимиты и проверку (`update_account`: daily_post_cap, hold_for_review, login_surface), \
поставить план (`plan_account`: duration_s / auto_schedule; список — `list_plans` / `list_questions` / `list_sources` / `list_presets`, пресет — `apply_preset`), превью (`preview_plan`), \
поставить рендер (`create_render`, по умолчанию цепочка `auto`) и склейку (`compose`), \
статусы движков — `list_render_backends`, \
автовход и mint mobile только для Instagram, \
паузу, ответить на вопрос агента, \
добавить источник, читать файлы проекта, `diagnose`, `docker_logs`. \
После create/update/export, если оператор не на нужной странице — `open_page`. \
Экспорт cookies/Playwright state скачивает файл в браузере (как кнопки модалки «Сессия»). \
Живой браузер из чата не открывай (Instagram, YouTube и TikTok). \
Graph / YouTube Data API / TikTok Content Posting API и OAuth не используются — как устроены неофициальные клиенты, смотри справочник.

Ты не можешь удалять ничего. Если просят удалить — откажись.

Неполная задача (нет username, proxy_label, url прокси и т.п.) — вызови \
`ask_operator` со списком коротких вопросов и зачем они нужны. Не выдумывай поля. \
Пока оператор не ответил сообщением «Уточнения: …» — не вызывай create_*. \
Несколько аккаунтов или прокси в одном сообщении — `create_accounts` / `create_proxies` \
(JSON-массив `items`, до 20). Если ни у одной строки нет обязательных полей — `ask_operator`. \
Частичный успех верни как есть: created и failed. \
Спросили про другую страницу, не текущую — сначала `page_guide`.

Правила про ответ:
1. Отвечай на языке обращения. По-русски спросили — по-русски.
2. Говори только то, что есть в справочнике или что только что вернул инструмент. \
Не выдумывай экраны, кнопки и «подключение агента к интернету».
3. Если факта нет — ответь дословно: «я не знаю ответ на этот вопрос». \
Без советов проверить прокси, настройки или «что-то ещё».
4. Если инструмент вернул поле «ошибка», traceback, available: false или пустые \
логи — процитируй как есть. Не смягчай и не выдумывай причину.
5. Статус — одно-два предложения. Как добавить аккаунт/прокси, как публиковать \
или как устроены доступы — по шагам из справочника, обычным текстом, без разметки. \
Страницы открывай инструментом, а не пиши URL."""


RUN_PROMPT = """\
Это автономный run (`POST /api/assistant/run` / `python -m app.cli ask`), не нижний чат UI. \
Страницы панели не открывай — `open_page` не обязателен. \
Можно стартовать живой Playwright (`start_browser`) для Instagram, YouTube и TikTok, \
смотреть статус (`browser_status`), сохранить cookies (`save_browser_session`), \
передать код 2FA (`submit_browser_code`). Instagram по логину/паролю — `first_login`. \
YouTube/TikTok — вход в Playwright Studio (cookies в state.json), не пароль Google как у instagrapi. \
После `create_render` дождись `wait_render`, затем `publish_now`. После `plan_account` — `wait_plan`, потом `wait_render` по generation_ids. Удаления, операторы, секретный путь и мастер-пароль — нельзя."""


PAGE_HEADING = re.compile(r"^## Страница:\s*(.+?)\s*$", re.M)
PATH_TITLES = {
    "/": "Панель",
    "/accounts": "Аккаунты",
    "/publishing": "Библиотека",
    "/agent": "Агент",
    "/renders": "Рендеры",
    "/calendar": "Календарь",
    "/activity": "Активность",
    "/maintenance": "Обслуживание",
    "/operators": "Доступы",
    "/settings": "Настройки",
    "/administration": "Администрирование",
}
TITLE_PATHS = {title: path for path, title in PATH_TITLES.items()}


def load_handbook(path: Path | None = None) -> str:
    target = path or HANDBOOK_PATH
    try:
        return target.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def split_handbook(text: str) -> tuple[str, dict[str, str]]:
    matches = list(PAGE_HEADING.finditer(text))
    if not matches:
        return text.strip(), {}
    core = text[: matches[0].start()].strip()
    pages: dict[str, str] = {}
    for i, match in enumerate(matches):
        title = match.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        pages[title] = text[match.start() : end].strip()
    return core, pages


def page_title(page: str | None) -> str | None:
    if not page:
        return None
    raw = str(page).strip()
    if not raw:
        return None
    if raw in PATH_TITLES.values():
        return raw
    path = raw.split("?", 1)[0]
    if path in PATH_TITLES:
        return PATH_TITLES[path]
    parts = [p for p in path.split("/") if p]
    if parts and parts[-1] in {k.lstrip("/") for k in PATH_TITLES if k != "/"}:
        return PATH_TITLES.get(f"/{parts[-1]}")
    try:
        _key, route = tools.resolve_page(raw.lstrip("/"))
    except ToolError:
        return None
    return PATH_TITLES.get(route)


def handbook_page_section(page: str, path: Path | None = None) -> dict[str, str]:
    book = load_handbook(path)
    _core, pages = split_handbook(book)
    title = page_title(page)
    if not title:
        raise ToolError(f"страницы {page!r} нет; страницы такие: {', '.join(PATH_TITLES.values())}")
    section = pages.get(title)
    if not section:
        raise ToolError(f"в справочнике нет страницы {title}")
    return {"page": title, "path": TITLE_PATHS.get(title, ""), "guide": section}


TALK_LIMIT = 8


def system_message(
    path: Path | None = None,
    page: str | None = None,
    *,
    account_id: int | None = None,
    job_id: int | None = None,
    allow_browser: bool = False,
) -> str:
    prompt = SYSTEM_PROMPT + ("\n\n" + RUN_PROMPT if allow_browser else "")
    book = load_handbook(path)
    if not book:
        return prompt
    core, pages = split_handbook(book)
    title = page_title(page)
    section = pages.get(title, "") if title else ""
    here = f"Оператор сейчас на странице {title}." if title else ""
    focus: list[str] = []
    if account_id:
        focus.append(f"На экране открыт аккаунт id={account_id}.")
    if job_id:
        focus.append(f"На экране открыта публикация job_id={job_id}.")
    extra = "\n\n".join(part for part in (core, here, *focus, section) if part)
    return (
        f"{prompt}\n\n---\n"
        f"Справочник (единственный источник правды: ядро + текущая страница; "
        f"остальное — инструмент page_guide):\n\n{extra}"
    )


def schema(name: str, description: str, properties: dict, required: list[str]):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOLS = [
    schema("overview", "Сколько аккаунтов, клипов, публикаций и рендеров.", {}, []),
    schema("list_accounts", "Все аккаунты: имя, пароль, площадка, статус, бриф, прокси.", {}, []),
    schema(
        "account_details",
        "Полная карточка аккаунта включая пароль, TOTP, session_id, email и URL прокси.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "list_posts",
        "Последние публикации с заголовком, аккаунтом, временем и ошибкой.",
        {
            "status": {"type": "string"},
            "account_id": {"type": "integer"},
            "query": {"type": "string"},
        },
        [],
    ),
    schema(
        "list_clips",
        "Клипы или саундтреки в библиотеке.",
        {
            "kind": {"type": "string", "description": "video или audio"},
            "query": {"type": "string"},
        },
        [],
    ),
    schema("list_renders", "Рендеры (backend, статус, ошибка).", {"status": {"type": "string"}}, []),
    schema("list_render_backends", "Какие движки рендера живы: auto, fal, huggingface, pollinations, local, hfspace.", {}, []),
    schema("list_compositions", "Склейки клипов.", {"status": {"type": "string"}}, []),
    schema(
        "list_questions",
        "Открытые вопросы контент-агента (id, текст). Нужен question_id для answer_question.",
        {"account_id": {"type": "integer"}},
        [],
    ),
    schema(
        "list_sources",
        "URL-источники брифа аккаунта. Нужен source_id для check_source.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema("list_presets", "Пресеты брифа (имя и текст).", {}, []),
    schema(
        "list_plans",
        "Прогоны контент-агента: статус, count, planned.",
        {"account_id": {"type": "integer"}},
        [],
    ),
    schema(
        "apply_preset",
        "Скопировать бриф пресета в аккаунт (как выбор пресета на /agent).",
        {"account_id": {"type": "integer"}, "name": {"type": "string"}},
        ["account_id", "name"],
    ),
    schema("list_proxies", "Прокси: метка, URL, страна, здоровье.", {}, []),
    schema(
        "list_errors",
        "Свежие ошибки: события, упавшие публикации и рендеры.",
        {},
        [],
    ),
    schema(
        "job_logs",
        "Диагностические логи публикации и открыть её на Активности.",
        {"job_id": {"type": "integer"}},
        ["job_id"],
    ),
    schema(
        "account_logs",
        "Диагностические логи входа и проверки аккаунта (first_login, connection_test, mint, browser, publish). Пароль в ответе скрыт.",
        {
            "account_id": {"type": "integer"},
            "kind": {
                "type": "string",
                "enum": [
                    "connection_test",
                    "first_login",
                    "mint_mobile_session",
                    "browser_session",
                    "publish_job",
                ],
            },
            "tail": {"type": "integer"},
        },
        ["account_id"],
    ),
    schema(
        "list_operators",
        "Как устроены доступы. Владельцу — секретный URL и токен; оператору — только список операторов.",
        {},
        [],
    ),
    schema(
        "list_project_files",
        "Список файлов и папок внутри проекта.",
        {"path": {"type": "string"}},
        [],
    ),
    schema(
        "read_project_file",
        "Прочитать текстовый файл проекта (включая .env и пароли в коде/данных).",
        {"path": {"type": "string"}},
        ["path"],
    ),
    schema(
        "open_page",
        "Показать оператору страницу панели. Можно с query: activity?status=dead, accounts?username=alice.",
        {"page": {"type": "string"}},
        ["page"],
    ),
    schema("open_clip", "Показать клип в библиотеке.", {"asset_id": {"type": "integer"}}, ["asset_id"]),
    schema("open_post", "Показать публикацию в очереди.", {"job_id": {"type": "integer"}}, ["job_id"]),
    schema(
        "open_account",
        "Показать карточку аккаунта.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "screenshot_page",
        "Снимок страницы панели прямо в разговоре.",
        {"page": {"type": "string", "enum": tools.page_keys()}},
        ["page"],
    ),
    schema(
        "plan_account",
        "Поставить план контента в очередь воркера для аккаунта.",
        {
            "account_id": {"type": "integer"},
            "count": {"type": "integer"},
            "week": {"type": "boolean", "description": "true — план на неделю"},
            "duration_s": {"type": "number", "description": "длина клипа 5–10 секунд"},
            "auto_schedule": {"type": "boolean"},
        },
        ["account_id"],
    ),
    schema(
        "preview_plan",
        "Превью плана без постановки в очередь (как кнопка Превью).",
        {
            "account_id": {"type": "integer"},
            "count": {"type": "integer"},
            "duration_s": {"type": "number"},
        },
        ["account_id"],
    ),
    schema(
        "enqueue_publish",
        "Поставить ролик из библиотеки в очередь публикации.",
        {
            "account_id": {"type": "integer"},
            "filename": {"type": "string"},
            "asset_id": {"type": "integer"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
            "caption_template": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "string"},
            "post_type": {"type": "string"},
            "when": {"type": "string", "description": "ISO дата слота"},
        },
        ["account_id"],
    ),
    schema(
        "reschedule_job",
        "Перенести слот публикации (queued / awaiting_review / failed).",
        {
            "job_id": {"type": "integer"},
            "when": {"type": "string", "description": "ISO дата/время"},
        },
        ["job_id"],
    ),
    schema(
        "pause_account",
        "Поставить аккаунт на паузу.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "resume_account",
        "Снять аккаунт с паузы.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "answer_question",
        "Ответить на открытый вопрос контент-агента.",
        {"question_id": {"type": "integer"}, "answer": {"type": "string"}},
        ["question_id", "answer"],
    ),
    schema(
        "add_source",
        "Добавить URL-источник к брифу аккаунта.",
        {"account_id": {"type": "integer"}, "value": {"type": "string"}, "kind": {"type": "string"}},
        ["account_id", "value"],
    ),
    schema(
        "create_account",
        "Создать аккаунт. Нужны username и proxy_label; пароль по желанию. TOTP и session_id — только Instagram.",
        {
            "username": {"type": "string"},
            "proxy_label": {"type": "string"},
            "password": {"type": "string"},
            "platform": {"type": "string"},
            "totp_seed": {"type": "string"},
            "session_id": {"type": "string"},
            "email": {"type": "string"},
            "email_password": {"type": "string"},
            "brief": {"type": "string"},
            "notes": {"type": "string"},
            "account_line": {"type": "string"},
            "login_identifier": {"type": "string"},
            "backup_codes": {"type": "string"},
        },
        ["username", "proxy_label"],
    ),
    schema(
        "create_accounts",
        "Создать несколько аккаунтов одним вызовом (до 20). items — JSON-массив объектов с username и proxy_label.",
        {
            "items": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "username": {"type": "string"},
                        "proxy_label": {"type": "string"},
                        "password": {"type": "string"},
                        "platform": {"type": "string"},
                        "totp_seed": {"type": "string"},
                        "session_id": {"type": "string"},
                        "email": {"type": "string"},
                        "email_password": {"type": "string"},
                        "brief": {"type": "string"},
                        "notes": {"type": "string"},
                        "account_line": {"type": "string"},
                        "login_identifier": {"type": "string"},
                        "backup_codes": {"type": "string"},
                    },
                },
            },
        },
        ["items"],
    ),
    schema(
        "update_account",
        "Обновить аккаунт: пароль, TOTP, email, бриф, прокси, лимиты, hold_for_review, login_surface. session_id — только Instagram.",
        {
            "account_id": {"type": "integer"},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "totp_seed": {"type": "string"},
            "session_id": {"type": "string"},
            "email": {"type": "string"},
            "email_password": {"type": "string"},
            "brief": {"type": "string"},
            "notes": {"type": "string"},
            "proxy_label": {"type": "string"},
            "login_identifier": {"type": "string"},
            "backup_codes": {"type": "string"},
            "daily_post_cap": {"type": "integer"},
            "min_gap_hours": {"type": "number"},
            "active_hour_start": {"type": "integer"},
            "active_hour_end": {"type": "integer"},
            "timezone": {"type": "string"},
            "caption_profile": {"type": "string"},
            "hold_for_review": {"type": "boolean"},
            "login_surface": {"type": "string"},
        },
        ["account_id"],
    ),
    schema(
        "create_proxy",
        "Добавить прокси. Нужны label и url.",
        {
            "label": {"type": "string"},
            "url": {"type": "string"},
            "country": {"type": "string"},
            "timezone": {"type": "string"},
            "notes": {"type": "string"},
        },
        ["label", "url"],
    ),
    schema(
        "create_proxies",
        "Создать несколько прокси одним вызовом (до 20). items — JSON-массив объектов с label и url.",
        {
            "items": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "url": {"type": "string"},
                        "country": {"type": "string"},
                        "timezone": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
            },
        },
        ["items"],
    ),
    schema(
        "update_proxy",
        "Изменить URL/страну существующего прокси по label.",
        {
            "label": {"type": "string"},
            "url": {"type": "string"},
            "country": {"type": "string"},
            "timezone": {"type": "string"},
            "notes": {"type": "string"},
        },
        ["label"],
    ),
    schema(
        "attach_proxy",
        "Привязать существующий прокси к аккаунту.",
        {"account_id": {"type": "integer"}, "proxy_label": {"type": "string"}},
        ["account_id", "proxy_label"],
    ),
    schema(
        "page_guide",
        "Секция справочника про другую страницу панели (не текущую).",
        {"page": {"type": "string"}},
        ["page"],
    ),
    schema(
        "ask_operator",
        "Спросить оператора, когда не хватает обязательных полей. Не выдумывай значения. После ответов — create/update.",
        {
            "questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Короткие вопросы: чего не хватает",
            },
            "reason": {"type": "string", "description": "Зачем нужны ответы"},
        },
        ["questions"],
    ),
    schema(
        "diagnose",
        "Стек, постинг, вход и прокси: воркер, блоки posting / login / proxies (очередь, сессии, DiagnosticRun, geo, hints), Ollama, ошибки БД, хвост data/app.log. Вызови, когда сломался постинг, вход, прокси или стек. Не выдумывай, если лога нет.",
        {"tail": {"type": "integer", "description": "сколько строк app.log, по умолчанию 24"}},
        [],
    ),
    schema(
        "docker_logs",
        "Логи docker compose этого репозитория. Сервисы: reels-api, reels-worker, reels-ollama, reels-frontend, reels-ollama-pull. Если CLI нет — читает Engine API через docker.sock. Если Docker нет — available false, не выдумывай логи.",
        {
            "service": {
                "type": "string",
                "enum": [
                    "reels-api",
                    "reels-worker",
                    "reels-ollama",
                    "reels-frontend",
                    "reels-ollama-pull",
                ],
            },
            "tail": {"type": "integer"},
        },
        ["service"],
    ),
    schema(
        "approve_job",
        "Одобрить публикацию, которая ждёт проверки (awaiting_review).",
        {"job_id": {"type": "integer"}},
        ["job_id"],
    ),
    schema(
        "cancel_job",
        "Отменить публикацию в очереди. Без confirm=true сначала спроси оператора (вернётся ask).",
        {"job_id": {"type": "integer"}, "confirm": {"type": "boolean"}},
        ["job_id"],
    ),
    schema(
        "retry_job",
        "Повторить упавшую или отменённую публикацию.",
        {"job_id": {"type": "integer"}},
        ["job_id"],
    ),
    schema(
        "start_worker",
        "Запустить воркер панели. Если уже крутится Docker/терминал — вернёт skipped, не ошибку: очередь должна ехать, второй процесс не нужен.",
        {},
        [],
    ),
    schema(
        "stop_worker",
        "Остановить воркер, который запустила панель. Без confirm=true сначала спроси оператора.",
        {"confirm": {"type": "boolean"}},
        [],
    ),
    schema(
        "take_backup",
        "Снять копию базы, как кнопка «Снять копию» на Обслуживании.",
        {},
        [],
    ),
    schema(
        "test_proxy",
        "Проверить один прокси по метке (как «Проверить» в списке).",
        {"proxy_label": {"type": "string"}},
        ["proxy_label"],
    ),
    schema(
        "test_connection",
        "Проверить прокси и сессию. Instagram: cookies/sessionid. YouTube/TikTok: Playwright state на диске, без instagram_reachable.",
        {
            "account_id": {"type": "integer"},
            "probe_mobile": {"type": "boolean"},
        },
        ["account_id"],
    ),
    schema(
        "export_cookies",
        "Скачать cookies аккаунта в браузере оператора (как кнопка «Скачать cookies»). format: json или txt.",
        {"account_id": {"type": "integer"}, "format": {"type": "string"}},
        ["account_id"],
    ),
    schema(
        "export_fingerprint",
        "Скачать Android fingerprint Instagram (instagrapi). Только Instagram.",
        {"account_id": {"type": "integer"}, "format": {"type": "string"}},
        ["account_id"],
    ),
    schema(
        "export_playwright_state",
        "Скачать Playwright state.json (сессия Studio для YouTube/TikTok или web Instagram).",
        {"account_id": {"type": "integer"}, "format": {"type": "string"}},
        ["account_id"],
    ),
    schema(
        "import_cookies",
        "Импортировать cookies: JSON Dolphin/Playwright в data или path к файлу в проекте.",
        {
            "account_id": {"type": "integer"},
            "data": {"description": "JSON-массив Dolphin или объект state"},
            "path": {"type": "string"},
        },
        ["account_id"],
    ),
    schema(
        "import_fingerprint",
        "Импортировать device fingerprint Instagram. Только тот же отпечаток, не чужой. Не для YouTube/TikTok.",
        {"account_id": {"type": "integer"}, "data": {}, "path": {"type": "string"}},
        ["account_id"],
    ),
    schema(
        "get_session",
        "Instagram: sessionid и источник. YouTube/TikTok: наличие Playwright state и имена cookies (без значений).",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "test_proxies",
        "Проверить несколько прокси (как «Проверить» по очереди). Без labels — все.",
        {"labels": {"type": "array", "items": {"type": "string"}}},
        [],
    ),
    schema(
        "test_connections",
        "Проверить несколько аккаунтов (как «Проверить все»). Без account_ids — все с прокси.",
        {
            "account_ids": {"type": "array", "items": {"type": "integer"}},
            "probe_mobile": {"type": "boolean"},
        },
        [],
    ),
    schema(
        "publish_now",
        "Проверить подключение аккаунта и сразу поставить ролик из библиотеки. Нет ролика — ask.",
        {
            "account_id": {"type": "integer"},
            "filename": {"type": "string"},
            "asset_id": {"type": "integer"},
            "title": {"type": "string"},
            "caption": {"type": "string"},
            "caption_template": {"type": "string"},
            "description": {"type": "string"},
            "tags": {"type": "string"},
            "post_type": {"type": "string"},
            "when": {"type": "string"},
        },
        ["account_id"],
    ),
    schema(
        "first_login",
        "Автовход Playwright только для Instagram. YouTube/TikTok — cookies или браузер в UI.",
        {"account_id": {"type": "integer"}, "login_surface": {"type": "string"}},
        ["account_id"],
    ),
    schema(
        "mint_mobile_session",
        "Выпустить mobile-сессию instagrapi. Только Instagram.",
        {"account_id": {"type": "integer"}},
        ["account_id"],
    ),
    schema(
        "retry_render",
        "Повторить упавший рендер. auto снова идёт по цепочке.",
        {"job_id": {"type": "integer"}},
        ["job_id"],
    ),
    schema(
        "cancel_render",
        "Отменить рендер в очереди. Без confirm=true сначала спроси оператора.",
        {"job_id": {"type": "integer"}, "confirm": {"type": "boolean"}},
        ["job_id"],
    ),
    schema(
        "create_render",
        "Поставить рендер. Промпт обязателен. backend по умолчанию auto (цепочка). Нет промпта — ask. Если ни один движок не жив — ошибка healthcheck как есть.",
        {
            "prompt": {"type": "string"},
            "account_id": {"type": "integer"},
            "backend": {"type": "string"},
            "duration_s": {"type": "number"},
            "negative_prompt": {"type": "string"},
        },
        [],
    ),
    schema(
        "compose",
        "Склеить клипы из библиотеки (минимум два clip_ids). Нет id — ask.",
        {
            "clip_ids": {"type": "array", "items": {"type": "integer"}},
            "audio_asset_id": {"type": "integer"},
            "account_id": {"type": "integer"},
            "post_title": {"type": "string"},
        },
        [],
    ),
    schema(
        "cancel_composition",
        "Отменить склейку в очереди. Без confirm=true сначала спроси оператора.",
        {"job_id": {"type": "integer"}, "confirm": {"type": "boolean"}},
        ["job_id"],
    ),
    schema(
        "retry_composition",
        "Повторить упавшую склейку.",
        {"job_id": {"type": "integer"}},
        ["job_id"],
    ),
    schema(
        "check_source",
        "Проверить источник брифа аккаунта (как кнопка Check).",
        {"source_id": {"type": "integer"}},
        ["source_id"],
    ),
    schema(
        "refresh_stats",
        "Обновить статистику опубликованного ролика.",
        {"publication_id": {"type": "integer"}},
        ["publication_id"],
    ),
]


BROWSER_TOOL_NAMES = frozenset(
    {
        "start_browser",
        "browser_status",
        "save_browser_session",
        "submit_browser_code",
        "wait_render",
        "wait_plan",
    }
)

BROWSER_TOOLS = [
    schema(
        "start_browser",
        "Запустить живой Playwright (VNC) для Instagram, YouTube Studio или TikTok Studio. Нужны аккаунт и прокси.",
        {
            "account_id": {"type": "integer"},
            "username": {"type": "string"},
            "login_surface": {"type": "string"},
        },
        [],
    ),
    schema(
        "browser_status",
        "Статус живого Playwright-сеанса аккаунта.",
        {"account_id": {"type": "integer"}, "username": {"type": "string"}},
        [],
    ),
    schema(
        "save_browser_session",
        "Сохранить cookies живого браузера в state.json (Instagram — ещё sessionid).",
        {"account_id": {"type": "integer"}, "username": {"type": "string"}},
        [],
    ),
    schema(
        "submit_browser_code",
        "Передать код 2FA/подтверждения в живой браузер. Нет кода — ask.",
        {
            "code": {"type": "string"},
            "account_id": {"type": "integer"},
            "username": {"type": "string"},
        },
        [],
    ),
    schema(
        "wait_render",
        "Ждать, пока рендер станет done/failed. Вызови после create_render, прежде чем публиковать.",
        {
            "job_id": {"type": "integer"},
            "timeout_s": {"type": "number"},
            "poll_s": {"type": "number"},
        },
        ["job_id"],
    ),
    schema(
        "wait_plan",
        "Ждать, пока PlanJob станет done/failed. Вызови после plan_account, затем wait_render по generation_ids.",
        {
            "plan_id": {"type": "integer"},
            "timeout_s": {"type": "number"},
            "poll_s": {"type": "number"},
        },
        ["plan_id"],
    ),
]


def tool_specs(*, allow_browser: bool = False) -> list[dict[str, Any]]:
    if allow_browser:
        return [*TOOLS, *BROWSER_TOOLS]
    return list(TOOLS)


class AssistantError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _prepare_runtime(settings: Settings) -> None:
    """Start Ollama / the model pull so the operator never has to."""
    from app.services.gpu_slot import video_busy

    if video_busy(settings):
        raise AssistantError(
            "GPU занята рендером видео — чат выгружен, чтобы хватило памяти. "
            "Напишите снова, когда ролик доедет.",
            retryable=True,
        )
    current = probe(settings)
    if not current.reachable:
        if not settings.ollama_autostart:
            raise AssistantError(
                f"модель не отвечает по адресу {settings.agent_base_url}",
                retryable=True,
            )
        try:
            status = ollama_control.ensure_started(pull=False)
        except ollama_control.OllamaProblem as exc:
            raise AssistantError(str(exc), retryable=True) from exc
        if not status.reachable:
            raise AssistantError("модель не отвечает — Ollama не поднялась", retryable=True)
        current = probe(settings)
    if current.reachable and not ollama_control.model_is_ready(current.models):
        ollama_control.pull_in_background()
        raise AssistantError(
            "модель ещё скачивается. Напишите ещё раз через минуту — это доедет само.",
            retryable=True,
        )


@dataclass
class Answer:
    reply: str
    opened: Opened | None = None
    used: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)
    created: dict[str, list[int]] = field(default_factory=lambda: {"accounts": [], "proxies": []})
    thinking: str = ""
    cut: str = ""


def run_tool(
    db: Session,
    name: str,
    args: dict[str, Any],
    *,
    settings: Settings | None = None,
    token: str | None = None,
    allow_browser: bool = False,
    viewer_role: str | None = None,
) -> tuple[Any, Opened | None]:
    if name == "overview":
        return tools.overview(db), None
    if name == "list_accounts":
        return tools.list_accounts(db), None
    if name == "list_posts":
        return (
            tools.list_posts(
                db,
                status=args.get("status"),
                account_id=args.get("account_id"),
                query=args.get("query"),
            ),
            None,
        )
    if name == "list_clips":
        return tools.list_clips(db, kind=args.get("kind") or "video", query=args.get("query")), None
    if name == "list_renders":
        return tools.list_renders(db, status=args.get("status")), None
    if name == "list_render_backends":
        return tools.list_render_backends(), None
    if name == "list_compositions":
        return tools.list_compositions(db, status=args.get("status")), None
    if name == "list_questions":
        return tools.list_questions(db, account_id=_optional_id(args, "account_id")), None
    if name == "list_sources":
        return tools.list_sources(db, _row_id(args, "account_id")), None
    if name == "list_presets":
        return tools.list_presets(db), None
    if name == "list_plans":
        return tools.list_plans(db, account_id=_optional_id(args, "account_id")), None
    if name == "apply_preset":
        return tools.apply_preset(db, _row_id(args, "account_id"), str(args.get("name") or "")), None
    if name == "list_proxies":
        return tools.list_proxies(db), None
    if name == "list_errors":
        return tools.list_errors(db), None
    if name == "job_logs":
        payload, opened = tools.job_logs(db, _row_id(args, "job_id"))
        return payload, opened
    if name == "account_logs":
        payload, opened = tools.account_logs(
            db,
            _row_id(args, "account_id"),
            kind=args.get("kind"),
            tail=int(args.get("tail") or 40),
        )
        return payload, opened
    if name == "open_page":
        opened = tools.open_page(args.get("page", ""))
        return {"открыто": opened.what}, opened
    if name == "open_clip":
        opened = tools.open_clip(db, _row_id(args, "asset_id"))
        return {"открыто": opened.what}, opened
    if name == "open_post":
        opened = tools.open_post(db, _row_id(args, "job_id"))
        return {"открыто": opened.what}, opened
    if name == "open_account":
        opened = tools.open_account(db, _row_id(args, "account_id"))
        return {"открыто": opened.what}, opened
    if name == "screenshot_page":
        opened = tools.screenshot_page(args.get("page", ""), settings=settings, db=db, token=token)
        return {"открыто": opened.what, "снимок": "готов"}, opened
    if name == "plan_account":
        return (
            tools.plan_account(
                db,
                _row_id(args, "account_id"),
                count=int(args.get("count") or 5),
                week=bool(args.get("week")),
                duration_s=_optional_number(args, "duration_s"),
                auto_schedule=_optional_bool(args, "auto_schedule"),
            ),
            None,
        )
    if name == "preview_plan":
        return (
            tools.preview_plan(
                db,
                _row_id(args, "account_id"),
                count=int(args.get("count") or 5),
                duration_s=_optional_number(args, "duration_s"),
            ),
            None,
        )
    if name == "enqueue_publish":
        return (
            tools.enqueue_publish(
                db,
                account_id=_row_id(args, "account_id"),
                filename=args.get("filename"),
                asset_id=_optional_id(args, "asset_id"),
                title=str(args.get("title") or ""),
                caption=_optional_text(args, "caption"),
                caption_template=_optional_text(args, "caption_template"),
                description=_optional_text(args, "description"),
                tags=_optional_text(args, "tags"),
                post_type=_optional_text(args, "post_type"),
                when=args.get("when"),
            ),
            None,
        )
    if name == "reschedule_job":
        return tools.reschedule_job(db, _row_id(args, "job_id"), when=args.get("when")), None
    if name == "pause_account":
        return tools.pause_account(db, _row_id(args, "account_id")), None
    if name == "resume_account":
        return tools.resume_account(db, _row_id(args, "account_id")), None
    if name == "answer_question":
        return tools.answer_question(db, _row_id(args, "question_id"), str(args.get("answer") or "")), None
    if name == "add_source":
        return (
            tools.add_source(
                db,
                _row_id(args, "account_id"),
                str(args.get("value") or ""),
                kind=str(args.get("kind") or "url"),
            ),
            None,
        )
    if name == "account_details":
        return tools.account_details(db, _row_id(args, "account_id")), None
    if name == "list_operators":
        return tools.list_operators(db, as_owner=viewer_role != "operator"), None
    if name == "list_project_files":
        return tools.list_project_files(_optional_text(args, "path")), None
    if name == "read_project_file":
        return tools.read_project_file(str(args.get("path") or "")), None
    if name == "create_account":
        return (
            tools.create_account(
                db,
                username=str(args.get("username") or ""),
                proxy_label=str(args.get("proxy_label") or ""),
                password=str(args.get("password") or ""),
                platform=str(args.get("platform") or "instagram"),
                totp_seed=_optional_text(args, "totp_seed"),
                session_id=_optional_text(args, "session_id"),
                email=_optional_text(args, "email"),
                email_password=_optional_text(args, "email_password"),
                brief=_optional_text(args, "brief"),
                notes=_optional_text(args, "notes"),
                account_line=_optional_text(args, "account_line"),
                login_identifier=_optional_text(args, "login_identifier"),
                backup_codes=_optional_text(args, "backup_codes"),
            ),
            None,
        )
    if name == "create_accounts":
        return tools.create_accounts(db, args.get("items")), None
    if name == "create_proxies":
        return tools.create_proxies(db, args.get("items")), None
    if name == "update_account":
        return (
            tools.update_account(
                db,
                _row_id(args, "account_id"),
                username=_optional_text(args, "username"),
                password=_optional_text(args, "password"),
                totp_seed=_optional_text(args, "totp_seed"),
                session_id=_optional_text(args, "session_id"),
                email=_optional_text(args, "email"),
                email_password=_optional_text(args, "email_password"),
                brief=_optional_text(args, "brief"),
                notes=_optional_text(args, "notes"),
                proxy_label=_optional_text(args, "proxy_label"),
                login_identifier=_optional_text(args, "login_identifier"),
                backup_codes=_optional_text(args, "backup_codes"),
                daily_post_cap=_optional_int(args, "daily_post_cap"),
                min_gap_hours=_optional_number(args, "min_gap_hours"),
                active_hour_start=_optional_int(args, "active_hour_start"),
                active_hour_end=_optional_int(args, "active_hour_end"),
                timezone=_optional_text(args, "timezone"),
                caption_profile=_optional_text(args, "caption_profile"),
                hold_for_review=_optional_bool(args, "hold_for_review"),
                login_surface=_optional_text(args, "login_surface"),
            ),
            None,
        )
    if name == "create_proxy":
        return (
            tools.create_proxy(
                db,
                label=str(args.get("label") or ""),
                url=str(args.get("url") or ""),
                country=_optional_text(args, "country"),
                timezone=_optional_text(args, "timezone"),
                notes=_optional_text(args, "notes"),
            ),
            None,
        )
    if name == "update_proxy":
        return (
            tools.update_proxy(
                db,
                str(args.get("label") or ""),
                url=_optional_text(args, "url"),
                country=_optional_text(args, "country"),
                timezone=_optional_text(args, "timezone"),
                notes=_optional_text(args, "notes"),
            ),
            None,
        )
    if name == "attach_proxy":
        return (
            tools.attach_proxy(db, _row_id(args, "account_id"), str(args.get("proxy_label") or "")),
            None,
        )
    if name == "page_guide":
        return handbook_page_section(str(args.get("page") or "")), None
    if name == "ask_operator":
        return _ask_operator(args), None
    if name == "diagnose":
        tail = args.get("tail")
        return tools.diagnose(db, tail=int(tail or tools.DIAGNOSE_LOG_TAIL)), None
    if name == "docker_logs":
        tail = args.get("tail")
        return tools.docker_logs(str(args.get("service") or ""), tail=int(tail or tools.LOG_TAIL)), None
    if name == "approve_job":
        return tools.approve_job(db, _row_id(args, "job_id")), None
    if name == "cancel_job":
        return tools.cancel_job(db, _row_id(args, "job_id"), confirm=args.get("confirm")), None
    if name == "retry_job":
        return tools.retry_job(db, _row_id(args, "job_id")), None
    if name == "start_worker":
        return tools.start_worker(db), None
    if name == "stop_worker":
        return tools.stop_worker(db, confirm=args.get("confirm")), None
    if name == "take_backup":
        return tools.take_backup(), None
    if name == "test_proxy":
        return tools.test_proxy(db, str(args.get("proxy_label") or "")), None
    if name == "test_connection":
        return (
            tools.test_connection(
                db,
                _row_id(args, "account_id"),
                probe_mobile=bool(args.get("probe_mobile")),
            ),
            None,
        )
    if name == "export_cookies":
        return tools.export_cookies(
            db, _row_id(args, "account_id"), format=str(args.get("format") or "json")
        )
    if name == "export_fingerprint":
        return tools.export_fingerprint(
            db, _row_id(args, "account_id"), format=str(args.get("format") or "json")
        )
    if name == "export_playwright_state":
        return tools.export_playwright_state(
            db, _row_id(args, "account_id"), format=str(args.get("format") or "json")
        )
    if name == "import_cookies":
        return (
            tools.import_cookies(
                db,
                _row_id(args, "account_id"),
                data=args.get("data"),
                path=_optional_text(args, "path"),
            ),
            None,
        )
    if name == "import_fingerprint":
        return (
            tools.import_fingerprint(
                db,
                _row_id(args, "account_id"),
                data=args.get("data"),
                path=_optional_text(args, "path"),
            ),
            None,
        )
    if name == "get_session":
        return tools.get_session(db, _row_id(args, "account_id")), None
    if name == "test_proxies":
        return tools.test_proxies(db, args.get("labels")), None
    if name == "test_connections":
        return (
            tools.test_connections(
                db,
                args.get("account_ids"),
                probe_mobile=bool(args.get("probe_mobile")),
            ),
            None,
        )
    if name == "publish_now":
        return (
            tools.publish_now(
                db,
                _row_id(args, "account_id"),
                filename=_optional_text(args, "filename"),
                asset_id=_optional_id(args, "asset_id"),
                title=str(args.get("title") or ""),
                caption=_optional_text(args, "caption"),
                caption_template=_optional_text(args, "caption_template"),
                description=_optional_text(args, "description"),
                tags=_optional_text(args, "tags"),
                post_type=_optional_text(args, "post_type"),
                when=args.get("when"),
            ),
            None,
        )
    if name == "first_login":
        return (
            tools.first_login(
                db,
                _row_id(args, "account_id"),
                login_surface=_optional_text(args, "login_surface"),
            ),
            None,
        )
    if name == "mint_mobile_session":
        return tools.mint_mobile_session(db, _row_id(args, "account_id")), None
    if name == "retry_render":
        return tools.retry_render(db, _row_id(args, "job_id")), None
    if name == "cancel_render":
        return tools.cancel_render(db, _row_id(args, "job_id"), confirm=args.get("confirm")), None
    if name == "create_render":
        return (
            tools.create_render(
                db,
                prompt=_optional_text(args, "prompt"),
                account_id=_optional_id(args, "account_id"),
                backend=_optional_text(args, "backend"),
                duration_s=_optional_number(args, "duration_s"),
                negative_prompt=str(args.get("negative_prompt") or ""),
            ),
            None,
        )
    if name == "compose":
        return (
            tools.compose(
                db,
                clip_ids=args.get("clip_ids"),
                audio_asset_id=_optional_id(args, "audio_asset_id"),
                account_id=_optional_id(args, "account_id"),
                post_title=str(args.get("post_title") or ""),
            ),
            None,
        )
    if name == "cancel_composition":
        return tools.cancel_composition(db, _row_id(args, "job_id"), confirm=args.get("confirm")), None
    if name == "retry_composition":
        return tools.retry_composition(db, _row_id(args, "job_id")), None
    if name == "check_source":
        return tools.check_source(db, _row_id(args, "source_id")), None
    if name == "refresh_stats":
        return tools.refresh_stats(db, _row_id(args, "publication_id")), None
    if name in BROWSER_TOOL_NAMES and not allow_browser:
        raise ToolError(f"{name} только в POST /api/assistant/run (не нижний чат)")
    if name == "start_browser":
        return (
            tools.start_browser(
                db,
                account_id=_optional_id(args, "account_id"),
                username=_optional_text(args, "username"),
                login_surface=_optional_text(args, "login_surface"),
            ),
            None,
        )
    if name == "browser_status":
        return (
            tools.browser_status(
                db,
                account_id=_optional_id(args, "account_id"),
                username=_optional_text(args, "username"),
            ),
            None,
        )
    if name == "save_browser_session":
        return (
            tools.save_browser_session(
                db,
                account_id=_optional_id(args, "account_id"),
                username=_optional_text(args, "username"),
            ),
            None,
        )
    if name == "submit_browser_code":
        return (
            tools.submit_browser_code(
                db,
                code=_optional_text(args, "code"),
                account_id=_optional_id(args, "account_id"),
                username=_optional_text(args, "username"),
            ),
            None,
        )
    if name == "wait_render":
        timeout = _optional_number(args, "timeout_s")
        poll = _optional_number(args, "poll_s")
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout_s"] = timeout
        if poll is not None:
            kwargs["poll_s"] = poll
        return tools.wait_render(db, _row_id(args, "job_id"), **kwargs), None
    if name == "wait_plan":
        timeout = _optional_number(args, "timeout_s")
        poll = _optional_number(args, "poll_s")
        kwargs = {}
        if timeout is not None:
            kwargs["timeout_s"] = timeout
        if poll is not None:
            kwargs["poll_s"] = poll
        return tools.wait_plan(db, _row_id(args, "plan_id"), **kwargs), None
    raise ToolError(f"инструмента {name!r} нет")


def _row_id(args: dict[str, Any], key: str) -> int:
    raw = args.get(key)
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ToolError(f"{key} должен быть числом, а пришло {raw!r}") from None


def _optional_id(args: dict[str, Any], key: str) -> int | None:
    if args.get(key) in (None, "", []):
        return None
    return _row_id(args, key)


def _optional_text(args: dict[str, Any], key: str) -> str | None:
    if key not in args or args.get(key) in (None, []):
        return None
    return str(args.get(key))


def _optional_int(args: dict[str, Any], key: str) -> int | None:
    if args.get(key) in (None, "", []):
        return None
    try:
        return int(str(args.get(key)).strip())
    except (TypeError, ValueError):
        raise ToolError(f"{key} должен быть числом, а пришло {args.get(key)!r}") from None


def _optional_number(args: dict[str, Any], key: str) -> float | None:
    if args.get(key) in (None, "", []):
        return None
    try:
        return float(str(args.get(key)).strip())
    except (TypeError, ValueError):
        raise ToolError(f"{key} должен быть числом, а пришло {args.get(key)!r}") from None


def _optional_bool(args: dict[str, Any], key: str) -> bool | None:
    if key not in args or args.get(key) in (None, ""):
        return None
    raw = args.get(key)
    if isinstance(raw, bool):
        return raw
    word = tools.one_word(raw)
    if word in {"true", "1", "yes", "да"}:
        return True
    if word in {"false", "0", "no", "нет"}:
        return False
    raise ToolError(f"{key} должен быть true/false, а пришло {raw!r}")


def _ask_operator(args: dict[str, Any]) -> dict[str, Any]:
    raw = args.get("questions")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise ToolError("questions должен быть списком строк")
    questions = [str(q).strip() for q in raw if str(q).strip()]
    if not questions:
        raise ToolError("нужен хотя бы один вопрос")
    return {
        "ask": True,
        "questions": questions,
        "why": str(args.get("reason") or "").strip(),
    }


@dataclass
class Step:
    kind: str
    text: str = ""
    questions: list[str] = field(default_factory=list)
    name: str = ""


def describe(name: str, args: dict[str, Any]) -> str:
    query = args.get("query")
    if name == "list_clips":
        audio = tools.one_word(args.get("kind") or "video") == "audio"
        if query:
            return f"ищу «{query}» среди {'саундтреков' if audio else 'клипов'}"
        return f"смотрю {'саундтреки' if audio else 'клипы'}"
    if name == "list_posts":
        status = args.get("status")
        if query:
            return f"ищу «{query}» среди публикаций"
        if status:
            return f"смотрю публикации: {tools.one_word(status)}"
        return "смотрю публикации"
    if name == "list_renders":
        status = args.get("status")
        if status:
            return f"смотрю рендеры: {tools.one_word(status)}"
        return "смотрю рендеры"
    if name == "list_render_backends":
        return "смотрю движки рендера"
    if name == "list_compositions":
        status = args.get("status")
        if status:
            return f"смотрю склейки: {tools.one_word(status)}"
        return "смотрю склейки"
    return {
        "overview": "считаю, сколько чего есть",
        "list_accounts": "смотрю аккаунты",
        "account_details": "открываю карточку аккаунта",
        "list_proxies": "смотрю прокси",
        "list_questions": "смотрю вопросы агента",
        "list_sources": "смотрю источники",
        "list_presets": "смотрю пресеты",
        "list_plans": "смотрю прогоны плана",
        "apply_preset": "ставлю пресет",
        "list_errors": "смотрю ошибки",
        "list_operators": "смотрю доступы",
        "list_project_files": "смотрю файлы проекта",
        "read_project_file": "читаю файл проекта",
        "job_logs": "читаю логи задачи",
        "account_logs": "читаю логи аккаунта",
        "open_page": "открываю страницу",
        "open_clip": "открываю клип",
        "open_post": "открываю публикацию",
        "open_account": "открываю аккаунт",
        "screenshot_page": "делаю снимок страницы",
        "plan_account": "ставлю план",
        "preview_plan": "смотрю превью плана",
        "enqueue_publish": "ставлю публикацию в очередь",
        "reschedule_job": "переношу слот",
        "pause_account": "ставлю аккаунт на паузу",
        "resume_account": "снимаю аккаунт с паузы",
        "answer_question": "отвечаю на вопрос агента",
        "add_source": "добавляю источник",
        "create_account": "добавляю аккаунт",
        "create_accounts": "добавляю аккаунты",
        "update_account": "обновляю аккаунт",
        "create_proxy": "добавляю прокси",
        "create_proxies": "добавляю прокси",
        "update_proxy": "обновляю прокси",
        "attach_proxy": "привязываю прокси",
        "page_guide": "смотрю справочник страницы",
        "ask_operator": "уточняю у оператора",
        "diagnose": "смотрю постинг, вход и прокси",
        "docker_logs": "читаю логи docker",
        "approve_job": "одобряю публикацию",
        "cancel_job": "отменяю публикацию",
        "retry_job": "повторяю публикацию",
        "start_worker": "запускаю воркер",
        "stop_worker": "останавливаю воркер",
        "take_backup": "снимаю копию базы",
        "test_proxy": "проверяю прокси",
        "test_connection": "проверяю подключение аккаунта",
        "export_cookies": "выгружаю cookies",
        "export_fingerprint": "выгружаю fingerprint",
        "export_playwright_state": "выгружаю Playwright state",
        "import_cookies": "импортирую cookies",
        "import_fingerprint": "импортирую fingerprint",
        "get_session": "читаю сессию",
        "test_proxies": "проверяю прокси",
        "test_connections": "проверяю подключения",
        "publish_now": "проверяю и ставлю публикацию",
        "first_login": "делаю автовход",
        "mint_mobile_session": "выпускаю mobile-сессию",
        "retry_render": "повторяю рендер",
        "cancel_render": "отменяю рендер",
        "create_render": "ставлю рендер",
        "compose": "ставлю склейку",
        "cancel_composition": "отменяю склейку",
        "retry_composition": "повторяю склейку",
        "check_source": "проверяю источник",
        "refresh_stats": "обновляю статистику",
        "start_browser": "запускаю браузер",
        "browser_status": "смотрю браузер",
        "save_browser_session": "сохраняю сессию браузера",
        "submit_browser_code": "отправляю код в браузер",
        "wait_render": "жду рендер",
        "wait_plan": "жду план",
    }.get(name, f"вызываю {name}")


def _empty_created() -> dict[str, list[int]]:
    return {"accounts": [], "proxies": []}


def _row_ids(rows: Any) -> list[int]:
    ids: list[int] = []
    if not isinstance(rows, list):
        return ids
    for row in rows:
        if isinstance(row, dict) and row.get("id") is not None:
            try:
                ids.append(int(row["id"]))
            except (TypeError, ValueError):
                continue
    return ids


def note_created(name: str, result: Any, created: dict[str, list[int]]) -> None:
    if not isinstance(result, dict):
        return
    if name == "create_account" and result.get("id") is not None:
        try:
            created["accounts"].append(int(result["id"]))
        except (TypeError, ValueError):
            return
    elif name == "create_proxy" and result.get("id") is not None:
        try:
            created["proxies"].append(int(result["id"]))
        except (TypeError, ValueError):
            return
    elif name == "create_accounts":
        created["accounts"].extend(_row_ids(result.get("created")))
    elif name == "create_proxies":
        created["proxies"].extend(_row_ids(result.get("created")))


def stream(
    db: Session,
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    token: str | None = None,
    page: str | None = None,
    account_id: int | None = None,
    job_id: int | None = None,
    allow_browser: bool = False,
    rounds: int | None = None,
    viewer_role: str | None = None,
) -> Iterator[Step | Answer]:
    settings = settings or get_settings()
    if salad_configured(settings):
        base = ""
        try:
            ready = prepare_for_chat(settings)
            while True:
                try:
                    line = next(ready)
                except StopIteration as stop:
                    base = str(stop.value or "")
                    break
                yield Step(kind="status", text=line)
        except SaladProblem as exc:
            raise AssistantError(str(exc), retryable=True) from exc
        if not base:
            raise AssistantError("Salad не вернул адрес группы", retryable=True)
        settings = settings.model_copy(update={"agent_base_url": base})
    elif not settings.agent_base_url:
        raise AssistantError(
            "модель не настроена — задайте AGENT_BASE_URL, например http://localhost:11434/v1"
        )
    _prepare_runtime(settings)

    specs = tool_specs(allow_browser=allow_browser)
    limit = RUN_ROUNDS if allow_browser else ROUNDS
    if rounds is not None:
        limit = max(1, int(rounds))

    thread: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": system_message(
                page=page,
                account_id=account_id,
                job_id=job_id,
                allow_browser=allow_browser,
            ),
        },
        *_recent_talk(messages),
    ]
    opened: Opened | None = None
    used: list[str] = []
    thoughts: list[str] = []
    images: list[str] = []
    created = _empty_created()
    asked: set[tuple[str, str]] = set()

    with http_client(
        settings,
        timeout=settings.assistant_timeout_seconds,
        headers=_headers(settings),
    ) as client:
        for _ in range(limit):
            said: list[str] = []
            message = yield from _complete(client, settings, thread, said, tools=specs)
            round_thought = str(message.pop("thinking", "") or "")
            cut = str(message.pop("cut", "") or "")
            if round_thought:
                thoughts.append(round_thought)
            calls = message.get("tool_calls") or []
            if not calls:
                yield Answer(
                    reply=_clean(message.get("content") or "".join(said)),
                    opened=opened,
                    used=used,
                    images=images,
                    created=created,
                    thinking="\n".join(thoughts),
                    cut=cut,
                )
                return

            thread.append(message)
            for call in calls:
                name, args = _read_call(call)
                used.append(name)
                yield Step(kind="tool", text=describe(name, args), name=name)
                again = (name, json.dumps(args, sort_keys=True, default=str))
                if again in asked:
                    thread.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", ""),
                            "content": _render(
                                {
                                    "уже": "ты это уже спрашивал, ответ выше",
                                    "дальше": "ответь оператору тем, что уже знаешь",
                                }
                            ),
                        }
                    )
                    continue
                asked.add(again)
                try:
                    result, went = run_tool(
                        db,
                        name,
                        args,
                        settings=settings,
                        token=token,
                        allow_browser=allow_browser,
                        viewer_role=viewer_role,
                    )
                    if went is not None:
                        opened = went
                        if went.screenshot_url:
                            images.append(went.screenshot_url)
                            yield Step(kind="image", text=went.screenshot_url)
                except (ToolError, TypeError, ValueError, KeyError) as exc:
                    result = {"ошибка": str(exc)}
                else:
                    note_created(name, result, created)
                thread.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": _render(result),
                    }
                )
                if isinstance(result, dict) and result.get("ask"):
                    questions = list(result.get("questions") or [])
                    why = str(result.get("why") or "").strip()
                    yield Step(kind="ask", text=why, questions=questions)
                    yield Answer(
                        reply=why or "Нужны уточнения, чтобы продолжить.",
                        opened=opened,
                        used=used,
                        images=images,
                        asks=questions,
                        created=created,
                    )
                    return

    yield Answer(
        reply="Посмотрел, но не успел договорить — спросите про что-то одно.",
        opened=opened,
        used=used,
        images=images,
        created=created,
    )


def ask(
    db: Session,
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    token: str | None = None,
    page: str | None = None,
    account_id: int | None = None,
    job_id: int | None = None,
    allow_browser: bool = False,
    rounds: int | None = None,
    viewer_role: str | None = None,
) -> Answer:
    last: Answer | None = None
    for step in stream(
        db,
        messages,
        settings=settings,
        token=token,
        page=page,
        account_id=account_id,
        job_id=job_id,
        allow_browser=allow_browser,
        rounds=rounds,
        viewer_role=viewer_role,
    ):
        if isinstance(step, Answer):
            last = step
    assert last is not None, "the stream always ends in an Answer"
    return last


def _recent_talk(messages: list[dict[str, str]], limit: int = TALK_LIMIT) -> list[dict[str, str]]:
    talk = [m for m in messages if m.get("role") in ("user", "assistant")]
    return talk[-limit:]


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.agent_api_key:
        headers["Authorization"] = f"Bearer {settings.agent_api_key}"
    return headers


def _chat_body(
    settings: Settings,
    thread: list[dict[str, Any]],
    *,
    include_think: bool = True,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.agent_model,
        "messages": thread,
        "tools": tools if tools is not None else TOOLS,
        "temperature": 0.1,
        "max_tokens": 1024,
        "stream": True,
        # 32k context on a 24 GB card OOMs and Salad answers 520.
        "options": {"num_ctx": 8192},
    }
    if include_think:
        body["think"] = False
    return body


def _stream_cut(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "incomplete chunked" in text or "peer closed" in text


def _calls_ready(calls: dict[int, dict[str, Any]]) -> bool:
    if not calls:
        return False
    for call in calls.values():
        name, args = _read_call(call)
        raw = (call.get("function") or {}).get("arguments")
        if not name:
            return False
        if isinstance(raw, str) and raw.strip() and not args and raw.strip() not in {"{}", "null"}:
            return False
    return True


def _complete(
    client: httpx.Client,
    settings: Settings,
    thread: list[dict[str, Any]],
    said: list[str],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[Step]:
    from app.services.salad_idle import touch

    touch(settings)
    url = f"{settings.agent_base_url.rstrip('/')}/chat/completions"
    content: list[str] = []
    thought: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    thinking = Thinking()
    include_think = True
    retried = False
    cut = False
    while True:
        body = _chat_body(settings, thread, include_think=include_think, tools=tools)
        try:
            with client.stream("POST", url, json=body) as response:
                if response.status_code == 400 and include_think:
                    response.read()
                    include_think = False
                    continue
                if response.status_code in {520, 524} and not retried and not content and not thought and not calls:
                    response.read()
                    retried = True
                    continue
                _raise_for(response, url)
                for line in response.iter_lines():
                    delta = _delta(line)
                    if delta is None:
                        continue
                    for key in ("reasoning", "thinking"):
                        extra = delta.get(key)
                        if isinstance(extra, str) and extra:
                            thought.append(extra)
                            yield Step(kind="think", text=extra)
                    piece = delta.get("content") or ""
                    if piece:
                        for kind, text in thinking.feed(piece):
                            if kind == "think":
                                thought.append(text)
                                yield Step(kind="think", text=text)
                            else:
                                content.append(text)
                                said.append(text)
                                yield Step(kind="token", text=text)
                    for part in delta.get("tool_calls") or []:
                        _gather(calls, part)
        except httpx.RequestError as exc:
            # Salad's gateway closes the stream at ~100s. A cut before any
            # token is worth one retry: the weights are already in VRAM.
            for kind, text in thinking.flush():
                if kind == "think":
                    thought.append(text)
                    yield Step(kind="think", text=text)
                else:
                    content.append(text)
                    said.append(text)
                    yield Step(kind="token", text=text)
            if _calls_ready(calls):
                break
            if content or thought:
                cut = True
                break
            if not retried and _stream_cut(exc):
                retried = True
                content.clear()
                thought.clear()
                calls.clear()
                thinking = Thinking()
                continue
            if _stream_cut(exc):
                raise AssistantError(
                    "шлюз Salad оборвал ответ модели. Напишите ещё раз — она уже в памяти.",
                    retryable=True,
                ) from exc
            raise AssistantError(
                f"не дозвониться до модели по адресу {url}: {exc}",
                retryable=True,
            ) from exc
        else:
            for kind, text in thinking.flush():
                if kind == "think":
                    thought.append(text)
                    yield Step(kind="think", text=text)
                else:
                    content.append(text)
                    said.append(text)
                    yield Step(kind="token", text=text)
        break

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content),
        "thinking": "".join(thought).strip(),
        "cut": CUT_NOTE if cut else "",
    }
    if calls and not cut:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return message


OPEN_THINK = "<think>"
CLOSE_THINK = "</think>"
CUT_NOTE = "Ответ оборвался на шлюзе."


def _partial_suffix(text: str, marker: str) -> int:
    for size in range(len(marker) - 1, 0, -1):
        if text.endswith(marker[:size]):
            return size
    return 0


class Thinking:
    """Split a qwen-style `<think>` channel from the answer the operator sees."""

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False
        self.decided = False

    def feed(self, piece: str) -> list[tuple[str, str]]:
        if not piece:
            return []
        if self.decided and not self.inside:
            return [("token", piece)]
        self.buf += piece
        out: list[tuple[str, str]] = []
        while self.buf:
            if not self.inside and not self.decided:
                if self.buf.startswith(OPEN_THINK):
                    self.inside = True
                    self.decided = True
                    self.buf = self.buf[len(OPEN_THINK) :]
                    continue
                if OPEN_THINK.startswith(self.buf):
                    return out
                self.decided = True
                out.append(("token", self.buf))
                self.buf = ""
                return out
            if self.inside:
                end = self.buf.find(CLOSE_THINK)
                if end == -1:
                    hold = _partial_suffix(self.buf, CLOSE_THINK)
                    emit = self.buf[:-hold] if hold else self.buf
                    self.buf = self.buf[-hold:] if hold else ""
                    if emit:
                        out.append(("think", emit))
                    return out
                if end:
                    out.append(("think", self.buf[:end]))
                self.buf = self.buf[end + len(CLOSE_THINK) :]
                self.inside = False
                continue
            out.append(("token", self.buf))
            self.buf = ""
        return out

    def flush(self) -> list[tuple[str, str]]:
        if not self.buf:
            return []
        kind = "think" if self.inside or not self.decided and self.buf.startswith("<") else "token"
        text, self.buf = self.buf, ""
        self.inside = False
        self.decided = True
        return [(kind, text)]


def _raise_for(response: httpx.Response, url: str) -> None:
    if response.status_code < 400:
        return
    response.read()
    if response.status_code == 429:
        raise AssistantError("хост модели ограничил частоту", retryable=True)
    if response.status_code == 524:
        raise AssistantError(
            "шлюз Salad оборвал ответ по таймауту. Напишите ещё раз.",
            retryable=True,
        )
    if response.status_code == 520:
        raise AssistantError(
            "видеокарта оборвала запрос. Напишите ещё раз короче.",
            retryable=True,
        )
    if response.status_code >= 500:
        raise AssistantError(f"ошибка хоста модели {response.status_code}", retryable=True)
    raise AssistantError(f"модель отклонила запрос: {response.text[:200]}")


def _delta(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)["choices"][0]["delta"]
    except (KeyError, IndexError, ValueError):
        return None


def _gather(calls: dict[int, dict[str, Any]], part: dict[str, Any]) -> None:
    index = part.get("index", 0)
    call = calls.setdefault(
        index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
    )
    if part.get("id"):
        call["id"] = part["id"]
    fn = part.get("function") or {}
    if fn.get("name"):
        call["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        call["function"]["arguments"] += fn["arguments"]


def _read_call(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fn = call.get("function") or {}
    name = fn.get("name") or ""
    raw = fn.get("arguments")
    if isinstance(raw, dict):
        return name, raw
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return name, {}
    return name, parsed if isinstance(parsed, dict) else {}


def _render(result: Any) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_CHARS:
        return text
    return text[:MAX_TOOL_CHARS] + " …(cut)"


BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
HEADING = re.compile(r"^#{1,6}\s+", re.M)
LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def _clean(content: str) -> str:
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    content = LINK.sub(r"\1", content)
    content = BOLD.sub(lambda m: m.group(1) or m.group(2), content)
    content = ITALIC.sub(r"\1", content)
    content = HEADING.sub("", content)
    return content.strip()
