FROM python:3.13.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    PQS_DATA_DIR=/app/data \
    PQS_PHASE3_STATE_DIR=/app/state

WORKDIR /app

RUN groupadd --system --gid 10001 pqs \
    && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin pqs

COPY pyproject.toml requirements.txt ./
COPY deployment/requirements-runtime.lock ./deployment/requirements-runtime.lock
COPY core ./core
COPY scripts ./scripts
COPY config ./config
COPY research/registry ./research/registry
COPY research/registries ./research/registries
COPY research/results/phase2 ./research/results/phase2

RUN python -m pip install --no-cache-dir -r deployment/requirements-runtime.lock \
    && python -m pip install --no-cache-dir --no-deps . \
    && python scripts/freeze_phase3_strategy.py verify \
    && mkdir -p /app/data /app/state /app/reports /app/logs \
    && chown -R 10001:10001 /app/data /app/state /app/reports /app/logs \
    && chmod -R a-w /app/core /app/scripts /app/config /app/research \
    && chmod 0755 /app/data /app/state /app/reports /app/logs

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "scripts/phase3_liveness.py", "--heartbeat", "/app/state/supervisor_heartbeat.json", "--maximum-age-seconds", "180"]

ENTRYPOINT ["python", "scripts/phase3_entrypoint.py"]

# Monitor-only by default. Market events require explicit run_forward_paper
# commands and immutable event metadata; no LIVE/broker-write entrypoint exists.
CMD ["python", "scripts/phase3_supervisor.py", "--state-dir", "/app/state", "--heartbeat", "/app/state/supervisor_heartbeat.json", "--interval-seconds", "60"]
