#!/bin/bash
# Used inside Dockerfile build; pulls one Ollama model with retries + stall timeout.
set -euo pipefail
name="${1:?model name required}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/ollama-cache/models}"
mkdir -p "$OLLAMA_MODELS"
ollama serve & pid=$!
trap 'kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null || true' EXIT
for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:11434/ >/dev/null && break
  sleep 1
done
if ollama list 2>/dev/null | grep -Fq "$name"; then
  echo "ollama: $name already in cache"
  exit 0
fi
# 25 min per attempt — kills hung downloads; Ollama resumes blobs in OLLAMA_MODELS.
PULL_TIMEOUT_SEC="${PULL_TIMEOUT_SEC:-1500}"
ok=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  echo "ollama pull $name attempt $attempt (timeout ${PULL_TIMEOUT_SEC}s)"
  set +e
  if command -v timeout >/dev/null 2>&1; then
    timeout --signal=KILL "$PULL_TIMEOUT_SEC" ollama pull "$name"
    rc=$?
  else
    ollama pull "$name"
    rc=$?
  fi
  set -e
  if [ "$rc" -eq 0 ] && ollama list 2>/dev/null | grep -Fq "$name"; then
    ok=1
    break
  fi
  echo "ollama pull $name failed/timeout attempt $attempt rc=$rc"
  sleep 15
done
test "$ok" -eq 1
ollama list | grep -Fq "$name"
