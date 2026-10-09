#!/usr/bin/env bash
# Print render-related .env keys as set/empty (no secret values). Run from repo root on VPS.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE="${1:-.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE" >&2
  exit 1
fi
vars=(
  FAL_API_KEY HF_TOKEN POLLINATIONS_API_KEY POLLINATIONS_VIDEO_URL
  VIDEO_BACKEND VIDEO_BACKEND_CHAIN WAN_BASE_URL WAN_API_KEY AGENT_BASE_URL
)
for v in "${vars[@]}"; do
  if grep -q "^${v}=" "$ENV_FILE" 2>/dev/null; then
    val=$(grep "^${v}=" "$ENV_FILE" | cut -d= -f2-)
    if [[ -z "$val" ]]; then echo "$v=ПУСТО"; else echo "$v=заполнено"; fi
  else
    echo "$v=НЕТ_СТРОКИ"
  fi
done
