FROM python:3.12-slim

# Install MLflow tracking server with PostgreSQL backend + S3 (Floci) artifact store.
# Backend DB readiness is handled by docker-compose `depends_on: service_healthy`
# combined with `restart: unless-stopped`, so no entrypoint wait script is needed.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

EXPOSE 5000

# Use shell form so $MLFLOW_BACKEND_STORE_URI / $MLFLOW_DEFAULT_ARTIFACT_ROOT
# (set by docker-compose) expand at container start.
#
# MLflow 3.x ships a Host-header allowlist (DNS-rebinding protection). Inside
# the docker network clients connect via `http://mlflow:5000`, so we must
# explicitly allow that hostname plus localhost/127.0.0.1 for host-side curls.
# Override via $MLFLOW_ALLOWED_HOSTS if needed.
CMD mlflow server \
    --host 0.0.0.0 --port 5000 \
    --backend-store-uri "$MLFLOW_BACKEND_STORE_URI" \
    --default-artifact-root "$MLFLOW_DEFAULT_ARTIFACT_ROOT" \
    --serve-artifacts \
    --allowed-hosts "${MLFLOW_ALLOWED_HOSTS:-mlflow,mlflow:*,localhost,localhost:*,127.0.0.1,127.0.0.1:*,0.0.0.0,0.0.0.0:*}"
