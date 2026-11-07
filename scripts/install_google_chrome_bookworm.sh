#!/usr/bin/env bash
# Install Google Chrome stable on Debian bookworm (Docker reels-api runtime).
# Run inside the container: bash /app/scripts/install_google_chrome_bookworm.sh
set -euo pipefail

if command -v google-chrome-stable >/dev/null 2>&1; then
  echo "google-chrome-stable already installed: $(google-chrome-stable --version)"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
  | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
  > /etc/apt/sources.list.d/google-chrome.list
apt-get update
apt-get install -y --no-install-recommends google-chrome-stable
rm -rf /var/lib/apt/lists/*
google-chrome-stable --version
