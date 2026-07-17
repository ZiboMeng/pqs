FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PQS_DATA_DIR=/app/data

WORKDIR /app

RUN groupadd --system pqs && useradd --system --gid pqs --home /app pqs

COPY pyproject.toml requirements.txt ./
COPY core ./core
COPY scripts ./scripts
COPY config ./config

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && mkdir -p /app/data /app/reports /app/logs \
    && chown -R pqs:pqs /app

USER pqs

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "scripts/health_check.py", "--config-dir", "config"]

# Safe default: inspect local paper state. No broker-connected LIVE command is
# present in this image and runtime.live_enabled remains false in config.
CMD ["python", "scripts/run_paper.py", "--mode", "status", "--db-path", "/app/data/paper_trading/pt.db"]
