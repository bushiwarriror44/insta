#!/bin/sh
set -e
# Pull the planner/chat model into the sibling Ollama container.
host="${OLLAMA_HOST:-http://reels-ollama:11434}"
model="${AGENT_MODEL:-qwen3:8b}"
export OLLAMA_HOST="$host"
i=0
while [ "$i" -lt 60 ]; do
  if ollama list >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 2
done
exec ollama pull "$model"
