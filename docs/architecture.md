# Architecture and design decisions

This document captures the *why* behind the shape of the stack. The README shows what runs and how to use it; this page exists so a future contributor doesn't have to re-derive the trade-offs from scratch.

---

## One MLflow server, shared by DS and engineers

Both tracks log to the **same** MLflow server (`http://mlflow:5000`). Segregation is by **experiment name**:

- `notebook-exploration` — set in `notebooks/01_explore.ipynb`. Anything ad-hoc the DS does in Jupyter.
- `pipeline-production` — set in `pipelines/train.py`. Anything coming out of the engineer pipeline.

Why one server instead of two:

- A single MLflow UI is the closest thing this template has to a "home page" — having two would dilute that.
- The DS-vs-engineer boundary is a workflow distinction, not a deployment one. If a DS notebook becomes a pipeline, it should keep its history; promoting an experiment from one server to another would be a chore.
- Operationally simpler: one Postgres backend, one artifact bucket, one set of port mappings.

The convention to enforce: **always set `mlflow.set_experiment(...)` explicitly in code.** The default experiment is reserved for "I forgot to set one" and should stay empty.

## MLflow backend DB is separate from the Floci-emulated RDS

There are two Postgres instances in the stack:

1. `mlflow-backend-db` — `postgres:16-alpine`, holds MLflow's internal store (`MLFLOW_BACKEND_STORE_URI`). Container-local, never touched by user code.
2. The Floci RDS Postgres at `floci:4510` — what `pipelines/load_s3_to_rds.py`, dbt, and `pipelines/train.py` talk to.

Why not collapse them onto the Floci RDS:

- **Failure isolation.** Floci is the part of the stack most likely to break (LocalStack-style emulators are flakier than a real Postgres image). When that happens, MLflow stays up and you can still browse past runs while you debug.
- **Lifecycle independence.** `make tf-destroy` and `make nuke` periodically wipe the Floci side. If MLflow lived on the same DB, every reset would also nuke run history.
- **Port hygiene.** MLflow's DB never needs to be reachable from the host; the Floci RDS does. Putting them on different containers makes the port mapping obvious.

Cost: an extra ~50 MB of RAM. Worth it.

## No Glue Crawler — Terraform-declared Glue Tables instead

Glue Crawlers are not reliably emulated by Floci/LocalStack (they require the Glue *jobs* runtime, not just the catalog API). Rather than work around that, the schema is declared inline in `infra/terraform/glue.tf` as an `aws_glue_catalog_table`.

Consequences and conventions:

- The Glue table is the **canonical schema definition**. `pipelines/load_s3_to_rds.py` calls `glue.get_table(...)` at runtime to learn the column list and the S3 location — adding a column means editing `glue.tf` and re-running `terraform apply`, after which the loader picks it up automatically.
- All columns are typed `string` because OpenCSVSerde does not support non-string Glue columns. Casting happens downstream in `dbt/models/staging/stg_customer_churn.sql`.
- `dbt/models/sources.yml` mirrors the Glue column list for documentation / `dbt docs` purposes only — dbt itself reads from RDS, not Glue.

If you ever swap Floci for real AWS, dropping in a Crawler becomes optional, not required.

## dbt uses the `postgres` adapter, not a Glue/Athena adapter

dbt's target is **always RDS Postgres** — that's where staging views and marts tables get materialised, and where `train.py` reads from. Glue only stores raw-layer metadata; nothing in dbt queries Glue directly.

Why:

- dbt-postgres is mature, fast, and works inside a single container with no extra services. dbt-glue / dbt-athena would pull in the Spark/Athena runtime, which Floci can't emulate at all.
- The S3 → RDS load is one cheap script (`load_s3_to_rds.py`); doing it once and then letting dbt operate on Postgres is much simpler than wiring dbt to read CSVs through a metastore.
- It mirrors a realistic small-team setup: data lands in object storage, gets ingested into a warehouse, dbt models the warehouse.

If the source-of-truth schema lives in Glue but dbt reads Postgres, the loader script is the **bridge** between them. Keep it small and dumb.

## Bind mounts under `./volumes/`, not Docker named volumes

All persistent state is bind-mounted into `./volumes/` on the host:

- `./volumes/mlflow-backend-db/` — MLflow's Postgres data dir.
- `./volumes/floci-storage/` — Floci's S3/Glue/RDS state.

Why bind mounts instead of `docker volume create ...`:

- **Transparency for DS.** A data scientist can `ls ./volumes/floci-storage/` and see actual files. Named volumes hide everything inside `/var/lib/docker/volumes/` where it's effectively unreachable on macOS / Windows / WSL2.
- **Easy reset by hand.** `rm -rf ./volumes/floci-storage` is more obvious than `docker volume rm <hash>`.
- **`make nuke` doesn't blow away the bind mounts** (it removes only Docker-managed volumes), which is intentional — we want explicit deletion to be a separate, conscious step.

The cost is WSL2 permission issues (see `docs/troubleshooting.md`); we accept that in exchange for the visibility.

## Out of scope (intentionally)

This template is deliberately small. The following are **not** here and won't be added:

- **CI / CD.** No GitHub Actions, no test orchestration. The whole point is that everything runs locally.
- **SaaS integrations.** No real AWS, no managed MLflow, no Snowflake/Databricks/etc. If you need those, fork.
- **Multi-node / distributed training.** Single-process scikit-learn is the ceiling.
- **GPU support.** All images are CPU-only.
- **Authentication / multi-user MLflow.** MLflow is single-user, no auth.
- **Production-grade Postgres tuning, backups, replication.** Both Postgres instances run with stock configs.
- **Schema migration tooling.** `load_s3_to_rds.py` does `if_exists='replace'` because raw is regenerable from S3; dbt handles everything downstream of that.

If you find yourself wanting one of these, it's a sign the project has outgrown this template — copy it out and graduate.
