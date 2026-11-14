"""Optional vision fallback for browser login (Ollama multimodal)."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

import httpx

from app.config import Settings, get_settings
from app.logging_setup import get_logger

logger = get_logger(__name__)

VisionActionKind = Literal["click", "type", "wait", "done", "unknown"]


@dataclass(frozen=True)
class VisionAction:
    action: VisionActionKind
    x: float | None = None
    y: float | None = None
    text: str | None = None
    selector_hint: str | None = None
    reason: str | None = None


def vision_enabled(cfg: Settings | None = None) -> bool:
    cfg = cfg or get_settings()
    return bool(cfg.agent_vision_enabled)


def vision_base_url(cfg: Settings | None = None) -> str:
    cfg = cfg or get_settings()
    dedicated = (cfg.agent_vision_base_url or "").strip()
    if dedicated:
        return dedicated.rstrip("/")
    return cfg.agent_base_url.rstrip("/")


async def capture_viewport_png(page, *, max_width: int = 1280) -> bytes:
    """Screenshot viewport; optionally downscale width to save VRAM."""
    raw = await page.screenshot(type="png", full_page=False)
    if max_width <= 0 or len(raw) < 100:
        return raw
    try:
        from PIL import Image

        img = Image.open(BytesIO(raw))
        w, h = img.size
        if w > max_width:
            nh = max(1, int(h * max_width / w))
            img = img.resize((max_width, nh))
            out = BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception as exc:
        logger.debug("browser_vision.resize_skip", error=str(exc))
    return raw


def _parse_vision_json(text: str) -> VisionAction:
    text = (text or "").strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return VisionAction(action="unknown", reason=text[:200])
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return VisionAction(action="unknown", reason=text[:200])
    if not isinstance(data, dict):
        return VisionAction(action="unknown")
    action = str(data.get("action") or "unknown").lower()
    if action not in ("click", "type", "wait", "done"):
        action = "unknown"
    x = data.get("x")
    y = data.get("y")
    try:
        xf = float(x) if x is not None else None
        yf = float(y) if y is not None else None
    except (TypeError, ValueError):
        xf = yf = None
    return VisionAction(
        action=action,  # type: ignore[arg-type]
        x=xf,
        y=yf,
        text=str(data.get("text") or "").strip() or None,
        selector_hint=str(data.get("selector_hint") or "").strip() or None,
        reason=str(data.get("reason") or "").strip() or None,
    )


def vision_plan(
    image_png: bytes,
    *,
    goal: str,
    settings: Settings | None = None,
) -> VisionAction:
    cfg = settings or get_settings()
    if not vision_enabled(cfg):
        return VisionAction(action="unknown", reason="vision disabled")
    model = (cfg.agent_vision_model or "").strip()
    if not model:
        return VisionAction(action="unknown", reason="no vision model")
    b64 = base64.standard_b64encode(image_png).decode("ascii")
    prompt = (
        f"Goal: {goal.strip()}\n"
        "Reply with ONE JSON object only: "
        '{"action":"click|type|wait|done","x":number,"y":number,'
        '"text":"for type","selector_hint":"optional","reason":"short"}'
    )
    url = f"{vision_base_url(cfg)}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ],
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.agent_api_key:
        headers["Authorization"] = f"Bearer {cfg.agent_api_key}"
    try:
        with httpx.Client(timeout=cfg.agent_timeout_seconds) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:
        logger.warning("browser_vision.request_failed", error=str(exc))
        return VisionAction(action="unknown", reason=str(exc)[:200])
    try:
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text = " ".join(
                str(p.get("text", "")) for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        else:
            text = str(content)
    except (KeyError, IndexError, TypeError):
        return VisionAction(action="unknown", reason="bad model response")
    return _parse_vision_json(text)


async def apply_vision_action(page, action: VisionAction) -> bool:
    from app.behavior.warmup_playwright import _human_type, _human_wait

    if action.action == "done":
        return True
    if action.action == "wait":
        await _human_wait(0.5, 1.2)
        return False
    if action.action == "click" and action.x is not None and action.y is not None:
        await page.mouse.click(action.x, action.y)
        await _human_wait(0.2, 0.5)
        return False
    if action.action == "type" and action.text:
        if action.selector_hint:
            try:
                await _human_type(page, action.selector_hint, action.text, click_first=True)
                return False
            except Exception:
                pass
        if action.x is not None and action.y is not None:
            await page.mouse.click(action.x, action.y)
        await page.keyboard.type(action.text, delay=80)
        return False
    return False


async def vision_login_fallback(
    page,
    *,
    goal: str = "complete login form",
    settings: Settings | None = None,
) -> bool:
    """Try up to browser_vision_max_steps vision actions. Returns True if model said done."""
    cfg = settings or get_settings()
    if not vision_enabled(cfg):
        return False
    steps = cfg.browser_vision_max_steps
    for _ in range(steps):
        png = await capture_viewport_png(page)
        action = vision_plan(png, goal=goal, settings=cfg)
        if action.action == "done":
            return True
        if action.action == "unknown":
            break
        await apply_vision_action(page, action)
    return False
