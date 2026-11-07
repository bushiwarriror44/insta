# Install Playwright browsers into the Docker volume and run preflight.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
docker compose up -d reels-api reels-worker
docker compose exec reels-api python -m app.cli install-playwright
docker compose exec reels-api python -m app.cli browser-vnc-diag
docker compose exec reels-api python -m app.cli preflight
Write-Host "Done. Google Chrome is in the API image; install-playwright still installs Chromium to the volume."
