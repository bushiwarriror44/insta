#!/usr/bin/env bash
set -euo pipefail

# Default to worker if no CLI command is provided.
if [ "$#" -eq 0 ]; then
  set -- run-worker
fi

# Idempotent: ensure SQLite schema exists before API/worker binaries start.
# Runs in both services so API never races a fresh volume before worker init finishes.
if [ "${SKIP_AUTO_INIT_DB:-0}" != "1" ]; then
  case "${1:-}" in
    run-worker|run-api)
      python -m app.cli init-db
      ;;
    *)
      ;;
  esac
fi

exec python -m app.cli "$@"
