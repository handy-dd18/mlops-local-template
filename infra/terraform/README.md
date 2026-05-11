# Terraform — Floci-emulated AWS stack

Provisions the local-AWS resources for this template:

- **S3**: `raw-data`, `mlflow-artifacts`
- **Glue Catalog**: database `mlops_raw`, table `customer_churn` (Telco schema, all-string columns, OpenCSVSerde, `skip.header.line.count = 1`)
- **RDS Postgres**: `mlops` database, master user `mlops`, engine `postgres 16`, `db.t3.micro`

No Glue Crawler — the schema is declared in `glue.tf`.

## Run from the host

Floci must be up first (`make up`). Then:

```bash
make tf-init     # cd infra/terraform && terraform init
make tf-apply    # cd infra/terraform && terraform apply -auto-approve
```

Defaults assume `floci_endpoint = http://localhost:4566` (host-side).

## Run from inside the docker network

Override the endpoint:

```bash
TF_VAR_floci_endpoint=http://floci:4566 terraform apply -auto-approve
```

## Outputs

```bash
terraform -chdir=infra/terraform output -raw raw_bucket_name
terraform -chdir=infra/terraform output -raw mlflow_artifacts_bucket_name
terraform -chdir=infra/terraform output -raw glue_database_name
terraform -chdir=infra/terraform output -raw glue_customer_churn_table_name
terraform -chdir=infra/terraform output -raw rds_host         # "floci"
terraform -chdir=infra/terraform output       rds_port         # 4510
terraform -chdir=infra/terraform output -raw rds_db_name
terraform -chdir=infra/terraform output -raw rds_username
terraform -chdir=infra/terraform output -raw rds_password      # sensitive
terraform -chdir=infra/terraform output -raw rds_jdbc_url
```

## Gotchas

- **RDS port is 4510, not 4566.** Floci routes Postgres on its engine-specific port, matching the LocalStack convention. The `rds_endpoint` output is whatever the Floci API reports — it may not be reachable directly. Use `rds_host` / `rds_port` / `rds_jdbc_url` instead.
- **Glue table location format**: `s3://raw-data/customer_churn/` (trailing slash). The `seed_s3.py` uploader must put CSVs under that prefix.
- **All Glue columns are `string`.** OpenCSVSerde does not support non-string columns; downstream loaders cast as needed.
- **`AWS_PROFILE` etc.** are ignored — the provider uses the hard-coded `test/test` credentials so a polluted host AWS profile cannot accidentally target real AWS.
- **State is local.** `.terraform/`, `*.tfstate`, and `.terraform.lock.hcl` are gitignored. Re-running `terraform apply` after `make nuke` (which wipes Floci storage) will fail with stale state — `make tf-destroy` first, or delete the local state files.
