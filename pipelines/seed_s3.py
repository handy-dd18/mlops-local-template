"""Upload the local Telco-churn CSV into the Floci S3 raw bucket.

Idempotent: re-running overwrites the same key. Creates the bucket if
Terraform hasn't (it should have, but be defensive — the script may run
before `make tf-apply` in some workflows).

Resolution order for connection params:
  RAW_BUCKET           default: raw-data
  S3_ENDPOINT_URL      preferred
  MLFLOW_S3_ENDPOINT_URL  fallback
  AWS_*                standard boto3 env vars

Source CSV path can be overridden via LOCAL_CSV; defaults to
/workspace/data/raw/customer_churn.csv (the bind-mounted location
inside the dbt container).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


# --- Config (env-driven) ----------------------------------------------------

DEFAULT_LOCAL_CSV = "/workspace/data/raw/customer_churn.csv"
DEFAULT_KEY = "customer_churn/customer_churn.csv"


def _endpoint_url() -> str:
    return (
        os.environ.get("S3_ENDPOINT_URL")
        or os.environ.get("MLFLOW_S3_ENDPOINT_URL")
        or "http://floci:4566"
    )


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=_endpoint_url(),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        # Path-style addressing is required by Floci/LocalStack.
        config=Config(s3={"addressing_style": "path"}),
    )


def ensure_bucket(s3, bucket: str) -> None:
    """Create the bucket if it doesn't already exist. Tolerant of
    "already owned by you" / "already exists" errors that fire when
    Terraform has provisioned the bucket first."""
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"[seed_s3] bucket '{bucket}' already exists.")
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"404", "NoSuchBucket", "NotFound"}:
            # Some other failure (auth, endpoint) — surface it.
            raise

    print(f"[seed_s3] creating bucket '{bucket}'...")
    try:
        s3.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            print(f"[seed_s3] bucket creation race ignored ({code}).")
        else:
            raise


def upload_csv(s3, bucket: str, local_path: Path, key: str) -> None:
    if not local_path.exists():
        raise FileNotFoundError(
            f"Local CSV not found at {local_path}. "
            "Generate it first (e.g. `make generate-data` once "
            "scripts/generate_sample_data.py exists)."
        )
    print(f"[seed_s3] uploading {local_path} -> s3://{bucket}/{key}")
    s3.upload_file(str(local_path), bucket, key)


def list_bucket(s3, bucket: str) -> None:
    print(f"[seed_s3] contents of s3://{bucket}/:")
    resp = s3.list_objects_v2(Bucket=bucket)
    for obj in resp.get("Contents", []):
        print(f"  {obj['Key']:50s}  {obj['Size']:>10d}  {obj['LastModified']}")
    if "Contents" not in resp:
        print("  (empty)")


def main() -> int:
    bucket = os.environ.get("RAW_BUCKET", "raw-data")
    local_csv = Path(os.environ.get("LOCAL_CSV", DEFAULT_LOCAL_CSV))
    key = os.environ.get("RAW_KEY", DEFAULT_KEY)

    print(f"[seed_s3] endpoint = {_endpoint_url()}")
    print(f"[seed_s3] bucket   = {bucket}")

    s3 = _s3_client()
    ensure_bucket(s3, bucket)
    upload_csv(s3, bucket, local_csv, key)
    list_bucket(s3, bucket)
    print("[seed_s3] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
