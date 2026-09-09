"""Ollama probe as the maintenance page sees it."""

from unittest.mock import MagicMock, patch

import httpx

from app.config import Settings
from app.services import runtime


def make_settings(**over) -> Settings:
    return Settings(
        _env_file=None,
        agent_base_url=over.pop("agent_base_url", "http://localhost:11434/v1"),
        agent_model=over.pop("agent_model", "qwen3:8b"),
        **over,
    )


def replies(*payloads, status: int = 200) -> list[httpx.Response]:
    return [
        httpx.Response(status, json=p, request=httpx.Request("GET", "http://x"))
        for p in payloads
    ]


def answering(*gets) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.side_effect = replies(*gets)
    return client


def test_probe_reads_ollama_name_when_model_is_missing():
    tags = {"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]}
    running = {"models": [{"name": "qwen3:8b", "context_length": 8192, "size": 6_000_000}]}
    with patch("app.services.runtime.http_client", return_value=answering(tags, running)):
        seen = runtime.probe(make_settings())

    assert seen.reachable is True
    assert seen.models == ["llama3.2:3b", "qwen3:8b"]
    assert seen.loaded[0].name == "qwen3:8b"
    assert seen.context_of("qwen3:8b") == 8192
