#!/usr/bin/env bash
# Add or resize swap on Ubuntu/Debian VPS (e.g. 1 GB RAM + 6 GB swap for noVNC/Chromium).
#
# Usage on VPS:
#   sudo bash deploy/setup-swap.sh
#   sudo bash deploy/setup-swap.sh 6G          # explicit size (default 6G)
#   sudo SWAP_SIZE=8G bash deploy/setup-swap.sh
#
# Safe to re-run: skips if /swapfile already exists with correct size.

set -euo pipefail

SWAP_SIZE="${1:-${SWAP_SIZE:-6G}}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 [$SWAP_SIZE]" >&2
  exit 1
fi

if swapon --show | grep -q "^${SWAP_FILE} "; then
  echo "Swap already active at ${SWAP_FILE}:"
  swapon --show
  free -h
  exit 0
fi

if [[ -f "${SWAP_FILE}" ]]; then
  echo "File ${SWAP_FILE} exists but is not active. Remove it first or set SWAP_FILE." >&2
  exit 1
fi

echo "Creating ${SWAP_SIZE} swap at ${SWAP_FILE}..."
if ! fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}" 2>/dev/null; then
  echo "fallocate failed, using dd (may take a few minutes)..."
  dd if=/dev/zero of="${SWAP_FILE}" bs=1M count=6144 status=progress
fi
chmod 600 "${SWAP_FILE}"
mkswap "${SWAP_FILE}"
swapon "${SWAP_FILE}"

if ! grep -q "${SWAP_FILE}" /etc/fstab 2>/dev/null; then
  echo "${SWAP_FILE} none swap sw 0 0 # insta-swap" >> /etc/fstab
fi

# Lower swap aggressiveness — use RAM first, swap only when needed (better for browsers)
SYSCTL_FILE="/etc/sysctl.d/99-insta-swap.conf"
cat > "${SYSCTL_FILE}" <<'EOF'
# Prefer RAM; use swap when memory pressure is high (interactive browser on small VPS).
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl -p "${SYSCTL_FILE}" >/dev/null

echo ""
echo "Done. Current memory:"
free -h
echo ""
swapon --show
