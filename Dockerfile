# FastAPI + the Expo web export, one image, for Cloud Run.
# The web build is copied into ./web by the deploy step (cloudbuild.yaml, or
# the manual `cp` in DEPLOY_GCP.md). If ./web is empty the container just
# serves the API.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

# Cloud Run sets $PORT (8080 by default). exec so uvicorn is PID 1 and gets SIGTERM.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
