#!/usr/bin/env bash
# Run on VPS: cd /opt/insta && bash scripts/vps-first-login-fix.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Rebuild and restart containers"
docker compose up -d --build

echo "==> Wait for API health"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "==> Verify first-login endpoint in OpenAPI"
if ! curl -sf http://127.0.0.1:8000/api/openapi.json | grep -q 'first-login'; then
  echo "ERROR: first-login not found in OpenAPI — check deploy" >&2
  exit 1
fi

echo "==> POST smoke test (direct API, expect 401 without token or 404/503 with token)"
curl -s -o /dev/null -w "POST :8000 -> HTTP %{http_code}\n" \
  -X POST "http://127.0.0.1:8000/api/accounts/smoke-test-user/first-login" || true

echo "==> POST smoke test (via frontend nginx)"
curl -s -o /dev/null -w "POST :3000 -> HTTP %{http_code}\n" \
  -X POST "http://127.0.0.1:3000/api/accounts/smoke-test-user/first-login" || true

echo "==> Install Playwright Chromium (required for first-login)"
docker compose exec -T reels-api python -m app.cli install-playwright

echo "==> Done. Use the admin UI button «Создать сессию» — do NOT open API URL in browser (GET returns 405)."
