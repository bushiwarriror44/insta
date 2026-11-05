#!/usr/bin/env bash
# Full noVNC / admin browser checks on the VPS (auto-reads .env ADMIN_TOKEN).
#
# Usage:
#   cd /opt/insta
#   bash deploy/browser-vnc-check.sh              # all accounts with proxy
#   bash deploy/browser-vnc-check.sh --start      # start first eligible, then check all
#   bash deploy/browser-vnc-check.sh alice        # one account
#   bash deploy/browser-vnc-check.sh alice --start
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DO_START=0
USERNAME=""
for arg in "$@"; do
  case "$arg" in
    --start) DO_START=1 ;;
    --help|-h)
      echo "Usage: bash deploy/browser-vnc-check.sh [USERNAME] [--start]" >&2
      echo "  No USERNAME — checks every account that has a proxy in DB." >&2
      echo "  --start    POST browser/start (one user, or first with proxy if USERNAME omitted)." >&2
      exit 0
      ;;
    --*) echo "Unknown option: $arg" >&2; exit 1 ;;
    *)
      if [[ -n "$USERNAME" ]]; then
        echo "Unexpected extra argument: $arg" >&2
        exit 1
      fi
      USERNAME="$arg"
      ;;
  esac
done

ADMIN_TOKEN=""
if [[ -f .env ]]; then
  line="$(grep -E '^[[:space:]]*ADMIN_TOKEN=' .env | tail -1 || true)"
  if [[ -n "$line" ]]; then
    ADMIN_TOKEN="${line#ADMIN_TOKEN=}"
    ADMIN_TOKEN="${ADMIN_TOKEN#"${ADMIN_TOKEN%%[![:space:]]*}"}"
    ADMIN_TOKEN="${ADMIN_TOKEN%"${ADMIN_TOKEN##*[![:space:]]}"}"
    ADMIN_TOKEN="${ADMIN_TOKEN#\"}"
    ADMIN_TOKEN="${ADMIN_TOKEN%\"}"
    ADMIN_TOKEN="${ADMIN_TOKEN#\'}"
    ADMIN_TOKEN="${ADMIN_TOKEN%\'}"
  fi
fi

CURL_AUTH=()
WS_TOKEN_QS=""
if [[ -n "$ADMIN_TOKEN" ]]; then
  CURL_AUTH=(-H "Authorization: Bearer ${ADMIN_TOKEN}")
  export _BROWSER_VNC_CHECK_TOKEN="$ADMIN_TOKEN"
  WS_TOKEN_QS="?token=$(python3 -c 'import os, urllib.parse; print(urllib.parse.quote(os.environ["_BROWSER_VNC_CHECK_TOKEN"], safe=""))')"
  unset _BROWSER_VNC_CHECK_TOKEN
else
  echo "Note: ADMIN_TOKEN empty in .env — API may be open; WS ?token= omitted." >&2
fi

API="http://127.0.0.1:8000"

section() {
  echo ""
  echo "========== $* =========="
}

discover_usernames() {
  docker compose exec -T reels-api python - <<'PY'
from sqlalchemy import select
from app.db import Account, SessionLocal

with SessionLocal() as db:
    names = db.scalars(
        select(Account.username)
        .where(Account.proxy_id.isnot(None))
        .order_by(Account.platform, Account.username)
    ).all()
for n in names:
    if n and str(n).strip():
        print(str(n).strip())
PY
}

fetch_browser_status() {
  local user="$1"
  if ((${#CURL_AUTH[@]})); then
    curl -sS "${CURL_AUTH[@]}" "${API}/api/accounts/${user}/browser/status" 2>/dev/null || true
  else
    curl -sS "${API}/api/accounts/${user}/browser/status" 2>/dev/null || true
  fi
}

status_field() {
  local user="$1"
  local field="$2"
  fetch_browser_status "$user" | python3 -c "
import json, sys
field = sys.argv[1]
try:
    d = json.load(sys.stdin)
except json.JSONDecodeError:
    sys.exit(1)
print(d.get(field, ''))
" "$field" 2>/dev/null || echo ""
}

post_browser_start() {
  local user="$1"
  echo "--- POST browser/start @${user} ---"
  if ((${#CURL_AUTH[@]})); then
    curl -sS -w "\nHTTP %{http_code}\n" -X POST "${CURL_AUTH[@]}" \
      "${API}/api/accounts/${user}/browser/start" || true
  else
    curl -sS -w "\nHTTP %{http_code}\n" -X POST \
      "${API}/api/accounts/${user}/browser/start" || true
  fi
}

check_user() {
  local user="$1"
  local verbose="${2:-1}"

  section "Account @${user}"

  docker compose exec -T reels-api python -m app.cli browser-vnc-diag "$user"

  local st
  st="$(status_field "$user" status)"
  if [[ -z "$st" ]]; then
    echo "WARN: could not read browser/status for @${user} (auth? API down?)"
    return
  fi

  echo "browser/status summary: status=${st}"
  if [[ "$verbose" -eq 1 ]]; then
    section "GET browser/status @${user} (JSON)"
    fetch_browser_status "$user" | python3 -m json.tool 2>/dev/null || fetch_browser_status "$user"
  fi

  if [[ "$st" == "running" || "$st" == "starting" || "$st" == "awaiting_code" ]]; then
    local ws_path="/api/accounts/${user}/browser/vnc/ws${WS_TOKEN_QS}"
    section "WebSocket @${user} (session active)"
    echo "API:    ws://127.0.0.1:8000${ws_path}"
    echo "Frontend nginx: ws://127.0.0.1:3000${ws_path}"
    if command -v wscat >/dev/null 2>&1; then
      echo "Probing API WS (3s timeout)..."
      timeout 3 wscat -c "ws://127.0.0.1:8000${ws_path}" 2>&1 || true
    fi
  else
    echo "(WebSocket skip — status=${st}; start browser in UI or use --start)"
  fi
}

section "1. Memory & swap"
free -h || true
swapon --show 2>/dev/null || true

section "2. Docker services"
docker compose ps

section "3. Listening ports (80 / 3000 / 8000)"
if command -v ss >/dev/null 2>&1; then
  ss -tlnp | grep -E ':80 |:3000 |:8000 ' || echo "(no matches — adjust grep or run as root for -p)"
else
  netstat -tlnp 2>/dev/null | grep -E ':80 |:3000 |:8000 ' || true
fi

section "4. In-container VNC stack (no user)"
docker compose exec -T reels-api python -m app.cli browser-vnc-diag

mapfile -t ALL_USERS < <(discover_usernames 2>/dev/null | tr -d '\r' | sed '/^[[:space:]]*$/d' || true)

if [[ -n "$USERNAME" ]]; then
  TARGET_USERS=("$USERNAME")
else
  if [[ ${#ALL_USERS[@]} -eq 0 ]]; then
    echo "No accounts with proxy in DB — assign proxy in admin panel first." >&2
    exit 1
  fi
  TARGET_USERS=("${ALL_USERS[@]}")
  section "5. Accounts to check (proxy assigned)"
  printf '  @%s\n' "${TARGET_USERS[@]}"
fi

if [[ "$DO_START" -eq 1 ]]; then
  START_USER="${USERNAME:-${TARGET_USERS[0]}}"
  section "6. POST browser/start"
  post_browser_start "$START_USER"
  if [[ -z "$USERNAME" && ${#TARGET_USERS[@]} -gt 1 ]]; then
    echo "Note: --start without USERNAME only started @${START_USER} (first in list)."
  fi
else
  section "6. browser/start skipped (add --start to launch)"
fi

section "7. Per-account browser status"
for u in "${TARGET_USERS[@]}"; do
  if [[ ${#TARGET_USERS[@]} -gt 3 ]]; then
    st="$(status_field "$u" status)"
    err="$(status_field "$u" error)"
    echo "@${u}  status=${st:-?}  error=${err:--}"
  else
    check_user "$u" 1
  fi
done

if [[ ${#TARGET_USERS[@]} -gt 3 ]]; then
  section "7b. Full detail for active sessions only"
  for u in "${TARGET_USERS[@]}"; do
    st="$(status_field "$u" status)"
    if [[ "$st" == "running" || "$st" == "starting" || "$st" == "awaiting_code" ]]; then
      check_user "$u" 1
    fi
  done
fi

section "8. Host nginx WebSocket (if panel on :80)"
if [[ -f /etc/nginx/sites-enabled/insta ]]; then
  grep -E 'Upgrade|connection_upgrade|proxy_read_timeout' /etc/nginx/sites-enabled/insta || \
    echo "WARN: no Upgrade headers in /etc/nginx/sites-enabled/insta — see deploy/host-nginx.conf.example"
else
  echo "No /etc/nginx/sites-enabled/insta — OK if you use :3000 directly"
fi

section "9. reels-api logs (last 40 lines)"
docker compose logs reels-api --tail=40

section "Done"
echo "Accounts checked: ${#TARGET_USERS[@]}"
echo "Re-run with --start to launch browser for first account (or pass USERNAME --start)."
echo "If WS fails from your PC but OK on VPS: deploy/host-nginx.conf.example"
