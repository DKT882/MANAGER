# ==============================================================================
# Multi-stage / Ultra-Minimal Container for Render & Cloud Environments
# ==============================================================================
FROM python:3.11-slim

# Memory & I/O optimization flags for low-RAM hosts (e.g. Render 512MB RAM)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_TRIM_THRESHOLD_=100000 \
    MALLOC_ARENA_MAX=2 \
    PORT=10000

WORKDIR /app

# Install build dependencies for C-extensions (uvloop) and clean up apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies without caching wheels
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Run as non-privileged system user for cloud security
RUN useradd -u 1000 -m appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose Render HTTP health check port
EXPOSE 10000

# Launch high-speed bot engine
CMD ["python", "bot.py"]
