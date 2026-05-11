# dbt-core runner for the MLOps local template.
#
# Same image runs:
#   * dbt run / dbt test against Floci RDS Postgres
#   * pipelines/seed_s3.py            (Makefile `seed` target)
#   * pipelines/load_s3_to_rds.py     (Makefile `load-rds` target)
#   * pipelines/train.py              (Makefile `train` target — created by mlops-engineer Phase B)
#
# The service is invoked via `docker compose run --rm dbt ...`, never as a
# long-running daemon, so the default CMD just keeps the image valid.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DBT_PROFILES_DIR=/workspace/dbt

# Build deps for psycopg2-binary aren't strictly required (wheel ships),
# but libpq is handy for psql-based debugging from inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        postgresql-client \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/dbt

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Service is run via `docker compose run`, not as a daemon — keep it idle
# if someone does `docker compose up dbt` (e.g. via the `tools` profile).
CMD ["tail", "-f", "/dev/null"]
