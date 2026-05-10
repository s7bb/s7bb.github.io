FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# git binary required at runtime: GitPython shells out to it. Push uses
# HTTPS with a fine-grained PAT delivered via GIT_ASKPASS; no SSH client needed.
# sqlite3 binary required for ad-hoc DB inspection / one-shot maintenance
# (e.g. `docker compose exec s7bb-fetcher sqlite3 /data/s7bb.db ...`).
RUN apt-get update && apt-get install -y --no-install-recommends git sqlite3 \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies in their own layer so source edits don't bust the cache.
# uv.lock is optional (glob): with it, builds are reproducible (--frozen);
# without it, uv resolves at build time and writes a lock inside the image.
COPY pyproject.toml uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --no-dev --no-install-project --frozen; \
    else \
        uv sync --no-dev --no-install-project; \
    fi

COPY src/ src/
COPY scripts/ scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --no-dev --frozen; \
    else \
        uv sync --no-dev; \
    fi

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["s7bb-service"]
