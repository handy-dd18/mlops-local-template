###############################################################################
# Outputs
#
# Consumers (data-pipeline-engineer, dbt, seed scripts) read these via:
#   terraform -chdir=infra/terraform output -raw <name>
###############################################################################

output "raw_bucket_name" {
  description = "S3 bucket holding raw CSVs."
  value       = aws_s3_bucket.raw_data.bucket
}

output "mlflow_artifacts_bucket_name" {
  description = "S3 bucket used by the MLflow server as its artifact root."
  value       = aws_s3_bucket.mlflow_artifacts.bucket
}

output "glue_database_name" {
  description = "Glue Catalog database for raw-layer metadata."
  value       = aws_glue_catalog_database.mlops.name
}

output "glue_customer_churn_table_name" {
  description = "Glue Catalog table for the Telco-churn raw CSV."
  value       = aws_glue_catalog_table.customer_churn.name
}

output "rds_endpoint" {
  description = "Floci RDS Postgres endpoint reported by the API (host:port). Note: see rds_jdbc_url for the actually-reachable address from the docker network."
  value       = aws_db_instance.mlops.endpoint
}

output "rds_host" {
  description = "Hostname clients should connect to from inside mlops-net. Floci spawns a sibling Postgres container named floci-rds-<instance-id>; attach it to mlops-net with `make rds-attach`."
  value       = "floci-rds-mlops-rds"
}

output "rds_port" {
  description = "Postgres listens on its native 5432 inside the spawned RDS container (NOT the Floci-reported host port)."
  value       = 5432
}

output "rds_db_name" {
  description = "Initial Postgres database name."
  value       = aws_db_instance.mlops.db_name
}

output "rds_username" {
  description = "Master username for the Postgres instance."
  value       = aws_db_instance.mlops.username
}

output "rds_password" {
  description = "Master password for the Postgres instance."
  value       = aws_db_instance.mlops.password
  sensitive   = true
}

output "rds_jdbc_url" {
  description = "Convenience JDBC URL for dbt / pipeline consumers. Use from within the docker network."
  value       = "jdbc:postgresql://floci-rds-mlops-rds:5432/${aws_db_instance.mlops.db_name}"
}
