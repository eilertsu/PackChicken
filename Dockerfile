# syntax=docker/dockerfile:1

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PACKCHICKEN_GUI_PORT=5050 \
    LABEL_DIR=/app/LABELS \
    ORDERS_DIR=/app/ORDERS

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    pip install --no-cache-dir --upgrade pip && \
    apt-get purge -y gcc && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Kopier prosjektfiler
COPY pyproject.toml README.md uv.lock ./ 
COPY src ./src
COPY scripts ./scripts

# Lag nødvendige mapper
RUN mkdir -p /app/ORDERS /app/LABELS /app/logs

# Installer avhengigheter
RUN pip install --no-cache-dir -e .

EXPOSE 5050

CMD ["python", "-m", "packchicken.gui.app"]
