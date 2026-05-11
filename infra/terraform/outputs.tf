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
  description = "Hostname clients should connect to. Inside the docker network this is the Floci service name."
  value       = "floci"
}

output "rds_port" {
  description = "Postgres port exposed by Floci. LocalStack/Floci default for Postgres is 4510."
  value       = 4510
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
  value       = "jdbc:postgresql://floci:4510/${aws_db_instance.mlops.db_name}"
}
