###############################################################################
# S3 buckets
#
# Two buckets only. We deliberately skip ACL/versioning/policy resources —
# Floci ignores most of them and they only add noise during `terraform apply`.
###############################################################################

resource "aws_s3_bucket" "raw_data" {
  bucket        = var.raw_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket" "mlflow_artifacts" {
  bucket        = var.mlflow_artifacts_bucket_name
  force_destroy = true
}
