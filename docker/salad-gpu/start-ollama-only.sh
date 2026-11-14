#!/bin/bash
set -euo pipefail

export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/opt/ollama/models}"
CHAT_MODEL="${AGENT_MODEL:-qwen3:8b}"
VISION_MODEL="${AGENT_VISION_MODEL:-qwen2.5vl:7b}"

cleanup() {
  kill "$OLLAMA_PID" "$NGINX_PID" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

ensure_model() {
  local name="$1"
  [ -n "$name" ] || return 0
  if ollama list 2>/dev/null | grep -Fq "$name"; then
    echo "ollama: $name already present"
    return 0
  fi
  echo "ollama: pulling $name (override via AGENT_MODEL / AGENT_VISION_MODEL)..."
  ollama pull "$name" || echo "ollama: pull $name failed (continuing)"
}

ollama serve &
OLLAMA_PID=$!

for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:11434/ >/dev/null && break
  sleep 1
done

ensure_model "$CHAT_MODEL"
ensure_model "$VISION_MODEL"

nginx -g "daemon off;" &
NGINX_PID=$!

wait -n "$OLLAMA_PID" "$NGINX_PID"
cleanup
wait || true
