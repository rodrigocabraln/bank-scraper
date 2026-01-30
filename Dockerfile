# Dockerfile
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOZ_HEADLESS=1

# Dependencias: Firefox ESR + libs + fonts
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      firefox-esr \
      ca-certificates \
      curl \
      gnupg \
      unzip \
      xvfb \
      libgtk-3-0 \
      libdbus-glib-1-2 \
      libx11-xcb1 \
      libxcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxfixes3 \
      libxrandr2 \
      libasound2 \
      libatk1.0-0 \
      libcairo2 \
      libcups2 \
      libdrm2 \
      libgbm1 \
      libglib2.0-0 \
      libnss3 \
      libpango-1.0-0 \
      libpangocairo-1.0-0 \
      libxshmfence1 \
      fonts-liberation \
      fontconfig \
      cron \
      wget \
 && rm -rf /var/lib/apt/lists/*

# Install Geckodriver (Fixed version or dynamic)
# Instala geckodriver (versión fija para estabilidad)
ARG GECKODRIVER_VERSION=0.36.0
RUN arch="$(dpkg --print-architecture)" \
 && case "$arch" in \
      amd64) gd_arch="linux64" ;; \
      arm64) gd_arch="linux-aarch64" ;; \
      *) echo "Arquitectura no soportada: $arch" && exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/geckodriver.tar.gz \
      "https://github.com/mozilla/geckodriver/releases/download/v${GECKODRIVER_VERSION}/geckodriver-v${GECKODRIVER_VERSION}-${gd_arch}.tar.gz" \
 && tar -xzf /tmp/geckodriver.tar.gz -C /usr/local/bin \
 && rm /tmp/geckodriver.tar.gz \
 && chmod +x /usr/local/bin/geckodriver

# Create app user
RUN useradd -m appuser

WORKDIR /app

# Install python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Permissions
RUN chown -R appuser:appuser /app

USER appuser

# Entrypoint
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "scheduler.py"]
