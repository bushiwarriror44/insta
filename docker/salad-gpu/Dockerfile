# syntax=docker/dockerfile:1
# One Salad replica: Ollama chat + Wan 2.1 T2V 1.3B. Not for the admin VPS compose.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_KEEP_ALIVE=30m \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/wan \
    WAN_DIR=/opt/wan \
    WAN_CKPT=/opt/wan/Wan2.1-T2V-1.3B \
    AGENT_MODEL=qwen3:32b

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg git nginx \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

ENV OLLAMA_MODELS=/opt/ollama/models

# Cache mount keeps partial blobs across failed builds; copy into the image only after a full pull.
RUN --mount=type=cache,id=ollama-qwen3-32b,target=/ollama-cache \
    /bin/bash -c '\
      set -euo pipefail; \
      export OLLAMA_MODELS=/ollama-cache/models; \
      mkdir -p "$OLLAMA_MODELS"; \
      ollama serve & pid=$!; \
      trap "kill $pid; wait $pid 2>/dev/null || true" EXIT; \
      for i in $(seq 1 90); do curl -sf http://127.0.0.1:11434/ >/dev/null && break; sleep 1; done; \
      ok=0; \
      for attempt in 1 2 3 4 5; do \
        if ollama pull qwen3:32b; then ok=1; break; fi; \
        echo "ollama pull failed attempt $attempt"; sleep 20; \
      done; \
      test $ok -eq 1; \
      ollama list | grep -q qwen3:32b; \
      mkdir -p /opt/ollama; \
      rm -rf /opt/ollama/models; \
      cp -a /ollama-cache/models /opt/ollama/models'

# dashscope is imported by Wan generate.py even when prompt extend is off.
# flash-attn is not installed on Salad; route model.py through attention() (SDPA).
RUN git clone --depth 1 https://github.com/Wan-Video/Wan2.1.git /opt/wan \
 && sed -i 's/from \.attention import flash_attention/from .attention import attention as flash_attention/' \
      /opt/wan/wan/modules/model.py \
 && pip install --no-cache-dir \
      "huggingface_hub[cli]" fastapi "uvicorn[standard]" \
      opencv-python-headless easydict ftfy imageio imageio-ffmpeg \
      diffusers transformers accelerate tqdm tokenizers \
      einops sentencepiece protobuf dashscope

RUN --mount=type=cache,id=hf-wan-1.3b,target=/root/.cache/huggingface \
    hf download Wan-AI/Wan2.1-T2V-1.3B --local-dir /opt/wan/Wan2.1-T2V-1.3B

COPY nginx.conf /etc/nginx/conf.d/salad.conf
COPY generate_server.py /opt/gpu/generate_server.py
COPY start.sh /opt/gpu/start.sh
RUN rm -f /etc/nginx/sites-enabled/default \
 && sed -i 's/\r$//' /opt/gpu/start.sh \
 && chmod +x /opt/gpu/start.sh

WORKDIR /opt/gpu
EXPOSE 8080
CMD ["/opt/gpu/start.sh"]
