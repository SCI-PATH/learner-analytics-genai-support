# Learner Analytics GenAI Support — FastAPI backend
#
# Build from the repo root (so Data/ and requirements.txt are available):
#   docker build -f FastAPI-Backend/Dockerfile -t learner-analytics-be .
#
# Run (pass secrets via --env-file; do not bake .env into the image):
#   docker run --rm -p 8003:8003 --env-file .env learner-analytics-be
#
# API docs: http://127.0.0.1:8003/docs

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8003

# Build tools needed for pyBKT / scientific Python wheels on slim images
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        g++ \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
# Force CPU-only torch first so sentence-transformers does not pull multi-GB CUDA wheels
# (those fill small EC2 root volumes during docker pull/extract).
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu \
        "torch>=2.2,<3.0" \
    && pip install -r requirements.txt

# App code + data the backend resolves via PROJECT_ROOT
COPY FastAPI-Backend/ ./FastAPI-Backend/
COPY Data/ ./Data/

WORKDIR /app/FastAPI-Backend

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/docs" >/dev/null || exit 1

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
