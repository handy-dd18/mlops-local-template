{{ config(materialized='view') }}

-- Staging layer: cast raw TEXT columns to proper types, normalise
-- categorical strings (lowercase + trim), drop rows with no customer_id.
--
-- All "blank-or-null" handling uses NULLIF on a trimmed value so rows
-- with whitespace-only fields are treated as NULL. The Telco-churn CSV
-- famously has whitespace `total_charges` for brand-new customers
-- (tenure = 0), which would otherwise blow up the numeric cast.

with raw as (
    select * from {{ source('raw', 'customer_churn') }}
),

cleaned as (
    select
        nullif(trim(customer_id), '')                              as customer_id,

        lower(nullif(trim(gender), ''))                            as gender,
        lower(nullif(trim(senior_citizen), ''))                    as senior_citizen_raw,
        lower(nullif(trim(partner), ''))                           as partner_raw,
        lower(nullif(trim(dependents), ''))                        as dependents_raw,

        nullif(trim(tenure), '')::int                              as tenure,

        lower(nullif(trim(phone_service), ''))                     as phone_service_raw,
        lower(nullif(trim(multiple_lines), ''))                    as multiple_lines,
        lower(nullif(trim(internet_service), ''))                  as internet_service,
        lower(nullif(trim(online_security), ''))                   as online_security,
        lower(nullif(trim(online_backup), ''))                     as online_backup,
        lower(nullif(trim(device_protection), ''))                 as device_protection,
        lower(nullif(trim(tech_support), ''))                      as tech_support,
        lower(nullif(trim(streaming_tv), ''))                      as streaming_tv,
        lower(nullif(trim(streaming_movies), ''))                  as streaming_movies,
        lower(nullif(trim(contract_type), ''))                     as contract_type,
        lower(nullif(trim(paperless_billing), ''))                 as paperless_billing_raw,
        lower(nullif(trim(payment_method), ''))                    as payment_method,

        nullif(trim(monthly_charges), '')::numeric(10, 2)          as monthly_charges,
        nullif(trim(total_charges),   '')::numeric(12, 2)          as total_charges,

        lower(nullif(trim(churn), ''))                             as churn_raw
    from raw
),

typed as (
    select
        customer_id,
        gender,

        -- Boolean coercions: accept "yes"/"true"/"1" as true.
        case
            when senior_citizen_raw    in ('yes', 'true', '1') then true
            when senior_citizen_raw    in ('no',  'false', '0') then false
        end                                                       as senior_citizen,
        case
            when partner_raw           in ('yes', 'true', '1') then true
            when partner_raw           in ('no',  'false', '0') then false
        end                                                       as partner,
        case
            when dependents_raw        in ('yes', 'true', '1') then true
            when dependents_raw        in ('no',  'false', '0') then false
        end                                                       as dependents,

        tenure,

        case
            when phone_service_raw     in ('yes', 'true', '1') then true
            when phone_service_raw     in ('no',  'false', '0') then false
        end                                                       as phone_service,

        multiple_lines,
        internet_service,
        online_security,
        online_backup,
        device_protection,
        tech_support,
        streaming_tv,
        streaming_movies,
        contract_type,

        case
            when paperless_billing_raw in ('yes', 'true', '1') then true
            when paperless_billing_raw in ('no',  'false', '0') then false
        end                                                       as paperless_billing,

        payment_method,
        monthly_charges,
        total_charges,

        case
            when churn_raw             in ('yes', 'true', '1') then true
            when churn_raw             in ('no',  'false', '0') then false
        end                                                       as churn
    from cleaned
)

select *
from typed
where customer_id is not null
