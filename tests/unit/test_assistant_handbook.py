"""Assistant must answer from the handbook, not invent."""

from __future__ import annotations

from pathlib import Path

from app.assistant.chat import (
    DONT_KNOW,
    HANDBOOK_PATH,
    SYSTEM_PROMPT,
    handbook_page_section,
    load_handbook,
    system_message,
)

PAGE_HEADINGS = (
    "Панель",
    "Аккаунты",
    "Библиотека",
    "Агент",
    "Рендеры",
    "Календарь",
    "Активность",
    "Обслуживание",
    "Доступы",
    "Настройки",
)


def test_handbook_file_states_local_ollama_and_that_proxies_are_not_for_chat():
    text = HANDBOOK_PATH.read_text(encoding="utf-8")
    assert "Ollama" in text
    assert "localhost:11434" in text
    assert "не для модели" in text or "не для модели и не для Ollama" in text
    assert "прокси" in text.lower()
    for heading in PAGE_HEADINGS:
        assert f"## Страница: {heading}" in text
    assert "Добавить аккаунт" in text
    assert "Добавить прокси" in text
    assert "Сохранить аккаунт" in text
    assert "### Я сам" in text
    assert "create_accounts" in text
    assert "добавь три аккаунта" in text
    assert "export_cookies" in text
    assert "publish_now" in text
    assert "test_proxies" in text
    assert "instagrapi" in text
    assert "studio.youtube.com" in text
    assert "YouTube Data API" in text
    assert "export_playwright_state" in text
    assert "create_render" in text
    assert "list_render_backends" in text
    assert "backend=auto" in text
    assert "compose" in text
    assert "awaiting_review" in text
    assert "reels-worker" in text
    assert "hold_for_review" in text
    assert "assistant/run" in text
    assert "start_browser" in text
    assert "list_questions" in text
    assert "apply_preset" in text
    assert "wait_plan" in text
    assert "geo_mismatch" in text
    assert "account_logs" in text
    assert "Только в UI" in text
    assert "процитируй как есть" in text.lower() or "Процитируй как есть" in text
    assert "### Оплата" in text
    assert "0.05" in text
    assert "не касса" in text
    assert "Stop" in text
    assert "USDC" in text
    assert "Карточка «Оплата»" in text
    assert "GPU Salad" in text
    assert "/api/gpu" in text
    assert "Блокнот" in text
    assert "### Если постинг сломался" in text
    assert "queued_due" in text
    assert "job_logs" in text
    assert "start_worker" in text
    assert "### Если вход сломался" in text
    assert "### Если прокси сломался" in text
    assert "account_logs" in text
    assert "test_proxy" in text
    assert "first_login" in text
    posting = text.split("### Если постинг сломался", 1)[1].split("### ", 1)[0]
    assert "proxies_unhealthy" not in posting
    assert "Если вход сломался" in posting
    assert "Если прокси сломался" in posting
    assert "foreign_alive" in posting
    accesses = text.split("## Страница: Доступы", 1)[1].split("## ", 1)[0]
    assert "list_operators" in accesses
    assert "entry_path" in accesses
    assert "оператору" in accesses.lower()


def test_system_prompt_requires_the_dont_know_phrase():
    assert DONT_KNOW in SYSTEM_PROMPT
    assert "я не знаю ответ на этот вопрос" in SYSTEM_PROMPT
    assert "ask_operator" in SYSTEM_PROMPT
    assert "diagnose" in SYSTEM_PROMPT
    assert "Если постинг сломался" in SYSTEM_PROMPT
    assert "Если вход сломался" in SYSTEM_PROMPT
    assert "Если прокси сломался" in SYSTEM_PROMPT
    assert "account_logs" in SYSTEM_PROMPT
    assert "docker_logs" in SYSTEM_PROMPT
    assert "процитируй как есть" in SYSTEM_PROMPT
    assert "publish_now" in SYSTEM_PROMPT
    assert "create_render" in SYSTEM_PROMPT
    assert "compose" in SYSTEM_PROMPT
    assert "YouTube Data API" in SYSTEM_PROMPT
    assert "cookies" in SYSTEM_PROMPT


def test_system_message_includes_open_account_id(tmp_path: Path):
    book = tmp_path / "assistant-handbook.md"
    book.write_text("ядро localhost:11434\n\n## Страница: Аккаунты\nкнопка\n", encoding="utf-8")
    message = system_message(book, page="/accounts", account_id=7, job_id=12)
    assert "аккаунт id=7" in message
    assert "job_id=12" in message


def test_system_message_appends_handbook(tmp_path: Path):
    book = tmp_path / "assistant-handbook.md"
    book.write_text("якорь-ollama localhost:11434", encoding="utf-8")
    message = system_message(book)
    assert SYSTEM_PROMPT in message
    assert "якорь-ollama" in message
    assert "единственный источник правды" in message


def test_system_message_slices_current_page(tmp_path: Path):
    book = tmp_path / "assistant-handbook.md"
    book.write_text(
        "ядро localhost:11434\n\n"
        "## Страница: Аккаунты\nкнопка Добавить аккаунт\n\n"
        "## Страница: Доступы\nсекрет операторов и новый пароль\n",
        encoding="utf-8",
    )
    message = system_message(book, page="/accounts")
    assert "Добавить аккаунт" in message
    assert "Оператор сейчас на странице Аккаунты." in message
    assert "секрет операторов" not in message
    assert "ядро" in message

    other = handbook_page_section("operators", path=book)
    assert other["page"] == "Доступы"
    assert "секрет операторов" in other["guide"]


def test_system_message_accounts_slice_does_not_dump_operators():
    message = system_message(page="/accounts")
    assert "Добавить аккаунт" in message
    assert "## Страница: Аккаунты" in message
    assert "## Страница: Доступы" not in message
    assert "Сгенерировать пароль" not in message


def test_system_message_without_file_is_just_the_prompt(tmp_path: Path):
    missing = tmp_path / "nope.md"
    assert load_handbook(missing) == ""
    assert system_message(missing) == SYSTEM_PROMPT
