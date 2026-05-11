###############################################################################
# Glue Catalog — database + customer_churn table
#
# No Glue Crawler. The Telco-churn schema is declared inline so dbt / Athena-
# style consumers can read it directly from the Catalog. All columns are typed
# `string`; downstream loaders (load_s3_to_rds.py) handle casting.
###############################################################################

resource "aws_glue_catalog_database" "mlops" {
  name        = var.glue_database_name
  description = "Raw-layer metadata for the MLOps local template. Populated by Terraform, not by a Crawler."
}

resource "aws_glue_catalog_table" "customer_churn" {
  name          = "customer_churn"
  database_name = aws_glue_catalog_database.mlops.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    "classification"         = "csv"
    "skip.header.line.count" = "1"
    "delimiter"              = ","
    "has_encrypted_data"     = "false"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.raw_data.bucket}/customer_churn/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      name                  = "customer_churn_csv_serde"
      serialization_library = "org.apache.hadoop.hive.serde2.OpenCSVSerde"

      parameters = {
        "separatorChar" = ","
        "quoteChar"     = "\""
        "escapeChar"    = "\\"
      }
    }

    # --- Telco-churn schema. All columns are `string`; cast downstream. ----
    columns {
      name = "customer_id"
      type = "string"
    }
    columns {
      name = "gender"
      type = "string"
    }
    columns {
      name = "senior_citizen"
      type = "string"
    }
    columns {
      name = "partner"
      type = "string"
    }
    columns {
      name = "dependents"
      type = "string"
    }
    columns {
      name = "tenure"
      type = "string"
    }
    columns {
      name = "phone_service"
      type = "string"
    }
    columns {
      name = "multiple_lines"
      type = "string"
    }
    columns {
      name = "internet_service"
      type = "string"
    }
    columns {
      name = "online_security"
      type = "string"
    }
    columns {
      name = "online_backup"
      type = "string"
    }
    columns {
      name = "device_protection"
      type = "string"
    }
    columns {
      name = "tech_support"
      type = "string"
    }
    columns {
      name = "streaming_tv"
      type = "string"
    }
    columns {
      name = "streaming_movies"
      type = "string"
    }
    columns {
      name = "contract_type"
      type = "string"
    }
    columns {
      name = "paperless_billing"
      type = "string"
    }
    columns {
      name = "payment_method"
      type = "string"
    }
    columns {
      name = "monthly_charges"
      type = "string"
    }
    columns {
      name = "total_charges"
      type = "string"
    }
    columns {
      name = "churn"
      type = "string"
    }
  }
}
