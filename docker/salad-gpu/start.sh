#!/bin/bash
set -euo pipefail

export OLLAMA_HOST="${OLLAMA_HOST:-0.0.0.0:11434}"
export PYTHONPATH="${WAN_DIR:-/opt/wan}"

python -c "import dashscope" 2>/dev/null || python -m pip install -q dashscope

cleanup() {
  kill "$OLLAMA_PID" "$WAN_PID" 2>/dev/null || true
}
trap cleanup SIGTERM SIGINT

ollama serve &
OLLAMA_PID=$!

python -m uvicorn generate_server:app --host 127.0.0.1 --port 8081 &
WAN_PID=$!

nginx -g "daemon off;" &
NGINX_PID=$!

wait -n "$OLLAMA_PID" "$WAN_PID" "$NGINX_PID"
cleanup
wait || true
