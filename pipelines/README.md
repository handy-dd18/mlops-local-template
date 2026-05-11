# pipelines/

Three small Python entrypoints that move data through the local stack
and produce an MLflow-tracked model. All scripts read connection
config from environment variables (defaults match `.env.example`).

| Script              | Owner role                  | Reads                                   | Writes                                                  |
| ------------------- | --------------------------- | --------------------------------------- | ------------------------------------------------------- |
| `seed_s3.py`        | data-pipeline-engineer      | `data/raw/customer_churn.csv`           | `s3://${RAW_BUCKET}/customer_churn/`                    |
| `load_s3_to_rds.py` | data-pipeline-engineer      | Glue table + S3 CSV                     | `raw.customer_churn` in Floci RDS Postgres              |
| `train.py`          | mlops-engineer              | `marts.customer_features` in Floci RDS  | MLflow run under experiment `pipeline-production`       |

End-to-end from a clean checkout:

```bash
make up                # bring stack online
make tf-apply          # provision S3 + Glue + RDS
make generate-data     # synth 7,000 rows -> data/raw/customer_churn.csv
make seed              # CSV -> S3
make load-rds          # S3 -> raw.customer_churn
make dbt-run           # build staging + marts.customer_features
make train             # train + log to MLflow
```

The `requirements.txt` here is duplicated into the dbt image; keep them
in sync if you bump a pin.
