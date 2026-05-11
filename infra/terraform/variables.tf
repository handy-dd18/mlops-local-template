###############################################################################
# Input variables
#
# All defaults match `.env.example`. Override via `-var` / `*.tfvars` / env
# vars (`TF_VAR_floci_endpoint=...`) when running from inside the docker
# network.
###############################################################################

variable "floci_endpoint" {
  description = "Base URL of the Floci emulator. Use http://localhost:4566 from the host, http://floci:4566 from inside the docker network."
  type        = string
  default     = "http://localhost:4566"
}

variable "aws_region" {
  description = "AWS region. Floci accepts anything; us-east-1 keeps Glue/S3 happiest."
  type        = string
  default     = "us-east-1"
}

variable "aws_access_key" {
  description = "Dummy access key for Floci. Must be non-empty."
  type        = string
  default     = "test"
}

variable "aws_secret_key" {
  description = "Dummy secret key for Floci. Must be non-empty."
  type        = string
  default     = "test"
  sensitive   = true
}

# ---------- S3 ----------------------------------------------------------------

variable "raw_bucket_name" {
  description = "Bucket for raw CSVs uploaded by seed_s3.py."
  type        = string
  default     = "raw-data"
}

variable "mlflow_artifacts_bucket_name" {
  description = "Bucket used by the MLflow server as its default artifact root."
  type        = string
  default     = "mlflow-artifacts"
}

# ---------- Glue --------------------------------------------------------------

variable "glue_database_name" {
  description = "Glue Catalog database holding raw-layer table metadata."
  type        = string
  default     = "mlops_raw"
}

# ---------- RDS Postgres ------------------------------------------------------

variable "rds_identifier" {
  description = "DB instance identifier (DNS-safe slug)."
  type        = string
  default     = "mlops-rds"
}

variable "rds_db_name" {
  description = "Initial Postgres database name."
  type        = string
  default     = "mlops"
}

variable "rds_username" {
  description = "Master username for the Postgres instance."
  type        = string
  default     = "mlops"
}

variable "rds_password" {
  description = "Master password for the Postgres instance."
  type        = string
  default     = "mlops"
  sensitive   = true
}

variable "rds_engine_version" {
  description = "Postgres engine version. Floci supports 15/16; stick to a major-only pin so Floci picks the latest patch."
  type        = string
  default     = "16"
}

variable "rds_instance_class" {
  description = "RDS instance class. Floci ignores it but the API requires a value."
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GiB."
  type        = number
  default     = 10
}
