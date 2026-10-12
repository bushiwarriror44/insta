"""Content agent backed by any OpenAI-compatible chat endpoint.

One adapter covers the whole free tier of the ecosystem, because they all
speak `/chat/completions`:

* **Ollama or LM Studio on your own machine** — free outright, no quota,
  works offline. `AGENT_BASE_URL=http://localhost:11434/v1`, no key.
* **Gemini** — an OpenAI-compatible endpoint with a real free tier.
* **Groq, OpenRouter, Together, vLLM** — same shape, different host.

The task here is small and well specified, so a mid-size open model does
it perfectly well; the expensive part of this system is rendering video,
not planning it.

Structured output is requested as a JSON schema, which Ollama and most
hosts honour. Hosts that reject the schema are retried in plain JSON mode,
and the result is validated against the same Pydantic model either way —
so a model that free-styles its output fails validation instead of
reaching the database.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.agent.planner import (
    SYSTEM_PROMPT,
    AgentBackend,
    AgentError,
    ContentPlan,
    PlanRequest,
    PlanResult,
    Usage,
    build_prompt,
)
from app.config import Settings, get_settings
from app.services.http import client as http_client

#: Small models like to wrap JSON in a markdown fence despite instructions.
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class SchemaUnsupported(AgentError):
    """The host does not implement `json_schema` response formatting."""


class ShapeProblem(AgentError):
    """The reply arrived but was not the JSON we asked for."""


SCHEMA_INSTRUCTION = (
    "Reply with a single JSON object and nothing else — no prose, no "
    'markdown fence. Shape: {"ideas": [{"shots": [str], "title": str, '
    '"description": str, "tags": [str]}], "questions": [{"question": str, '
    '"why": str, "assumed": str}]}. "shots" holds one to four prompts in '
    'the order they play. Send "questions": [] when the brief settles '
    "everything."
)


def extract_json(text: str) -> dict[str, Any]:
    """Read the JSON object out of a reply, fence or no fence."""
    candidate = text.strip()
    fenced = FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Last resort: the outermost braces, for a model that added a sentence.
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ShapeProblem(
                f"{exc.msg} — модель не вернула JSON", retryable=True
            ) from exc
    raise ShapeProblem("модель не вернула JSON", retryable=True)


class OpenAICompatAgent(AgentBackend):
    name = "openai-compat"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def healthcheck(self) -> bool:
        # A local runtime needs no key; a hosted one does.
        return bool(self.settings.agent_base_url)

    def plan(self, request: PlanRequest) -> PlanResult:
        self.validate(request)
        if not self.healthcheck():
            raise AgentError("AGENT_BASE_URL не задан")

        prompt = build_prompt(request)
        messages = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{SCHEMA_INSTRUCTION}"},
            {"role": "user", "content": prompt},
        ]
        retried = False

        timeout = self.settings.agent_timeout_seconds
        with http_client(
            self.settings, timeout=timeout, headers=self._headers()
        ) as client:
            try:
                content, tokens = self._complete(client, messages, schema=True)
                plan = ContentPlan.model_validate(extract_json(content))
            except (SchemaUnsupported, ShapeProblem, ValidationError):
                # One retry in plain JSON mode: for a host that does not
                # implement json_schema, and for a smaller model that needs
                # a second attempt to get the shape right. A rate limit, a
                # dead host or a bad key propagates instead — retrying
                # those here would only hide them from the caller's backoff.
                retried = True
                content, tokens = self._complete(client, messages, schema=False)
                plan = self._validate(content)

        if not plan.ideas:
            raise AgentError("модель не вернула идей", retryable=True)

        sent, got = tokens
        return PlanResult(
            ideas=plan.ideas[: request.count],
            questions=plan.questions,
            prompt=prompt,
            raw=content,
            usage=Usage(
                model=self.settings.agent_model,
                input_tokens=sent,
                output_tokens=got,
                # A local runtime is free, and no free host publishes a
                # rate worth recording. Cost stays zero rather than made up.
                cost_usd=0.0,
                retried=retried,
            ),
        )

    @staticmethod
    def _validate(content: str) -> ContentPlan:
        try:
            return ContentPlan.model_validate(extract_json(content))
        except ValidationError as exc:
            raise AgentError(
                "план модели не подошёл под схему: "
                f"{exc.error_count()} проблем(ы)",
                retryable=True,
            ) from exc

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.agent_api_key:
            headers["Authorization"] = f"Bearer {self.settings.agent_api_key}"
        return headers

    def _body(self, messages: list[dict[str, str]], *, schema: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.settings.agent_model,
            "messages": messages,
            # Some creative spread, but not so much that the schema slips.
            "temperature": 0.8,
            "max_tokens": 4096,
        }
        if schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "content_plan",
                    "strict": True,
                    "schema": ContentPlan.model_json_schema(),
                },
            }
        else:
            body["response_format"] = {"type": "json_object"}
        return body

    def _complete(
        self, client: httpx.Client, messages: list[dict[str, str]], *, schema: bool
    ) -> tuple[str, tuple[int | None, int | None]]:
        """The reply text, and the token counts if the host reported any."""
        url = f"{self.settings.agent_base_url.rstrip('/')}/chat/completions"
        try:
            response = client.post(url, json=self._body(messages, schema=schema))
        except httpx.RequestError as exc:
            raise AgentError(f"не удалось достучаться до {url}: {exc}", retryable=True) from exc

        if response.status_code >= 400:
            self._raise(response, schema=schema)

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise ShapeProblem(
                f"неожиданная форма ответа от {url}", retryable=True
            ) from exc

        usage = payload.get("usage") or {}
        return content, (usage.get("prompt_tokens"), usage.get("completion_tokens"))

    @staticmethod
    def _raise(response: httpx.Response, *, schema: bool) -> None:
        detail = response.text[:200]
        if response.status_code in (401, 403):
            raise AgentError(f"хост модели отклонил ключ: {detail}")
        if response.status_code == 429:
            raise AgentError(f"хост модели ограничил частоту: {detail}", retryable=True)
        if response.status_code >= 500:
            raise AgentError(
                f"ошибка хоста модели {response.status_code}: {detail}", retryable=True
            )
        if schema:
            # Hosts that do not implement json_schema answer 400 here; the
            # caller falls back to plain JSON mode.
            raise SchemaUnsupported(f"хост отклонил схему: {detail}")
        raise AgentError(f"хост модели отклонил запрос: {detail}")
