###############################################################################
# Provider — AWS pointed at the Floci emulator
#
# Every endpoint is overridden to `var.floci_endpoint` so the provider talks
# to Floci/LocalStack instead of real AWS. The skip_* flags suppress STS /
# IMDS / account-id lookups that Floci does not implement faithfully.
###############################################################################

provider "aws" {
  region     = var.aws_region
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key

  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3   = var.floci_endpoint
    glue = var.floci_endpoint
    rds  = var.floci_endpoint
    iam  = var.floci_endpoint
    sts  = var.floci_endpoint
  }
}
