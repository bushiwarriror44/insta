# Explicit bookworm avoids surprise moves to Debian testing images and flaky mirror paths.
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV VENV_PATH=/opt/venv

WORKDIR /app

# Many networks drop plain HTTP or IPv6 oddly; APT over HTTPS + retries fixes most Docker builds on Windows/VPN setups.
RUN set -ex; \
    printf '%s\n' \
        'Acquire::Retries "12";' \
        'Acquire::http::Timeout "120";' \
        'Acquire::https::Timeout "120";' \
        'Acquire::ftp::Timeout "120";' \
        > /etc/apt/apt.conf.d/99docker-retry; \
    find /etc/apt -type f \( -name '*.sources' -o -name '*.list' -o -name 'sources.list' \) \
        -exec sed -i 's|http://deb.debian.org|https://deb.debian.org|g' {} + || true

# Build-stage deps are intentionally separate from runtime to keep
# the final image smaller.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        ffmpeg \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libatspi2.0-0 \
        libxshmfence1 \
        libpango-1.0-0 \
        libcairo2 \
        libgtk-3-0 \
        libx11-xcb1 \
        xvfb \
        x11vnc \
        novnc \
        websockify && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./

RUN python -m venv "${VENV_PATH}" && \
    "${VENV_PATH}/bin/pip" install --upgrade pip && \
    "${VENV_PATH}/bin/pip" install -r requirements.txt

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV VENV_PATH=/opt/venv
ENV PATH="${VENV_PATH}/bin:${PATH}"

WORKDIR /app

RUN set -ex; \
    printf '%s\n' \
        'Acquire::Retries "12";' \
        'Acquire::http::Timeout "120";' \
        'Acquire::https::Timeout "120";' \
        'Acquire::ftp::Timeout "120";' \
        > /etc/apt/apt.conf.d/99docker-retry; \
    find /etc/apt -type f \( -name '*.sources' -o -name '*.list' -o -name 'sources.list' \) \
        -exec sed -i 's|http://deb.debian.org|https://deb.debian.org|g' {} + || true

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        libnss3 \
        libnspr4 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libdbus-1-3 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libatspi2.0-0 \
        libxshmfence1 \
        libpango-1.0-0 \
        libcairo2 \
        libgtk-3-0 \
        libx11-xcb1 \
        xvfb \
        x11vnc \
        novnc \
        websockify && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY . .

# Browser binaries are installed on-demand at runtime (see CLI command
# `install-playwright`) to keep docker build lighter and more stable on WSL.
RUN mkdir -p /ms-playwright

RUN chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["run-worker"]
