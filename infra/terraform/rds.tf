###############################################################################
# RDS Postgres on Floci
#
# Floci exposes the engine-specific port (Postgres → 4510) on the same host
# as the gateway (4566). The `address`/`port` attributes returned by the API
# may not reflect this reliably; outputs.tf hard-codes the well-known port.
###############################################################################

resource "aws_db_instance" "mlops" {
  identifier = var.rds_identifier

  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  allocated_storage = var.rds_allocated_storage

  db_name  = var.rds_db_name
  username = var.rds_username
  password = var.rds_password

  skip_final_snapshot = true
  publicly_accessible = true

  # Floci does not enforce these, but supplying them keeps the AWS provider
  # from complaining about apply-time diffs.
  apply_immediately   = true
  deletion_protection = false
}
