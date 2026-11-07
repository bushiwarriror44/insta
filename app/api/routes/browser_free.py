"""Free-form VNC browser (no account) with proxy from the pool."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db, verify_ws_token
from app.api.schemas import BrowserFreeStartIn, BrowserSessionOut
from app.browser.session_manager import browser_session_manager
from app.db import Proxy
from app.logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/browser/free", tags=["browser-free"], dependencies=[AuthDep])


def _require_adhoc_session_id(session_id: str) -> str:
    sid = (session_id or "").strip()
    if not sid.startswith("adhoc-"):
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return sid


def _get_proxy_by_label(db: Session, label: str) -> Proxy:
    cleaned = (label or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Укажите proxy_label")
    proxy = db.scalar(select(Proxy).where(Proxy.label == cleaned))
    if proxy is None:
        raise HTTPException(status_code=404, detail=f"Прокси «{cleaned}» не найден")
    if not (proxy.url or "").strip():
        raise HTTPException(status_code=400, detail="У прокси не задан URL")
    return proxy


def _status_out(session_id: str) -> BrowserSessionOut:
    payload = browser_session_manager.status_dict(session_id)
    return BrowserSessionOut(**payload)


@router.post("/start", response_model=BrowserSessionOut)
async def start_free_browser(
    body: BrowserFreeStartIn,
    db: Session = Depends(get_db),
) -> BrowserSessionOut:
    proxy = _get_proxy_by_label(db, body.proxy_label)
    try:
        session = await browser_session_manager.start_free_session(
            proxy,
            initial_url=body.initial_url,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _status_out(session.username)


@router.get("/{session_id}/status", response_model=BrowserSessionOut)
def free_browser_status(session_id: str) -> BrowserSessionOut:
    sid = _require_adhoc_session_id(session_id)
    return _status_out(sid)


@router.delete("/{session_id}/stop", response_model=BrowserSessionOut)
async def stop_free_browser(session_id: str) -> BrowserSessionOut:
    sid = _require_adhoc_session_id(session_id)
    await browser_session_manager.stop_session(sid)
    return _status_out(sid)


@router.websocket("/{session_id}/vnc/ws")
async def free_browser_vnc_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str | None = None,
) -> None:
    if not verify_ws_token(websocket.headers.get("authorization"), token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    sid = (session_id or "").strip()
    if not sid.startswith("adhoc-"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    session = browser_session_manager.get(sid)
    if session is None or session.ws_port <= 0:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    target_uri = f"ws://127.0.0.1:{session.ws_port}"

    try:
        import websockets
    except ImportError:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    try:
        async with websockets.connect(target_uri, max_size=None) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        message = await websocket.receive()
                        if message.get("type") == "websocket.disconnect":
                            break
                        if message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                        elif message.get("text") is not None:
                            await upstream.send(message["text"])
                except WebSocketDisconnect:
                    pass

            async def upstream_to_client() -> None:
                async for payload in upstream:
                    if isinstance(payload, bytes):
                        await websocket.send_bytes(payload)
                    else:
                        await websocket.send_text(payload)

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as exc:
        logger.exception(
            "browser.free_vnc_ws_proxy_failed",
            session_id=sid,
            ws_port=session.ws_port,
            error=str(exc),
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
