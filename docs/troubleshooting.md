# Troubleshooting

Each entry: **Symptom** → **Cause** → **Fix**. Three lines max. If your error isn't here, check `make logs` first, then `docker compose ps`.

---

## Stack startup

### Floci doesn't start / "port 4566 already in use"

- **Symptom:** `make up` fails with `Bind for 0.0.0.0:4566 failed: port is already allocated`, or `floci` exits immediately.
- **Cause:** Another LocalStack/Floci instance (or anything else) is already bound to the host port.
- **Fix:** `lsof -iTCP:4566 -sTCP:LISTEN` (or `ss -ltnp | grep 4566`) to find the offender; either kill it, or set `FLOCI_PORT=4567` in `.env` and `make down && make up`.

### Floci healthcheck fails / image lacks `curl`

- **Symptom:** `docker compose ps` shows `floci` as `unhealthy` even though the API responds; or `make up` hangs on Floci start.
- **Cause:** The healthcheck in `docker-compose.yml` curls `http://localhost:4566/_localstack/health` — some Floci builds don't ship `curl`.
- **Fix:** Comment out the `floci.healthcheck` block in `docker-compose.yml` (the comment in that file already calls this out), then `make down && make up`.

### `terraform apply` fails with "connection refused" to localhost:4566

- **Symptom:** `make tf-apply` errors with `dial tcp 127.0.0.1:4566: connect: connection refused` or `RequestError: send request failed`.
- **Cause:** Floci isn't healthy yet (the AWS provider tries to reach it before the container is ready).
- **Fix:** `docker compose ps` and confirm `floci` is `running`/`healthy`; tail with `docker compose logs floci`; re-run `make tf-apply` once it settles.

### WSL2 volume permission errors (Postgres "could not write file ... Permission denied")

- **Symptom:** `mlflow-backend-db` exits with `chown: changing ownership of '/var/lib/postgresql/data': Operation not permitted` or `FATAL: data directory ... has wrong ownership`.
- **Cause:** WSL2 bind mounts default to root ownership; the postgres image runs as UID 999.
- **Fix:** `sudo chown -R 999:999 ./volumes/mlflow-backend-db` (and similar for `./volumes/floci-storage` if Floci complains), then `make down && make up`.

### Jupyter login token mismatch / browser asks for token even though `.env` has one

- **Symptom:** Visiting `http://localhost:8888` prompts for a token that `mlops` (or your custom `JUPYTER_TOKEN`) doesn't accept.
- **Cause:** The container started before `.env` was edited, or compose didn't pick up the new value.
- **Fix:** `make down && make up` (compose only re-reads `.env` on container creation). The token is the value of `JUPYTER_TOKEN` in `.env`.

---

## Pipeline / data layer

### MLflow run logs but artifacts are missing in the UI

- **Symptom:** Runs appear in MLflow, parameters/metrics are there, but the "Artifacts" tab is empty or model loading fails with "no such file".
- **Cause:** The client process doesn't have `MLFLOW_S3_ENDPOINT_URL=http://floci:4566` set, so boto3 talks to real AWS instead of Floci.
- **Fix:** Run via `make train` (the `dbt` service has it set in `docker-compose.yml`); from a notebook, restart the kernel after editing `.env` so the new env reaches the python process.

### dbt connection refused on port 4510

- **Symptom:** `make dbt-run` fails with `connection to server at "floci" (...), port 4510 failed: Connection refused`.
- **Cause:** Floci RDS hasn't been provisioned — `terraform apply` hasn't been run yet, or `make tf-destroy` wiped it.
- **Fix:** `make tf-init && make tf-apply`, wait for the RDS resource to come up, then re-run `make dbt-run`. The well-known port is 4510; do not use 4566 for Postgres.

### `load_s3_to_rds.py` fails on Glue `GetTable`

