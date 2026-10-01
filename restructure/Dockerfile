FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: pypdf image extraction benefits from these libs; curl for health.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY orchestrator/requirements.txt /app/orchestrator/requirements.txt
RUN pip install -r /app/orchestrator/requirements.txt

COPY orchestrator /app/orchestrator
RUN chmod +x /app/orchestrator/entrypoint.sh

ENV INPUT_DIR=/inputs \
    OUTPUT_DIR=/outputs

ENTRYPOINT ["/app/orchestrator/entrypoint.sh"]
