"""Cross-cutting regression anchors (frozensets, tool catalog)."""
from __future__ import annotations

from app.assistant.chat import (
    BROWSER_TOOL_NAMES,
    LOGIN_ORCH_BROWSER_TOOLS,
    tool_specs,
)


def test_login_orch_browser_tools_anchor():
    assert LOGIN_ORCH_BROWSER_TOOLS == frozenset(
        {
            "browser_status",
            "save_browser_session",
            "submit_browser_code",
            "submit_login_code",
        }
    )


def test_login_orch_vnc_tools_in_browser_catalog():
    """VNC-facing orch tools must stay in BROWSER_TOOL_NAMES (submit_login_code is file-queue only)."""
    vnc_tools = LOGIN_ORCH_BROWSER_TOOLS - {"submit_login_code"}
    assert vnc_tools <= BROWSER_TOOL_NAMES


def test_preview_plan_in_tool_catalog():
    names = {spec["function"]["name"] for spec in tool_specs(allow_browser=False)}
    assert "preview_plan" in names
    run_names = {spec["function"]["name"] for spec in tool_specs(allow_browser=True)}
    assert "preview_plan" in run_names