- **Symptom:** `make load-rds` errors with `EntityNotFoundException: ... Table customer_churn not found` (or similar) from `glue.get_table(...)`.
- **Cause:** Terraform hasn't been applied (the Glue DB/table doesn't exist) or `GLUE_DATABASE_NAME` is overridden to a non-existent DB.
- **Fix:** `make tf-apply`; confirm with `terraform -chdir=infra/terraform output -raw glue_database_name` (should be `mlops_raw`). If you've changed the DB name, set `GLUE_DATABASE_NAME` to match in your env.

### `load_s3_to_rds.py` fails with `No objects found under s3://raw-data/customer_churn/`

- **Symptom:** Error in `make load-rds` after a successful Glue lookup, complaining about an empty S3 prefix.
- **Cause:** `make seed` was skipped, or `seed_s3.py` uploaded under a different prefix.
- **Fix:** `make seed` first; the loader expects the CSV at `s3://${RAW_BUCKET}/customer_churn/`.

### Repeated `make dbt-run` leaves stale data

- **Symptom:** dbt runs cleanly but `marts.customer_features` doesn't reflect new rows you just loaded into `raw.customer_churn`.
- **Cause:** `customer_features` is materialised as a `table` (per `dbt_project.yml`); dbt rebuilds it each run, but the *source* is read at run time. If you forgot to re-run `load-rds`, dbt reads the same source. Confusion also comes from the staging `view` caching nothing — it always reflects current source.
- **Fix:** `make load-rds && make dbt-run`. To force dbt to rebuild from a clean slate (drops `marts.customer_features` and recreates), run `docker compose run --rm dbt dbt run --full-refresh`.

---

## Known issues (do not fix here — track and address in code)

These were flagged by other agents during build. They are real but **left as-is** by docs-writer; fix in the appropriate source file.

### dbt-core resolves to 1.11.9, not the 1.10.x line

- **Symptom:** `pip show dbt-core` inside the dbt container reports `1.11.9` even though `dbt/requirements.txt` pins `dbt-postgres==1.10.0`.
- **Cause:** dbt-postgres 1.10.0 transitively depends on a dbt-adapters version that requires dbt-core 1.11.x (protobuf 6.x). The older dbt-core 1.10 line is incompatible. See the comment in `dbt/requirements.txt`.
- **Fix:** None — this is intentional. Don't pin dbt-core to 1.10 unless you also downgrade dbt-postgres and the adapters in lockstep.

### `total_charges` is NULL for rows where `tenure = 0`

- **Symptom:** `marts.customer_features.total_charges` (and derived `charges_per_month_of_tenure`) is NULL for brand-new customers, and the `not_null` test on `total_charges` would fail if added.
- **Cause:** The Telco-churn CSV ships whitespace-only `total_charges` for `tenure=0` customers; staging's `nullif(trim(...), '')::numeric` correctly produces NULL. The marts spend-ratio columns explicitly guard `tenure=0`.
- **Fix:** None — this is expected. `dbt/models/staging/schema.yml` deliberately does not assert `not_null` on `total_charges`. Downstream code (e.g. `train.py`) imputes via `SimpleImputer(strategy="median")`.

### `accepted_values` test on boolean `churn` requires `quote: false`

- **Symptom:** `dbt test` errors on the `accepted_values` test for `stg_customer_churn.churn` if you write `values: ['true', 'false']`.
- **Cause:** dbt's default `accepted_values` quotes the values as strings, but `churn` is a Postgres `boolean` after staging coerces it.
- **Fix:** Already applied in `dbt/models/staging/schema.yml`: `accepted_values: arguments: { values: [true, false], quote: false }`. Don't "fix" it back to quoted strings.

---

## A few command snippets that pay off

```bash
# Watch one service's logs
docker compose logs -f floci

# Open a psql shell against Floci RDS from the host (requires psql installed)
PGPASSWORD=mlops psql -h localhost -p 4510 -U mlops -d mlops

# Open a shell inside the dbt container
docker compose run --rm dbt bash

# Force a clean dbt rebuild
docker compose run --rm dbt dbt run --full-refresh

# Inspect what's in S3 / Glue without leaving the host
docker compose run --rm dbt python -c "import boto3; print(boto3.client('s3', endpoint_url='http://floci:4566').list_buckets())"
```
