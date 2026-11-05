#!/usr/bin/env bash
# HEAD studio.youtube.com + accounts.google.com via each account proxy from DB (no manual curl -x).
#
# Usage:
#   cd /opt/insta
#   bash deploy/proxy-studio-check.sh                    # imported YT/TT (am-mobile-*)
#   bash deploy/proxy-studio-check.sh AuraBluekudsv      # one account's proxy
#   bash deploy/proxy-studio-check.sh --imported-only --timeout 45
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -eq 0 ]]; then
  set -- --imported-only
fi

exec docker compose exec -T reels-api python -m app.cli proxy-studio-check "$@"
