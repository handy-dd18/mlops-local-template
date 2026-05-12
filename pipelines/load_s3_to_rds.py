"""Load the customer_churn CSV from S3 into RDS Postgres `raw.customer_churn`.

The Glue Catalog is the source of truth for the column list and the S3
location of the CSV. This script:

  1. Calls Glue `get_table(DatabaseName='mlops_raw', Name='customer_churn')`
     to learn the column names + types and the storage location.
  2. Lists objects under that S3 prefix and downloads the first CSV
     (the seed_s3.py script writes a single file).
  3. Connects to the Floci RDS Postgres via SQLAlchemy.
  4. (Re)creates the `raw` schema and `raw.customer_churn` table with
     all columns typed as TEXT — type-casting happens in dbt staging.
  5. Bulk-inserts the rows via pandas.to_sql(if_exists='replace').
  6. Prints the resulting row count.

Idempotent: running twice leaves the same final state (the table is
fully replaced each time).
"""

from __future__ import annotations

import io
import os
import sys
from typing import List, Tuple
from urllib.parse import urlparse

import boto3
import pandas as pd
from botocore.client import Config
from sqlalchemy import create_engine, text


# --- Config (env-driven) ----------------------------------------------------

GLUE_DB = os.environ.get("GLUE_DATABASE_NAME", "mlops_raw")
GLUE_TABLE = os.environ.get("GLUE_TABLE_NAME", "customer_churn")

RAW_SCHEMA = os.environ.get("RAW_SCHEMA", "raw")
RAW_TABLE = os.environ.get("RAW_TABLE", "customer_churn")


def _endpoint_url() -> str:
    return (
        os.environ.get("S3_ENDPOINT_URL")
        or os.environ.get("MLFLOW_S3_ENDPOINT_URL")
        or "http://floci:4566"
    )


def _aws_kwargs() -> dict:
    return dict(
        endpoint_url=_endpoint_url(),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )


def _s3_client():
    return boto3.client(
        "s3",
        config=Config(s3={"addressing_style": "path"}),
        **_aws_kwargs(),
    )


def _glue_client():
    return boto3.client("glue", **_aws_kwargs())


def _rds_engine():
    host = os.environ.get("RDS_HOST", "floci")
    port = os.environ.get("RDS_PORT", "4510")
    user = os.environ.get("RDS_USER", "mlops")
    pw = os.environ.get("RDS_PASSWORD", "mlops")
    db = os.environ.get("RDS_DB", "mlops")
    url = f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{db}"
    print(f"[load] RDS url = postgresql+psycopg2://{user}:***@{host}:{port}/{db}")
    return create_engine(url, future=True)


# --- Glue ---------------------------------------------------------------------

def fetch_glue_metadata() -> Tuple[List[str], str]:
    """Return (column_names, s3_location) for the Glue table."""
    glue = _glue_client()
    print(f"[load] glue.get_table(DatabaseName={GLUE_DB!r}, Name={GLUE_TABLE!r})")
    resp = glue.get_table(DatabaseName=GLUE_DB, Name=GLUE_TABLE)
    table = resp["Table"]
    sd = table["StorageDescriptor"]
    columns = [c["Name"] for c in sd["Columns"]]
    location = sd["Location"]
    print(f"[load] glue: {len(columns)} columns; location = {location}")
    return columns, location


# --- S3 -----------------------------------------------------------------------

def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Expected s3:// URI, got {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")


def download_csv(s3_location: str) -> bytes:
    """List the s3 prefix and download the first .csv-looking object."""
    s3 = _s3_client()
    bucket, prefix = _parse_s3_uri(s3_location)
    if not prefix.endswith("/"):
        prefix += "/"
    print(f"[load] s3.list_objects_v2(Bucket={bucket!r}, Prefix={prefix!r})")
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    contents = resp.get("Contents", [])
    if not contents:
        raise FileNotFoundError(
            f"No objects found under s3://{bucket}/{prefix} — did you run `make seed`?"
        )
    # Prefer .csv keys; fall back to the first object if nothing matches.
    csv_keys = [obj["Key"] for obj in contents if obj["Key"].lower().endswith(".csv")]
    key = csv_keys[0] if csv_keys else contents[0]["Key"]
    print(f"[load] downloading s3://{bucket}/{key}")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    print(f"[load] downloaded {len(body):,} bytes")
    return body


# --- RDS ----------------------------------------------------------------------

def load_to_rds(engine, columns: List[str], csv_bytes: bytes) -> int:
    """Replace raw.<table> with the CSV data, all columns as TEXT."""
    # Read with all columns as strings to preserve raw fidelity. Skip
    # leading whitespace fields produced by the Telco source.
    df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False, na_values=[""])

    # Sanity-check: the CSV header should match the Glue schema. We
    # don't fail on mismatch (Glue is the spec) but we do warn so the
    # user knows the loader will reorder/realign.
    csv_cols = list(df.columns)
    if csv_cols != columns:
        print(
            f"[load] WARNING: CSV header {csv_cols} does not match Glue schema {columns}. "
            f"Aligning to Glue order; missing columns will be NULL."
        )
        # Reindex to Glue's column order; missing -> NaN.
        df = df.reindex(columns=columns)

    # Force every column to TEXT-compatible str/None.
    df = df.where(pd.notnull(df), None)

    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{RAW_SCHEMA}"'))
        # to_sql with if_exists='replace' drops the table, so the schema
        # we get is exactly the one pandas infers — but with dtype=str
        # everything maps to TEXT.
        df.to_sql(
            RAW_TABLE,
            con=conn,
            schema=RAW_SCHEMA,
            if_exists="replace",
            index=False,
            method="multi",
            chunksize=1000,
            dtype={col: __import__("sqlalchemy").types.Text() for col in df.columns},
        )

        row_count = conn.execute(
            text(f'SELECT COUNT(*) FROM "{RAW_SCHEMA}"."{RAW_TABLE}"')
        ).scalar_one()
    return int(row_count)


# --- Entrypoint ---------------------------------------------------------------

def main() -> int:
    print(f"[load] endpoint = {_endpoint_url()}")
    # The Glue Catalog DB+Table are managed outside Terraform (Floci limitation).
    # Make this script self-sufficient by ensuring they exist first.
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import setup_glue  # noqa: E402
    setup_glue.main()

    columns, location = fetch_glue_metadata()
    csv_bytes = download_csv(location)
    engine = _rds_engine()
    rows = load_to_rds(engine, columns, csv_bytes)
    print(f"[load] OK: {RAW_SCHEMA}.{RAW_TABLE} now has {rows:,} rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
