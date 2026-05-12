"""Idempotently create the Glue Catalog Database + customer_churn Table.

Floci's Glue API does not implement `GetTags` for Catalog Databases, which
breaks the AWS Terraform provider's post-create read step. To keep
`terraform apply` clean, the Glue resources are managed here via boto3
(which does not call GetTags).

This script is safe to run repeatedly:
  - If the database exists, the AlreadyExistsException is caught.
  - If the table exists, it is deleted and recreated so any schema
    change in this file takes effect.

Usage:
    python pipelines/setup_glue.py
    # or via the Makefile:
    make glue-setup

It is also invoked automatically by `pipelines/load_s3_to_rds.py` so the
loader is self-sufficient.
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError


GLUE_DB = os.environ.get("GLUE_DATABASE_NAME", "mlops_raw")
GLUE_TABLE = os.environ.get("GLUE_TABLE_NAME", "customer_churn")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "raw-data")

# Telco-churn schema. All columns are `string`; cast downstream in dbt staging.
COLUMNS = [
    "customer_id", "gender", "senior_citizen", "partner", "dependents",
    "tenure", "phone_service", "multiple_lines", "internet_service",
    "online_security", "online_backup", "device_protection", "tech_support",
    "streaming_tv", "streaming_movies", "contract_type", "paperless_billing",
    "payment_method", "monthly_charges", "total_charges", "churn",
]


def _endpoint_url() -> str:
    return (
        os.environ.get("S3_ENDPOINT_URL")
        or os.environ.get("MLFLOW_S3_ENDPOINT_URL")
        or "http://floci:4566"
    )


def _glue_client():
    return boto3.client(
        "glue",
        endpoint_url=_endpoint_url(),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )


def ensure_database(glue) -> None:
    try:
        glue.create_database(
            DatabaseInput={
                "Name": GLUE_DB,
                "Description": (
                    "Raw-layer metadata for the MLOps local template. "
                    "Managed by pipelines/setup_glue.py, not by a Crawler."
                ),
            }
        )
        print(f"[glue] created database {GLUE_DB!r}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "AlreadyExistsException":
            print(f"[glue] database {GLUE_DB!r} already exists")
        else:
            raise


def ensure_table(glue) -> None:
    table_input = {
        "Name": GLUE_TABLE,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {
            "classification": "csv",
            "skip.header.line.count": "1",
            "delimiter": ",",
            "has_encrypted_data": "false",
        },
        "StorageDescriptor": {
            "Location": f"s3://{RAW_BUCKET}/customer_churn/",
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
            "SerdeInfo": {
                "Name": "customer_churn_csv_serde",
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
                "Parameters": {
                    "separatorChar": ",",
                    "quoteChar": "\"",
                    "escapeChar": "\\",
                },
            },
            "Columns": [{"Name": c, "Type": "string"} for c in COLUMNS],
        },
    }

    try:
        glue.delete_table(DatabaseName=GLUE_DB, Name=GLUE_TABLE)
        print(f"[glue] deleted existing table {GLUE_DB}.{GLUE_TABLE} (will recreate)")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("EntityNotFoundException",):
            raise

    glue.create_table(DatabaseName=GLUE_DB, TableInput=table_input)
    print(f"[glue] created table {GLUE_DB}.{GLUE_TABLE} at s3://{RAW_BUCKET}/customer_churn/")


def main() -> int:
    print(f"[glue] endpoint = {_endpoint_url()}")
    glue = _glue_client()
    ensure_database(glue)
    ensure_table(glue)
    print("[glue] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
