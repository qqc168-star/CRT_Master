FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CRT_RUNTIME_ROOT=/var/lib/crt-radar

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && useradd --create-home --uid 10001 crt
COPY CONFIG /app/CONFIG
COPY src /app/src
COPY scripts /app/scripts
RUN mkdir -p /var/lib/crt-radar && chown -R crt:crt /app /var/lib/crt-radar
USER crt
VOLUME ["/var/lib/crt-radar"]
ENTRYPOINT ["/app/scripts/run_live_shadow_24h.sh"]
