{{ config(materialized='table') }}

-- Marts: per-customer feature row consumed by pipelines/train.py.
-- One row per customer_id. Booleans for "is_*" flags, integer bucket
-- for tenure, derived spend ratio. The target column `churn` is passed
-- through unchanged so train.py can split it off.

with stg as (
    select * from {{ ref('stg_customer_churn') }}
)

select
    customer_id,

    -- Pass-throughs the model can use directly.
    gender,
    senior_citizen,
    partner,
    dependents,
    tenure,
    phone_service,
    multiple_lines,
    internet_service,
    online_security,
    online_backup,
    device_protection,
    tech_support,
    streaming_tv,
    streaming_movies,
    contract_type,
    paperless_billing,
    payment_method,
    monthly_charges,
    total_charges,

    -- ---- Engineered features --------------------------------------------

    -- Contract-shape signal: month-to-month customers churn far more.
    (contract_type = 'month-to-month')                          as is_month_to_month,

    -- Coarse tenure bucketing for tree-based models / EDA.
    case
        when tenure is null         then null
        when tenure <  6            then '00_0_to_5'
        when tenure < 12            then '01_6_to_11'
        when tenure < 24            then '02_12_to_23'
        when tenure < 48            then '03_24_to_47'
        else                             '04_48_plus'
    end                                                          as tenure_bucket,

    -- Spend intensity: total_charges / tenure. Guards tenure=0.
    case
        when tenure is null or tenure = 0 then null
        else (total_charges / tenure)::numeric(12, 4)
    end                                                          as charges_per_month_of_tenure,

    -- Ratio of actual lifetime charge to "expected if billed every month".
    case
        when monthly_charges is null or monthly_charges = 0 or tenure is null or tenure = 0
            then null
        else (total_charges / (monthly_charges * tenure))::numeric(8, 4)
    end                                                          as lifetime_to_expected_ratio,

    -- Number of opt-in add-on services (excludes phone/internet baselines).
    (
        case when online_security    = 'yes' then 1 else 0 end
      + case when online_backup      = 'yes' then 1 else 0 end
      + case when device_protection  = 'yes' then 1 else 0 end
      + case when tech_support       = 'yes' then 1 else 0 end
      + case when streaming_tv       = 'yes' then 1 else 0 end
      + case when streaming_movies   = 'yes' then 1 else 0 end
    )                                                            as num_addon_services,

    -- ---- Target ---------------------------------------------------------
    churn

from stg
