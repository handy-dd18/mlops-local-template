{#
    Override dbt's default schema-name generator so that the per-folder
    `+schema:` configs in dbt_project.yml become the *literal* schema
    names ("staging", "marts") instead of the default
    "<target_schema>_<custom_schema>" concatenation.

    This keeps the physical layout in Postgres tidy and predictable:
        raw.customer_churn          (loaded by pipelines/load_s3_to_rds.py)
        staging.stg_customer_churn  (dbt view)
        marts.customer_features     (dbt table — train.py reads this)
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
