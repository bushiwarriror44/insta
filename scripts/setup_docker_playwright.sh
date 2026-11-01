#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose up -d reels-api reels-worker
docker compose exec reels-api python -m app.cli install-playwright
docker compose exec reels-api python -m app.cli preflight
