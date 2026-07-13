"""Xvfb + x11vnc + websockify subprocess stack for noVNC."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field

from app.logging_setup import get_logger

logger = get_logger(__name__)

_PORT_BASE = 5900
_WS_PORT_BASE = 6080


def vnc_stack_available() -> bool:
    """True when headed browser + VNC tooling is present on the host."""
    return all(shutil.which(cmd) for cmd in ("Xvfb", "x11vnc", "websockify"))


def allocate_ports(display: int) -> tuple[int, int]:
    """Return (rfb_port, websockify_port) for a virtual display number."""
    offset = display - 100
    return _PORT_BASE + offset, _WS_PORT_BASE + offset


def _screen_with_depth(screen: str, depth: str) -> str:
    if screen.count("x") >= 2:
        return screen.rsplit("x", 1)[0] + f"x{depth}"
    return screen


def _lightweight_x11vnc_args() -> list[str]:
    """x11vnc tuning for small VPS without -ncache (breaks proxied noVNC)."""
    return [
        "-wait",
        "20",
        "-defer",
        "20",
    ]


def _require_running(proc: subprocess.Popen, name: str, *, cmd: list[str]) -> None:
    if proc.poll() is None:
        return
    raise RuntimeError(
        f"{name} exited immediately (code={proc.returncode}); command={cmd!r}"
    )


@dataclass
class VncStack:
    display: int
    rfb_port: int
    ws_port: int
    screen: str = "1280x800x24"
    lightweight: bool = False
    _procs: list[subprocess.Popen] = field(default_factory=list, repr=False)

    @property
    def display_name(self) -> str:
        return f":{self.display}"

    async def start(self) -> None:
        if not vnc_stack_available():
            raise RuntimeError("Xvfb/x11vnc/websockify not installed")

        env = os.environ.copy()
        env["DISPLAY"] = self.display_name

        screen = self.screen
        xvfb_cmd = self._xvfb_command(screen)
        xvfb = subprocess.Popen(
            xvfb_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._procs.append(xvfb)
        await asyncio.sleep(0.35)
        _require_running(xvfb, "Xvfb", cmd=xvfb_cmd)
        await self._wait_display_ready(env, timeout_sec=8.0)

        x11vnc_cmd = [
            "x11vnc",
            "-display",
            self.display_name,
            "-rfbport",
            str(self.rfb_port),
            "-localhost",
            "-nopw",
            "-forever",
            "-shared",
            "-noxdamage",
        ]
        if self.lightweight:
            x11vnc_cmd.extend(_lightweight_x11vnc_args())

        x11vnc = subprocess.Popen(
            x11vnc_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._procs.append(x11vnc)
        await asyncio.sleep(0.4)
        _require_running(x11vnc, "x11vnc", cmd=x11vnc_cmd)

        websockify_cmd = [
            "websockify",
            "--web",
            "/usr/share/novnc",
            str(self.ws_port),
            f"localhost:{self.rfb_port}",
        ]
        websockify = subprocess.Popen(
            websockify_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._procs.append(websockify)
        await asyncio.sleep(0.3)
        _require_running(websockify, "websockify", cmd=websockify_cmd)

        logger.info(
            "vnc.started",
            display=self.display,
            rfb_port=self.rfb_port,
            ws_port=self.ws_port,
            lightweight=self.lightweight,
            screen=screen,
        )

    def _xvfb_command(self, screen: str) -> list[str]:
        cmd = [
            "Xvfb",
            self.display_name,
            "-screen",
            "0",
            screen,
            "-ac",
        ]
        if self.lightweight:
            cmd.append("-noreset")
        else:
            cmd.extend(["+extension", "GLX", "+render", "-noreset"])
        return cmd

    async def _wait_display_ready(self, env: dict[str, str], *, timeout_sec: float) -> None:
        # Xvfb needs a short warm-up before Chromium can attach.
        await asyncio.sleep(min(timeout_sec, 1.2))

    def stop(self) -> None:
        for proc in reversed(self._procs):
            try:
                if proc.poll() is None:
                    proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + 3.0
        for proc in reversed(self._procs):
            while proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        self._procs.clear()
        logger.info("vnc.stopped", display=self.display)
