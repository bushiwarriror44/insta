"""LLM gateway: OpenAI-compatible proxy + minimal MCP, separate from panel auth."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import LlmGatewayDep, OwnerOrOpenDep, get_db
from app.api.schemas import (
    LlmGatewayCredentialsOut,
    LlmGatewayEnabledIn,
)
from app.config import settings
from app.panel.settings_store import (
    ensure_llm_gateway_token,
    llm_gateway_is_enabled,
    rotate_llm_gateway_token,
    set_llm_gateway_enabled,
)
from app.services.gateway_probe import ollama_reachable
from app.services.http import client as http_client
from app.services.llm_gateway_activity import list_activity, record_activity
from app.services.llm_gateway_errors import explain_llm_upstream_error

credentials_router = APIRouter(
    prefix="/api/llm-gateway",
    tags=["llm-gateway"],
    dependencies=[OwnerOrOpenDep],
)

proxy_router = APIRouter(prefix="/llm/v1", tags=["llm-proxy"])
mcp_router = APIRouter(tags=["mcp"])

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_INFO = {"name": "reels-salad", "version": "0.1.0"}


def _public_origin(request: Request) -> str:
    """Prefer forwarded headers when the panel sits behind a reverse proxy."""
    forwarded = (request.headers.get("x-forwarded-host") or "").strip()
    if forwarded:
        proto = (request.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
        host = forwarded.split(",")[0].strip()
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return ""


def _record(
    request: Request,
    *,
    channel: str,
    path: str,
    status: int,
    detail: str = "",
) -> None:
    record_activity(
        channel=channel,  # type: ignore[arg-type]
        method=request.method,
        path=path,
        client_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent") or "",
        status=status,
        detail=detail,
    )


def _mcp_json_block(*, mcp_url: str, api_key: str) -> str:
    payload = {
        "mcpServers": {
            "reels-salad": {
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {api_key}"},
            }
        }
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _credentials(request: Request, db: Session) -> LlmGatewayCredentialsOut:
    api_key = ensure_llm_gateway_token(db)
    origin = _public_origin(request)
    base_url = f"{origin}/llm/v1"
    mcp_url = f"{origin}/mcp"
    return LlmGatewayCredentialsOut(
        base_url=base_url,
        api_key=api_key,
        mcp_url=mcp_url,
        mcp_json=_mcp_json_block(mcp_url=mcp_url, api_key=api_key),
        model=settings.agent_model,
        upstream_ok=ollama_reachable(settings),
        enabled=llm_gateway_is_enabled(db),
        recent=list_activity(),
    )


@credentials_router.get("/credentials", response_model=LlmGatewayCredentialsOut)
def get_credentials(
    request: Request,
    db: Session = Depends(get_db),
) -> LlmGatewayCredentialsOut:
    return _credentials(request, db)


@credentials_router.post("/rotate", response_model=LlmGatewayCredentialsOut)
def rotate_credentials(
    request: Request,
    db: Session = Depends(get_db),
) -> LlmGatewayCredentialsOut:
    rotate_llm_gateway_token(db)
    return _credentials(request, db)


@credentials_router.post("/enabled", response_model=LlmGatewayCredentialsOut)
def set_enabled(
    payload: LlmGatewayEnabledIn,
    request: Request,
    db: Session = Depends(get_db),
) -> LlmGatewayCredentialsOut:
    set_llm_gateway_enabled(db, payload.enabled)
    return _credentials(request, db)


def _upstream_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = (settings.agent_api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _upstream_url(path: str) -> str:
    base = settings.agent_base_url.rstrip("/") + "/"
    return urljoin(base, path.lstrip("/"))


async def _forward(request: Request, path: str) -> tuple[Response, str]:
    url = _upstream_url(path)
    body = await request.body()
    headers = _upstream_headers()
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type

    timeout = httpx.Timeout(settings.agent_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.request(
                request.method,
                url,
                content=body if body else None,
                headers=headers,
            )
    except httpx.RequestError as exc:
        message = explain_llm_upstream_error(exc)
        return (
            JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": message,
                        "type": "proxy_error",
                        "code": "upstream_unreachable",
                    }
                },
            ),
            message,
        )

    excluded = {"content-encoding", "transfer-encoding", "content-length", "connection"}
    out_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in excluded
    }
    detail = ""
    if upstream.status_code >= 400:
        detail = f"Модель ответила HTTP {upstream.status_code}"
    return (
        Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=upstream.headers.get("content-type"),
        ),
        detail,
    )


@proxy_router.api_route(
    "/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def openai_proxy(
    path: str,
    request: Request,
    _key: str = LlmGatewayDep,
) -> Response:
    response, detail = await _forward(request, path)
    _record(
        request,
        channel="llm",
        path=f"/llm/v1/{path}",
        status=response.status_code,
        detail=detail,
    )
    return response


def _chat_completion(messages: list[dict[str, str]]) -> dict[str, Any]:
    url = _upstream_url("chat/completions")
    payload = {
        "model": settings.agent_model,
        "messages": messages,
        "stream": False,
    }
    try:
        with http_client(settings, timeout=settings.agent_timeout_seconds) as client:
            response = client.post(url, json=payload, headers=_upstream_headers())
    except httpx.RequestError as exc:
        raise RuntimeError(explain_llm_upstream_error(exc)) from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Модель ответила HTTP {response.status_code}")
    return response.json()


def _mcp_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _mcp_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _handle_mcp_method(method: str, params: dict[str, Any] | None, req_id: Any) -> dict[str, Any] | None:
    params = params or {}
    if method == "initialize":
        return _mcp_result(
            req_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": MCP_SERVER_INFO,
            },
        )
    if method == "notifications/initialized" or method.startswith("notifications/"):
        return None
    if method == "ping":
        return _mcp_result(req_id, {})
    if method == "tools/list":
        return _mcp_result(
            req_id,
            {
                "tools": [
                    {
                        "name": "chat",
                        "description": "Chat with the panel Salad/Ollama model (OpenAI-compatible).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "User message when messages are omitted",
                                },
                                "messages": {
                                    "type": "array",
                                    "description": "OpenAI-style chat messages",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "role": {"type": "string"},
                                            "content": {"type": "string"},
                                        },
                                        "required": ["role", "content"],
                                    },
                                },
                            },
                        },
                    }
                ]
            },
        )
    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if name != "chat":
            return _mcp_error(req_id, -32602, f"unknown tool: {name}")
        messages = arguments.get("messages")
        if not isinstance(messages, list) or not messages:
            prompt = str(arguments.get("prompt") or "").strip()
            if not prompt:
                return _mcp_error(req_id, -32602, "prompt or messages required")
            messages = [{"role": "user", "content": prompt}]
        try:
            data = _chat_completion(messages)
            text = (
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
                or ""
            )
        except Exception as exc:  # noqa: BLE001 — surface to MCP client
            return _mcp_result(
                req_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
        return _mcp_result(
            req_id,
            {"content": [{"type": "text", "text": text or "(empty)"}]},
        )
    if req_id is None:
        return None
    return _mcp_error(req_id, -32601, f"method not found: {method}")


@mcp_router.post("/mcp")
async def mcp_post(
    request: Request,
    _key: str = LlmGatewayDep,
) -> Response:
    try:
        payload = await request.json()
    except Exception:
        response: Response = JSONResponse(
            status_code=400,
            content=_mcp_error(None, -32700, "parse error"),
        )
        _record(request, channel="mcp", path="/mcp", status=response.status_code)
        return response

    if isinstance(payload, list):
        out: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            handled = _handle_mcp_method(
                str(item.get("method") or ""),
                item.get("params") if isinstance(item.get("params"), dict) else {},
                item.get("id"),
            )
            if handled is not None:
                out.append(handled)
        response = JSONResponse(content=out)
        _record(request, channel="mcp", path="/mcp", status=response.status_code)
        return response

    if not isinstance(payload, dict):
        response = JSONResponse(
            status_code=400,
            content=_mcp_error(None, -32600, "invalid request"),
        )
        _record(request, channel="mcp", path="/mcp", status=response.status_code)
        return response

    handled = _handle_mcp_method(
        str(payload.get("method") or ""),
        payload.get("params") if isinstance(payload.get("params"), dict) else {},
        payload.get("id"),
    )
    if handled is None:
        response = Response(status_code=204)
        _record(request, channel="mcp", path="/mcp", status=204)
        return response
    response = JSONResponse(content=handled)
    _record(request, channel="mcp", path="/mcp", status=response.status_code)
    return response


@mcp_router.get("/mcp")
async def mcp_get(request: Request, _key: str = LlmGatewayDep) -> StreamingResponse:
    """Minimal SSE stream so clients that open GET /mcp stay connected briefly."""

    async def events() -> AsyncIterator[bytes]:
        yield b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/message\",\"params\":{\"level\":\"info\",\"data\":\"ok\"}}\n\n"

    _record(request, channel="mcp", path="/mcp", status=200)
    return StreamingResponse(events(), media_type="text/event-stream")
