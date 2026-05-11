"""Generate a synthetic Telco-style customer-churn CSV.

Standard library + numpy + pandas only. Seeded RNG. Produces exactly
7,000 rows at ``data/raw/customer_churn.csv`` with the column names and
order declared in ``infra/terraform/glue.tf`` (Glue-canonical form).

Realistic correlations baked in so models converge to something
non-trivial:

  * Higher ``monthly_charges`` raises churn probability.
  * Month-to-month contracts churn far more than 1- or 2-year contracts.
  * Short tenure raises churn probability.
  * Fiber-optic internet customers churn more than DSL or no-internet.
  * Electronic-check payment correlates with higher churn.
  * Senior citizens churn slightly more.
  * Customers with many add-on services churn slightly less.

Whitespace is intentionally injected into ``total_charges`` for a small
fraction of brand-new (tenure=0) customers — this mirrors the real
Telco-churn dataset and lets the dbt staging NULLIF logic actually
matter.

Run:
    python scripts/generate_sample_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# --- Config -----------------------------------------------------------------

N_ROWS = 7_000
RANDOM_SEED = 20250511

# Path is resolved relative to the repo root (parent of scripts/).
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "customer_churn.csv"

# Glue-canonical column order — must match infra/terraform/glue.tf.
COLUMNS = [
    "customer_id",
    "gender",
    "senior_citizen",
    "partner",
    "dependents",
    "tenure",
    "phone_service",
    "multiple_lines",
    "internet_service",
    "online_security",
    "online_backup",
    "device_protection",
    "tech_support",
    "streaming_tv",
    "streaming_movies",
    "contract_type",
    "paperless_billing",
    "payment_method",
    "monthly_charges",
    "total_charges",
    "churn",
]


# --- Helpers ----------------------------------------------------------------

def _yesno(rng: np.random.Generator, n: int, p_yes: float) -> np.ndarray:
    return np.where(rng.random(n) < p_yes, "yes", "no")


def _customer_ids(rng: np.random.Generator, n: int) -> np.ndarray:
    """Generate n unique IDs of the form 'NNNN-XXXXX'."""
    digits = rng.integers(1000, 10000, size=n)
    letters = np.array(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    suffixes = np.apply_along_axis(
        lambda row: "".join(row), 1, rng.choice(letters, size=(n, 5))
    )
    raw = np.array([f"{d}-{s}" for d, s in zip(digits, suffixes)])
    # Ensure uniqueness by appending an incrementing tail when collisions occur.
    seen: dict[str, int] = {}
    out = np.empty(n, dtype=object)
    for i, val in enumerate(raw):
        if val not in seen:
            seen[val] = 0
            out[i] = val
        else:
            seen[val] += 1
            out[i] = f"{val[:-1]}{seen[val] % 10}"
    return out


# --- Generator --------------------------------------------------------------

def generate(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    customer_id = _customer_ids(rng, n)

    gender = rng.choice(["male", "female"], size=n, p=[0.504, 0.496])
    senior_citizen = _yesno(rng, n, 0.16)
    partner = _yesno(rng, n, 0.48)
    dependents = _yesno(rng, n, 0.30)

    # Tenure 0..72 with a roughly bimodal distribution: lots of newcomers
    # plus a long-tail of loyal customers.
    tenure_short = rng.integers(0, 18, size=n)
    tenure_long = rng.integers(18, 73, size=n)
    use_short = rng.random(n) < 0.55
    tenure = np.where(use_short, tenure_short, tenure_long).astype(int)

    phone_service = _yesno(rng, n, 0.903)

    # multiple_lines depends on phone_service.
    multiple_lines = np.where(
        phone_service == "no",
        "no phone service",
        np.where(rng.random(n) < 0.46, "yes", "no"),
    )

    # internet_service: dsl / fiber optic / no.
    internet_service = rng.choice(
        ["dsl", "fiber optic", "no"], size=n, p=[0.34, 0.44, 0.22]
    )

    def _addon(p_yes_with_internet: float) -> np.ndarray:
        out = np.where(rng.random(n) < p_yes_with_internet, "yes", "no")
        return np.where(internet_service == "no", "no internet service", out)

    online_security = _addon(0.36)
    online_backup = _addon(0.44)
    device_protection = _addon(0.44)
    tech_support = _addon(0.37)
    streaming_tv = _addon(0.49)
    streaming_movies = _addon(0.49)

    # Contract type — biased so the dataset has a healthy month-to-month majority.
    contract_type = rng.choice(
        ["month-to-month", "one year", "two year"], size=n, p=[0.55, 0.21, 0.24]
    )

    paperless_billing = _yesno(rng, n, 0.59)
    payment_method = rng.choice(
        [
            "electronic check",
            "mailed check",
            "bank transfer (automatic)",
            "credit card (automatic)",
        ],
        size=n,
        p=[0.34, 0.23, 0.22, 0.21],
    )

    # Monthly charges: base + per-add-on bumps + noise. Floor at ~18.
    base_internet = np.where(
        internet_service == "no",
        0.0,
        np.where(internet_service == "dsl", 25.0, 45.0),
    )
    base_phone = np.where(phone_service == "yes", 20.0, 0.0)
    base_multi = np.where(multiple_lines == "yes", 7.5, 0.0)
    addon_count = sum(
        (arr == "yes").astype(int)
        for arr in (
            online_security,
            online_backup,
            device_protection,
            tech_support,
            streaming_tv,
            streaming_movies,
        )
    )
    addon_charge = addon_count * 5.5
    noise = rng.normal(0.0, 2.0, size=n)
    monthly_charges = np.clip(
        base_internet + base_phone + base_multi + addon_charge + 18.0 + noise,
        18.25,
        125.0,
    ).round(2)

    # total_charges ≈ monthly_charges * tenure + small multiplicative noise.
    # Brand-new customers (tenure = 0) get blank — mirrors the real dataset.
    total_noise = rng.normal(1.0, 0.04, size=n)
    raw_total = monthly_charges * tenure * total_noise
    total_charges = np.where(tenure == 0, " ", np.round(raw_total, 2).astype(str))

    # ---- Churn label with realistic correlations --------------------------
    # Logistic combination of the strong predictors. Then sample ~26% positives.
    z = (
        -1.40
        + 0.040 * (monthly_charges - 65.0)         # higher bill → more churn
        + np.where(contract_type == "month-to-month", 1.10, 0.0)
        + np.where(contract_type == "two year", -1.20, 0.0)
        - 0.045 * tenure                            # longer tenure → less churn
        + np.where(internet_service == "fiber optic", 0.55, 0.0)
        + np.where(internet_service == "no", -0.55, 0.0)
        + np.where(payment_method == "electronic check", 0.45, 0.0)
        + np.where(senior_citizen == "yes", 0.25, 0.0)
        + np.where(partner == "yes", -0.20, 0.0)
        + np.where(dependents == "yes", -0.25, 0.0)
        - 0.10 * addon_count                        # more services → less churn
        + rng.normal(0.0, 0.45, size=n)
    )
    p_churn = 1.0 / (1.0 + np.exp(-z))
    churn = np.where(rng.random(n) < p_churn, "yes", "no")

    df = pd.DataFrame(
        {
            "customer_id": customer_id,
            "gender": gender,
            "senior_citizen": senior_citizen,
            "partner": partner,
            "dependents": dependents,
            "tenure": tenure,
            "phone_service": phone_service,
            "multiple_lines": multiple_lines,
            "internet_service": internet_service,
            "online_security": online_security,
            "online_backup": online_backup,
            "device_protection": device_protection,
            "tech_support": tech_support,
            "streaming_tv": streaming_tv,
            "streaming_movies": streaming_movies,
            "contract_type": contract_type,
            "paperless_billing": paperless_billing,
            "payment_method": payment_method,
            "monthly_charges": monthly_charges,
            "total_charges": total_charges,
            "churn": churn,
        }
    )
    # Enforce column order.
    return df[COLUMNS]


def main() -> int:
    df = generate(N_ROWS, RANDOM_SEED)
    assert len(df) == N_ROWS, f"expected {N_ROWS} rows, got {len(df)}"
    assert list(df.columns) == COLUMNS, f"column order drift: {list(df.columns)}"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    churn_rate = (df["churn"] == "yes").mean()
    print(f"[generate] wrote {len(df):,} rows -> {OUTPUT_PATH}")
    print(f"[generate] churn rate = {churn_rate:.3f}")
    print(f"[generate] columns ({len(df.columns)}): {list(df.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
