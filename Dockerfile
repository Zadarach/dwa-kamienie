# ─────────────────────────────────────────────────────────
# Vinted-Notification — Dockerfile
# Real-time notifications for Vinted (all domains)
# Build: docker build -t vinted-notification .
# ─────────────────────────────────────────────────────────

FROM python:3.11-slim-bookworm

LABEL maintainer="Vinted-Notification"
LABEL description="Real-time Vinted listing notifications to Discord"

# Zmienne środowiskowe
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Katalog roboczy
WORKDIR /app

# Zainstaluj zależności systemowe (minimalne)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Kopiuj requirements i zainstaluj
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiuj kod aplikacji
COPY . .

# Utwórz katalog na dane
RUN mkdir -p data

# Eksponuj port panelu
EXPOSE 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/stats || exit 1

# Uruchom aplikację
CMD ["python", "main.py"]
