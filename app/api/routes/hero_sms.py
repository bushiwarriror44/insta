"""Hero SMS virtual numbers (sms-activate compatible handler)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, OwnerOrOpenDep, get_db
from app.api.schemas import (
    HeroSmsActivationStatusOut,
    HeroSmsActiveActivationOut,
    HeroSmsActiveOut,
    HeroSmsApiKeyIn,
    HeroSmsFormState,
    HeroSmsHistoryItemOut,
    HeroSmsHistoryOut,
    HeroSmsOrderIn,
    HeroSmsOrderOut,
    HeroSmsPriceRow,
    HeroSmsPricesOut,
    HeroSmsSetStatusIn,
    HeroSmsSetStatusOut,
    HeroSmsSmsOut,
    HeroSmsStatusOut,
)
from app.panel.settings_store import (
    get_hero_sms_last_form,
    hero_sms_key_from_env,
    resolve_hero_sms_api_key,
    set_hero_sms_api_key,
    set_hero_sms_last_form,
)
from app.services import hero_sms as hs

router = APIRouter(prefix="/api/hero-sms", tags=["hero-sms"], dependencies=[AuthDep])


def _key_or_400(db: Session) -> str:
    key = resolve_hero_sms_api_key(db)
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Не задан API-ключ Hero SMS. Укажите HERO_SMS_API_KEY или сохраните ключ на странице Hero SMS.",
        )
    return key


def _raise_hs(exc: hs.HeroSmsError) -> None:
    code = 502
    if exc.status_code in (401, 403):
        code = 401
    elif exc.status_code == 404:
        code = 404
    elif exc.status_code == 409:
        code = 409
    elif exc.status_code == 400:
        code = 400
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _last_form_out(db: Session) -> HeroSmsFormState | None:
    raw = get_hero_sms_last_form(db)
    if not raw:
        return None
    try:
        return HeroSmsFormState.model_validate(raw)
    except Exception:
        return None


@router.get("/status", response_model=HeroSmsStatusOut)
def status(db: Session = Depends(get_db)) -> HeroSmsStatusOut:
    last_form = _last_form_out(db)
    key = resolve_hero_sms_api_key(db)
    if not key:
        return HeroSmsStatusOut(configured=False, key_from_env=False, last_form=last_form)
    try:
        bal = hs.balance(key)
        return HeroSmsStatusOut(
            configured=True,
            key_from_env=hero_sms_key_from_env(),
            balance=bal,
            last_form=last_form,
        )
    except hs.HeroSmsError as exc:
        return HeroSmsStatusOut(
            configured=True,
            key_from_env=hero_sms_key_from_env(),
            last_form=last_form,
            error=str(exc),
        )


@router.put("/api-key", response_model=HeroSmsStatusOut, dependencies=[OwnerOrOpenDep])
def put_api_key(
    payload: HeroSmsApiKeyIn,
    db: Session = Depends(get_db),
) -> HeroSmsStatusOut:
    if hero_sms_key_from_env():
        raise HTTPException(
            status_code=400,
            detail="Ключ задан в HERO_SMS_API_KEY (env) — смените его в окружении сервера.",
        )
    set_hero_sms_api_key(db, payload.api_key)
    return status(db)


@router.get("/countries")
def countries(db: Session = Depends(get_db)) -> Any:
    key = _key_or_400(db)
    try:
        return hs.countries(key)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)


@router.get("/services")
def services(db: Session = Depends(get_db)) -> Any:
    key = _key_or_400(db)
    try:
        return hs.services_list(key)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)


@router.get("/prices", response_model=HeroSmsPricesOut)
def price_list(
    service: str = Query(min_length=1, max_length=32),
    country: int | None = None,
    db: Session = Depends(get_db),
) -> HeroSmsPricesOut:
    key = _key_or_400(db)
    try:
        raw = hs.prices(key, service=service, country=country)
        rows = hs.normalize_prices(raw, service=service)
        return HeroSmsPricesOut(
            service=service,
            rows=[HeroSmsPriceRow.model_validate(r) for r in rows],
        )
    except hs.HeroSmsError as exc:
        _raise_hs(exc)


def _order_out(payload: dict[str, Any]) -> HeroSmsOrderOut:
    act_id = str(payload.get("activationId") or payload.get("id") or "")
    phone = str(payload.get("phoneNumber") or payload.get("phone") or "")
    cost = payload.get("activationCost") or payload.get("cost")
    try:
        cost_f = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost_f = None
    country = payload.get("countryCode") or payload.get("country")
    try:
        country_i = int(country) if country is not None else None
    except (TypeError, ValueError):
        country_i = None
    return HeroSmsOrderOut(
        activation_id=act_id,
        phone_number=phone,
        phone_e164=hs.phone_to_e164(phone),
        activation_cost=cost_f,
        country_id=country_i,
        service_code=str(payload.get("serviceCode") or payload.get("service") or "") or None,
        activation_time=str(payload.get("activationTime") or "") or None,
        activation_end_time=str(payload.get("activationEndTime") or "") or None,
        can_get_another_sms=bool(payload.get("canGetAnotherSms")),
    )


@router.post("/order", response_model=HeroSmsOrderOut)
def order(
    payload: HeroSmsOrderIn,
    db: Session = Depends(get_db),
) -> HeroSmsOrderOut:
    key = _key_or_400(db)
    try:
        raw = hs.order_number(
            key,
            service=payload.service,
            country=payload.country_id,
            max_price=payload.max_price,
            fixed_price=payload.strict_price,
            operator=payload.operator,
        )
    except hs.HeroSmsError as exc:
        _raise_hs(exc)
    set_hero_sms_last_form(
        db,
        {
            "service": payload.service,
            "country_id": payload.country_id,
            "operator": payload.operator,
            "strict_price": payload.strict_price,
        },
    )
    return _order_out(raw if isinstance(raw, dict) else {})


def _activation_status(act_id: str, raw: dict[str, Any]) -> HeroSmsActivationStatusOut:
    sms_block = raw.get("sms")
    sms_out: HeroSmsSmsOut | None = None
    waiting = True
    if isinstance(sms_block, dict):
        code = sms_block.get("code")
        text = sms_block.get("text")
        if code or text:
            sms_out = HeroSmsSmsOut(
                code=str(code) if code is not None else None,
                text=str(text) if text is not None else None,
                date_time=str(sms_block.get("dateTime") or "") or None,
            )
            waiting = not bool(code or text)
        else:
            waiting = True
    elif sms_block is None:
        waiting = True
    return HeroSmsActivationStatusOut(activation_id=act_id, sms=sms_out, waiting=waiting)


@router.get("/activations/active", response_model=HeroSmsActiveOut)
def activations_active(db: Session = Depends(get_db)) -> HeroSmsActiveOut:
    key = _key_or_400(db)
    try:
        rows = hs.active_activations(key)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)
    items: list[HeroSmsActiveActivationOut] = []
    for row in rows:
        act_id = str(row.get("activationId") or row.get("id") or "")
        if not act_id:
            continue
        phone = str(row.get("phoneNumber") or row.get("phone") or "")
        cost = row.get("activationCost") or row.get("cost")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        country = row.get("countryCode") or row.get("country")
        try:
            country_i = int(country) if country is not None else None
        except (TypeError, ValueError):
            country_i = None
        items.append(
            HeroSmsActiveActivationOut(
                activation_id=act_id,
                service_code=str(row.get("serviceCode") or row.get("service") or ""),
                phone_number=phone,
                phone_e164=hs.phone_to_e164(phone),
                activation_cost=cost_f,
                country_id=country_i,
                sms_code=str(row.get("smsCode") or row.get("code") or "") or None,
                sms_text=str(row.get("smsText") or row.get("text") or "") or None,
                activation_time=str(row.get("activationTime") or "") or None,
                receive_sms_date=str(row.get("receiveSmsDate") or "") or None,
            )
        )
    return HeroSmsActiveOut(items=items)


@router.get("/activations/{activation_id}/status", response_model=HeroSmsActivationStatusOut)
def activation_status(activation_id: str, db: Session = Depends(get_db)) -> HeroSmsActivationStatusOut:
    key = _key_or_400(db)
    try:
        raw = hs.status_v2(key, activation_id)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)
    return _activation_status(activation_id, raw if isinstance(raw, dict) else {})


@router.post("/activations/{activation_id}/action", response_model=HeroSmsSetStatusOut)
def activation_action(
    activation_id: str,
    payload: HeroSmsSetStatusIn,
    db: Session = Depends(get_db),
) -> HeroSmsSetStatusOut:
    key = _key_or_400(db)
    try:
        result = hs.set_status(key, activation_id, payload.status)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)
    return HeroSmsSetStatusOut(result=result)


@router.get("/history", response_model=HeroSmsHistoryOut)
def history(
    size: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HeroSmsHistoryOut:
    key = _key_or_400(db)
    try:
        rows = hs.history(key, size=size, offset=offset)
    except hs.HeroSmsError as exc:
        _raise_hs(exc)
    items: list[HeroSmsHistoryItemOut] = []
    for row in rows[:size]:
        cost = row.get("cost")
        try:
            cost_f = float(cost) if cost is not None else None
        except (TypeError, ValueError):
            cost_f = None
        items.append(
            HeroSmsHistoryItemOut(
                id=str(row.get("id") or ""),
                date=str(row.get("date") or "") or None,
                phone=str(row.get("phone") or "") or None,
                sms=str(row.get("sms") or "") or None,
                cost=cost_f,
                status=str(row.get("status") or "") or None,
            )
        )
    return HeroSmsHistoryOut(items=items)
