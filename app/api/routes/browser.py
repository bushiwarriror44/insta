"""Interactive browser session API (noVNC + Playwright)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.connection_test import run_account_connection_test
from app.api.deps import AuthDep, get_db, verify_ws_token
from app.api.schemas import BrowserCodeIn, BrowserSaveOut, BrowserSessionOut, DiagnosticLogLineOut
from app.browser.session_manager import browser_session_manager
from app.db import Account, Proxy

router = APIRouter(prefix="/api/accounts", tags=["browser"], dependencies=[AuthDep])


def _get_account(username: str, db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account '{username}' not found")
    return account


def _get_proxy(account: Account, db: Session) -> Proxy:
    if account.proxy_id is None:
        raise HTTPException(status_code=400, detail="Прокси не назначен")
    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        raise HTTPException(status_code=400, detail="Запись прокси отсутствует")
    return proxy


@router.post("/{username}/browser/start", response_model=BrowserSessionOut)
async def start_browser_session(username: str, db: Session = Depends(get_db)) -> BrowserSessionOut:
    account = _get_account(username, db)
    proxy = _get_proxy(account, db)
    try:
        await browser_session_manager.start_session(account, proxy)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return BrowserSessionOut(**browser_session_manager.status_dict(username))


@router.get("/{username}/browser/status", response_model=BrowserSessionOut)
def browser_session_status(username: str) -> BrowserSessionOut:
    return BrowserSessionOut(**browser_session_manager.status_dict(username))


@router.post("/{username}/browser/code", response_model=BrowserSessionOut)
async def submit_browser_code(
    username: str,
    payload: BrowserCodeIn,
    db: Session = Depends(get_db),
) -> BrowserSessionOut:
    account = _get_account(username, db)
    try:
        await browser_session_manager.submit_code(db, account, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BrowserSessionOut(**browser_session_manager.status_dict(username))


@router.post("/{username}/browser/save", response_model=BrowserSaveOut)
async def save_browser_session(
    username: str,
    db: Session = Depends(get_db),
    stop_after_save: bool = Query(default=False),
) -> BrowserSaveOut:
    account = _get_account(username, db)
    try:
        result = await browser_session_manager.save_session(db, account)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.refresh(account)
    connection_test = run_account_connection_test(account, db)
    overall_ok = connection_test.overall_ok

    if stop_after_save and overall_ok:
        await browser_session_manager.stop_session(username)

    return BrowserSaveOut(
        **result,
        **browser_session_manager.status_dict(username),
        overall_ok=overall_ok,
        connection_test=connection_test,
        logs=[DiagnosticLogLineOut(**line.__dict__) for line in connection_test.logs],
    )


@router.delete("/{username}/browser/stop", response_model=BrowserSessionOut)
async def stop_browser_session(username: str) -> BrowserSessionOut:
    await browser_session_manager.stop_session(username)
    return BrowserSessionOut(**browser_session_manager.status_dict(username))


@router.websocket("/{username}/browser/vnc/ws")
async def browser_vnc_websocket(
    websocket: WebSocket,
    username: str,
    token: str | None = Query(default=None),
) -> None:
    if not verify_ws_token(websocket.headers.get("authorization"), token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    session = browser_session_manager.get(username)
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
    except Exception:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
