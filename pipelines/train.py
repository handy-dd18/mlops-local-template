"""Production-shaped churn training pipeline.

Reads the dbt marts table ``marts.customer_features`` from Floci RDS,
trains a logistic-regression classifier, evaluates on a held-out test
set, and logs everything to the MLflow experiment ``pipeline-production``.

Run end-to-end inside the dbt container, which already has Python +
psycopg2 + the right network access:

    docker compose run --rm dbt python /workspace/pipelines/train.py
    # or
    make train

Required env (all defaulted for the local stack):

    RDS_HOST       default floci
    RDS_PORT       default 4510
    RDS_USER       default mlops
    RDS_PASSWORD   default mlops
    RDS_DB         default mlops
    MLFLOW_TRACKING_URI   default http://mlflow:5000

Exits non-zero on any failure (data missing, MLflow unreachable, model
fit failure) so the pipeline is safe to wire into a scheduler.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import mlflow
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy import create_engine, text


# --- Config ----------------------------------------------------------------

EXPERIMENT_NAME = "pipeline-production"
FEATURES_SCHEMA = os.environ.get("MARTS_SCHEMA", "marts")
FEATURES_TABLE = os.environ.get("MARTS_TABLE", "customer_features")
TARGET_COL = "churn"
ID_COL = "customer_id"

# Numeric columns in marts.customer_features (per dbt schema).
NUMERIC_COLS = [
    "tenure",
    "monthly_charges",
    "total_charges",
    "charges_per_month_of_tenure",
    "lifetime_to_expected_ratio",
    "num_addon_services",
]

# Boolean columns that we treat as numeric 0/1 features.
BOOLEAN_COLS = [
    "senior_citizen",
    "partner",
    "dependents",
    "phone_service",
    "paperless_billing",
    "is_month_to_month",
]

# Categorical (string) columns to one-hot encode.
CATEGORICAL_COLS = [
    "gender",
    "multiple_lines",
    "internet_service",
    "online_security",
    "online_backup",
    "device_protection",
    "tech_support",
    "streaming_tv",
    "streaming_movies",
    "contract_type",
    "payment_method",
    "tenure_bucket",
]

SQL_TEMPLATE = """\
SELECT *
FROM {schema}.{table}
WHERE {target} IS NOT NULL
"""

LOG = logging.getLogger("train")


# --- DB connection ----------------------------------------------------------

@dataclass(frozen=True)
class RdsConfig:
    host: str
    port: str
    user: str
    password: str
    db: str

    @classmethod
    def from_env(cls) -> "RdsConfig":
        return cls(
            host=os.environ.get("RDS_HOST", "floci"),
            port=os.environ.get("RDS_PORT", "4510"),
            user=os.environ.get("RDS_USER", "mlops"),
            password=os.environ.get("RDS_PASSWORD", "mlops"),
            db=os.environ.get("RDS_DB", "mlops"),
        )

    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    def safe_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:***"
            f"@{self.host}:{self.port}/{self.db}"
        )


# --- Pipeline stages --------------------------------------------------------

def load_data(cfg: RdsConfig) -> tuple[pd.DataFrame, str]:
    """Pull ``marts.customer_features`` from RDS. Returns (df, sql)."""
    sql = SQL_TEMPLATE.format(
        schema=FEATURES_SCHEMA, table=FEATURES_TABLE, target=TARGET_COL
    )
    LOG.info("connecting to %s", cfg.safe_url())
    engine = create_engine(cfg.url(), future=True)
    with engine.connect() as conn:
        # Cheap existence probe so we fail fast with a clear message if
        # dbt hasn't been run yet.
        check_sql = text(
            "SELECT to_regclass(:rel) AS exists"
        )
        rel = f"{FEATURES_SCHEMA}.{FEATURES_TABLE}"
        if conn.execute(check_sql, {"rel": rel}).scalar_one() is None:
            raise RuntimeError(
                f"Table {rel} does not exist. Run `make seed`, `make load-rds`, "
                "and `make dbt-run` first."
            )
        LOG.info("running query:\n%s", sql.strip())
        df = pd.read_sql(text(sql), conn)
    LOG.info("loaded %d rows, %d columns from %s.%s",
             len(df), len(df.columns), FEATURES_SCHEMA, FEATURES_TABLE)
    if df.empty:
        raise RuntimeError(
            f"{FEATURES_SCHEMA}.{FEATURES_TABLE} returned 0 rows."
        )
    return df, sql


def _build_estimator() -> Pipeline:
    numeric_pipe = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
    ])
    categorical_pipe = Pipeline(steps=[
        ("impute", SimpleImputer(strategy="most_frequent")),
        ("ohe", OneHotEncoder(handle_unknown="ignore")),
    ])
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, NUMERIC_COLS + BOOLEAN_COLS),
            ("cat", categorical_pipe, CATEGORICAL_COLS),
        ],
        remainder="drop",
    )
    return Pipeline(steps=[
        ("prep", preprocessor),
        ("clf", LogisticRegression(max_iter=400, n_jobs=None)),
    ])


def _prepare_xy(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    y = df[TARGET_COL].astype(int)
    feature_cols = NUMERIC_COLS + BOOLEAN_COLS + CATEGORICAL_COLS
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"Marts table is missing expected columns: {missing}. "
            "Re-run dbt or update the train.py column lists."
        )
    # Cast booleans to int for the numeric branch of the ColumnTransformer.
    X = df[feature_cols].copy()
    for col in BOOLEAN_COLS:
        X[col] = X[col].astype("Int8")
    return X, y


def train(df: pd.DataFrame, seed: int = 42) -> tuple[Pipeline, pd.DataFrame, pd.Series]:
    """Fit the pipeline. Returns (fitted_pipe, X_test, y_test)."""
    X, y = _prepare_xy(df)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=seed, stratify=y
    )
    LOG.info("train shape=%s  test shape=%s", X_train.shape, X_test.shape)
    pipe = _build_estimator()
    pipe.fit(X_train, y_train)
    LOG.info("model fit complete")
    return pipe, X_test, y_test


def evaluate(pipe: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> dict[str, float]:
    proba = pipe.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)
    metrics = {
        "test_accuracy": float(accuracy_score(y_test, pred)),
        "test_f1": float(f1_score(y_test, pred)),
        "test_roc_auc": float(roc_auc_score(y_test, proba)),
    }
    LOG.info("eval metrics: %s", metrics)
    return metrics


# --- Entrypoint -------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    LOG.info("mlflow tracking_uri=%s experiment=%s", tracking_uri, EXPERIMENT_NAME)

    cfg = RdsConfig.from_env()

    with mlflow.start_run(run_name="train.py") as run:
        mlflow.set_tag("entrypoint", "pipelines/train.py")
        mlflow.set_tag("marts_table", f"{FEATURES_SCHEMA}.{FEATURES_TABLE}")
        mlflow.set_tag("rds_host", cfg.host)

        df, sql = load_data(cfg)
        mlflow.log_param("row_count", len(df))
        mlflow.log_param("positive_rate", round(float(df[TARGET_COL].mean()), 4))
        # Tag a one-line preview; full SQL goes in as an artifact.
        mlflow.set_tag("sql_preview", " ".join(sql.split())[:240])
        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "query.sql"
            sql_path.write_text(sql)
            mlflow.log_artifact(str(sql_path), artifact_path="query")

        pipe, X_test, y_test = train(df)
        metrics = evaluate(pipe, X_test, y_test)
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(pipe, name="model")

        ui_base = tracking_uri.replace("mlflow:5000", "localhost:5000")
        experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
        run_url = (
            f"{ui_base}/#/experiments/{experiment.experiment_id}/runs/{run.info.run_id}"
        )
        LOG.info("done. run URL: %s", run_url)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        LOG.exception("training pipeline failed")
        sys.exit(1)
