"""Telegram agent bot: auth, chain, vision parse."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.behavior.browser_vision import _parse_vision_json, vision_plan
from app.config import settings
from app.generation.registry import DEFAULT_CHAIN, parse_chain
from app.panel.settings_store import (
    revoke_telegram_chat,
    telegram_chat_is_allowed,
    verify_telegram_auth,
)


def test_default_chain_prefers_qubax_without_local():
    names = parse_chain()
    assert names[0] == "qubax"
    assert "local" not in DEFAULT_CHAIN


def test_verify_telegram_auth(app_env, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    db = app_env.SessionLocal()
    try:
        assert verify_telegram_auth(db, 12345, "secret-token") is True
        assert telegram_chat_is_allowed(db, 12345) is True
        assert verify_telegram_auth(db, 12345, "wrong") is False
        assert revoke_telegram_chat(db, 12345) is True
        assert telegram_chat_is_allowed(db, 12345) is False
    finally:
        db.close()


def test_parse_vision_json():
    action = _parse_vision_json('{"action":"click","x":120,"y":40,"reason":"login"}')
    assert action.action == "click"
    assert action.x == 120.0
    assert action.y == 40.0


@patch("app.behavior.browser_vision.httpx.Client")
def test_vision_plan_mock(mock_client_factory, monkeypatch):
    monkeypatch.setattr(settings, "agent_vision_enabled", True, raising=True)
    monkeypatch.setattr(settings, "agent_vision_model", "qwen2.5vl:7b", raising=True)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": '{"action":"done","reason":"logged in"}'}}]
    }
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_factory.return_value = mock_client
    action = vision_plan(b"fakepng", goal="test")
    assert action.action == "done"


def test_ask_reply_markup():
    from app.telegram.format import ASK_CALLBACK_PREFIX, ask_reply_markup

    markup = ask_reply_markup(["какой промпт?", "для кого"])
    assert markup is not None
    rows = markup["inline_keyboard"]
    assert len(rows) == 2
    assert rows[0][0]["callback_data"] == f"{ASK_CALLBACK_PREFIX}0"
    assert rows[1][0]["callback_data"] == f"{ASK_CALLBACK_PREFIX}1"


def test_handle_callback_query_sets_pending(app_env, monkeypatch):
    from app.telegram import bot as bot_module
    from app.telegram.sessions import session_store

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    db = app_env.SessionLocal()
    try:
        verify_telegram_auth(db, 777, "secret-token")
    finally:
        db.close()

    sent: list[str] = []
    monkeypatch.setattr(bot_module.api_client, "agent_bot_token", lambda cfg: "bot-token")
    monkeypatch.setattr(bot_module.api_client, "send_message", lambda *a, **k: sent.append(a[2]))
    monkeypatch.setattr(
        bot_module.api_client,
        "answer_callback_query",
        lambda *a, **k: None,
    )

    session = session_store.get(777)
    session.pending_ask_options = ["первый", "второй"]
    cfg = __import__("app.config", fromlist=["Settings"]).Settings(
        _env_file=None,
        telegram_agent_bot_token="bot-token",
        admin_token="secret-token",
    )
    bot_module.handle_callback_query(
        {
            "id": "cb1",
            "data": "tgask:1",
            "message": {"chat": {"id": 777}},
        },
        cfg=cfg,
    )
    assert session.pending_ask == "второй"
    assert sent and "второй" in sent[0]


def test_agent_run_submitted_to_executor(app_env, monkeypatch):
    from app.telegram import bot as bot_module

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    monkeypatch.setattr(settings, "telegram_agent_rate_limit_s", 0.0, raising=True)
    bot_module._last_message_at.clear()
    db = app_env.SessionLocal()
    try:
        verify_telegram_auth(db, 888, "secret-token")
    finally:
        db.close()

    submitted: list[tuple] = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append((fn, args))

    monkeypatch.setattr(bot_module, "_get_agent_executor", lambda cfg: FakeExecutor())
    monkeypatch.setattr(bot_module.api_client, "agent_bot_token", lambda cfg: "bot-token")
    monkeypatch.setattr(bot_module.api_client, "send_message", lambda *a, **k: 1)

    bot_module.session_store.get(888).busy = False
    cfg = __import__("app.config", fromlist=["Settings"]).Settings(
        _env_file=None,
        telegram_agent_bot_token="bot-token",
        admin_token="secret-token",
        telegram_agent_rate_limit_s=0.0,
    )
    bot_module.handle_update(
        {"message": {"chat": {"id": 888}, "text": "список аккаунтов"}},
        cfg=cfg,
    )
    assert len(submitted) == 1
    _fn, args = submitted[0]
    assert args[0] == 888
    assert args[1] == "список аккаунтов"
    assert bot_module.session_store.get(888).busy is True


def test_format_agent_event_message():
    from app.assistant.chat import Answer
    from app.telegram.bot import _format_agent_event_message

    msg = _format_agent_event_message(
        42,
        Answer(
            reply="готово",
            used=["list_accounts", "create_render"],
            asks=["какой промпт?"],
        ),
    )
    assert "chat 42" in msg
    assert "used=list_accounts,create_render" in msg
    assert "asks=1" in msg


def test_second_chat_submits_while_first_busy(app_env, monkeypatch):
    from app.telegram import bot as bot_module

    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    bot_module._last_message_at.clear()
    db = app_env.SessionLocal()
    try:
        verify_telegram_auth(db, 888, "secret-token")
        verify_telegram_auth(db, 999, "secret-token")
    finally:
        db.close()

    submitted: list[int] = []
    sent: list[tuple[int, str]] = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append(int(args[0]))

    monkeypatch.setattr(bot_module, "_get_agent_executor", lambda cfg: FakeExecutor())
    monkeypatch.setattr(bot_module.api_client, "agent_bot_token", lambda cfg: "bot-token")

    def fake_send(token, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return 1

    monkeypatch.setattr(bot_module.api_client, "send_message", fake_send)

    bot_module.session_store.get(888).busy = True
    bot_module.session_store.get(999).busy = False

    cfg = __import__("app.config", fromlist=["Settings"]).Settings(
        _env_file=None,
        telegram_agent_bot_token="bot-token",
        admin_token="secret-token",
        telegram_agent_rate_limit_s=0.0,
    )
    bot_module.handle_update(
        {"message": {"chat": {"id": 999}, "text": "задача B"}},
        cfg=cfg,
    )
    bot_module.handle_update(
        {"message": {"chat": {"id": 888}, "text": "задача A"}},
        cfg=cfg,
    )
    assert submitted == [999]
    busy_msgs = [t for cid, t in sent if cid == 888 and "предыдущее" in t.lower()]
    assert busy_msgs


def test_handle_update_unauthorized_sends_welcome(app_env, monkeypatch):
    from app.telegram import bot as bot_module

    sent: list[tuple[int, str]] = []

    def fake_send(token, chat_id, text, **kwargs):
        sent.append((chat_id, text))
        return 1

    monkeypatch.setattr(bot_module.api_client, "agent_bot_token", lambda cfg: "bot-token")
    monkeypatch.setattr(bot_module.api_client, "send_message", fake_send)
    cfg = __import__("app.config", fromlist=["Settings"]).Settings(
        _env_file=None,
        telegram_agent_bot_token="bot-token",
        admin_token="secret",
    )
    bot_module.handle_update(
        {"message": {"chat": {"id": 999}, "text": "сделай рендер"}},
        cfg=cfg,
    )
    assert sent
    chat_id, text = sent[0]
    assert chat_id == 999
    assert "/auth" in text


def test_handle_update_auth_command(monkeypatch, app_env):
    from app.telegram import bot as bot_module
    from app.config import settings

    sent: list[str] = []

    def fake_send(token, chat_id, text, **kwargs):
        sent.append(text)
        return 1

    monkeypatch.setattr(bot_module.api_client, "agent_bot_token", lambda cfg: "bot-token")
    monkeypatch.setattr(bot_module.api_client, "send_message", fake_send)
    monkeypatch.setattr(settings, "admin_token", "secret-token", raising=True)
    cfg = __import__("app.config", fromlist=["Settings"]).Settings(
        _env_file=None,
        telegram_agent_bot_token="bot-token",
        admin_token="secret-token",
    )
    bot_module.handle_update(
        {"message": {"chat": {"id": 555}, "text": "/auth secret-token"}},
        cfg=cfg,
    )
    assert any("привязан" in t or "Ок" in t for t in sent)


def test_telegram_runner_simple(app_env, monkeypatch):
    from app.telegram.runner import run_agent_task_simple

    monkeypatch.setattr(settings, "admin_token", "t", raising=True)

    class FakeAnswer:
        reply = "ok"
        asks = []
        used = ["list_accounts"]
        opened = None

    with patch("app.telegram.runner.ask", return_value=FakeAnswer()):
        db = app_env.SessionLocal()
        try:
            out = run_agent_task_simple(
                db,
                [{"role": "user", "content": "ping"}],
                allow_browser=True,
            )
        finally:
            db.close()
    assert out.reply == "ok"
