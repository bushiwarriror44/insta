"""Interactive browser session API (noVNC + Playwright)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.login_identifier import resolve_login_identifier
from app.api.deps import AuthDep, AuthPrincipal, get_db, resolve_principal, verify_ws_token
from app.api.schemas import BrowserCodeIn, BrowserSaveOut, BrowserSessionOut, DiagnosticLogLineOut
from app.behavior.playwright_surface import resolve_playwright_surface
from app.browser.session_manager import NavTarget, browser_session_manager
from app.db import Account, Proxy
from app.logging_setup import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["browser"])


def _get_account(username: str, db: Session) -> Account:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Аккаунт «{username}» не найден")
    return account


def _get_proxy(account: Account, db: Session) -> Proxy:
    if account.proxy_id is None:
        raise HTTPException(status_code=400, detail="Прокси не назначен")
    proxy = db.get(Proxy, account.proxy_id)
    if proxy is None:
        raise HTTPException(status_code=400, detail="Запись прокси отсутствует")
    return proxy


def _account_credentials(account: Account, *, include_secrets: bool) -> dict[str, str | None]:
    login = resolve_login_identifier(account) if include_secrets else None
    return {
        "account_username": account.username,
        "account_login": login,
        "account_password": account.password if include_secrets else None,
        "account_notes": account.notes,
    }


def _browser_session_response(
    username: str,
    db: Session,
    principal: AuthPrincipal,
) -> BrowserSessionOut:
    account = db.scalar(select(Account).where(Account.username == username))
    if account is None:
        raise HTTPException(status_code=404, detail=f"Аккаунт «{username}» не найден")
    include_secrets = principal.role == "owner"
    payload = {
        **browser_session_manager.status_dict(username),
        **_account_credentials(account, include_secrets=include_secrets),
    }
    return BrowserSessionOut(**payload)


@router.post("/{username}/browser/start", response_model=BrowserSessionOut, dependencies=[AuthDep])
async def start_browser_session(
    username: str,
    login_surface: str | None = Query(default=None),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSessionOut:
    account = _get_account(username, db)
    proxy = _get_proxy(account, db)
    resolved_surface = resolve_playwright_surface(login_surface or account.login_surface)
    account.login_surface = resolved_surface
    db.commit()
    try:
        # Proxy preflight runs in parallel with VNC inside start_session.
        await browser_session_manager.start_session(
            account,
            proxy,
            surface=resolved_surface,
            proxy_snapshot=None,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _browser_session_response(username, db, principal)


@router.post("/{username}/browser/open-instagram", response_model=BrowserSessionOut, dependencies=[AuthDep])
async def open_instagram_in_browser(
    username: str,
    autofill: bool = Query(default=False),
    target: NavTarget = Query(default="auto"),
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSessionOut:
    account = _get_account(username, db)
    proxy = _get_proxy(account, db)
    try:
        await browser_session_manager.open_instagram(
            account,
            proxy,
            autofill_login=autofill,
            target=target,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _browser_session_response(username, db, principal)


@router.get("/{username}/browser/status", response_model=BrowserSessionOut, dependencies=[AuthDep])
def browser_session_status(
    username: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSessionOut:
    return _browser_session_response(username, db, principal)


@router.post("/{username}/browser/code", response_model=BrowserSessionOut, dependencies=[AuthDep])
async def submit_browser_code(
    username: str,
    payload: BrowserCodeIn,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSessionOut:
    account = _get_account(username, db)
    try:
        await browser_session_manager.submit_code(db, account, payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _browser_session_response(username, db, principal)


@router.post("/{username}/browser/save", response_model=BrowserSaveOut, dependencies=[AuthDep])
async def save_browser_session(
    username: str,
    db: Session = Depends(get_db),
    stop_after_save: bool = Query(default=False),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSaveOut:
    """Persist web sessionid from the live browser.

    Does **not** run mobile ``login_by_sessionid`` probe — that often invalidates
    the freshly saved web cookie. Use ``POST .../test-connection`` explicitly.
    """
    account = _get_account(username, db)
    try:
        result = await browser_session_manager.save_session(db, account)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.refresh(account)
    overall_ok = bool(result.get("session_imported")) and bool((account.session_id or "").strip())

    if stop_after_save and overall_ok:
        await browser_session_manager.stop_session(username)

    browser_session_manager.persist_action_logs(
        db,
        account,
        status="ok" if overall_ok else "warn",
        summary="browser save: web sessionid" if overall_ok else "browser save incomplete",
    )

    base = _browser_session_response(username, db, principal)
    now_ts = datetime.now(timezone.utc).isoformat()
    extra = [
        DiagnosticLogLineOut(
            ts=now_ts,
            level="info",
            step="save",
            message="Сессия сохранена (web cookies → БД)",
        ),
        DiagnosticLogLineOut(
            ts=now_ts,
            level="info",
            step="verify",
            message=(
                "Mobile API-проверка пропущена. Для автопостинга: "
                "«Подготовить к автопостингу» или пост в очередь по паролю."
            ),
        ),
    ]
    merged_logs = list(base.logs) + extra

    return BrowserSaveOut(
        **result,
        **base.model_dump(exclude={"logs"}),
        overall_ok=overall_ok,
        connection_test=None,
        logs=merged_logs,
    )


@router.delete("/{username}/browser/stop", response_model=BrowserSessionOut, dependencies=[AuthDep])
async def stop_browser_session(
    username: str,
    db: Session = Depends(get_db),
    principal: AuthPrincipal = Depends(resolve_principal),
) -> BrowserSessionOut:
    account = _get_account(username, db)
    browser_session_manager.persist_action_logs(
        db,
        account,
        status="ok",
        summary="browser session stopped",
    )
    await browser_session_manager.stop_session(username)
    return _browser_session_response(username, db, principal)


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
    except Exception as exc:
        logger.exception(
            "browser.vnc_ws_proxy_failed",
            username=username,
            ws_port=session.ws_port,
            error=str(exc),
        )
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
