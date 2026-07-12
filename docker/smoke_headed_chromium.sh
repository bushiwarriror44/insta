#!/usr/bin/env bash
# Smoke-test headed Chromium inside Docker (requires xvfb + playwright browsers).
set -euo pipefail

export DISPLAY="${DISPLAY:-:99}"
SCREEN="${SCREEN:-1280x800x24}"

if ! command -v Xvfb >/dev/null 2>&1; then
  echo "Xvfb not installed" >&2
  exit 1
fi

Xvfb "${DISPLAY}" -screen 0 "${SCREEN}" -ac +extension GLX +render -noreset &
XVFB_PID=$!
trap 'kill "${XVFB_PID}" 2>/dev/null || true' EXIT
sleep 1

python - <<'PY'
import asyncio
import os
import sys


async def main() -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 1

    display = os.environ.get("DISPLAY", ":99")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            env={**os.environ, "DISPLAY": display},
        )
        page = await browser.new_page()
        await page.goto("about:blank", timeout=15000)
        title = await page.title()
        await browser.close()
    print(f"headed chromium ok on {display}, title={title!r}")
    return 0


raise SystemExit(asyncio.run(main()))
PY
