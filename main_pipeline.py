"""Compatibility entry point.

The legacy single-file pipeline has been replaced with a proper service in
the ``app/`` package. Use the CLI for everything:

    python -m app.cli --help
    python -m app.cli init-db
    python -m app.cli add-proxy ...
    python -m app.cli add-account ...
    python -m app.cli enqueue-post ...
    python -m app.cli run-worker

This file just forwards to the CLI to avoid breaking old shortcuts.
"""
from __future__ import annotations

from app.cli import app


if __name__ == "__main__":
    app()
