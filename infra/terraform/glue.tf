###############################################################################
# Glue Catalog — managed outside Terraform.
#
# Floci's Glue API does not implement `GetTags` for Catalog Databases
# (returns `InvalidInputException: Resource ARN does not point to a Registry
# or Schema`). Terraform's AWS provider issues a `GetTags` call after every
# create / read, so `aws_glue_catalog_database` and `aws_glue_catalog_table`
# cannot be managed here without errors.
#
# Workaround: the Catalog Database and `customer_churn` Table are created
# idempotently by `pipelines/setup_glue.py` using boto3 directly (which does
# not call GetTags). That script runs as part of `make glue-setup` and is
# also invoked at the top of `pipelines/load_s3_to_rds.py` so the loader is
# self-sufficient.
#
# The names this module would have produced are surfaced as plain string
# outputs (see `outputs.tf`) for consumers that still want a single source
# of truth.
###############################################################################
