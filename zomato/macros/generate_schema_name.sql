{#-
    Schema naming.

    dbt's default behaviour *concatenates* the target schema with the custom
    schema, so `+schema: marts` inside target schema STAGING produces
    STAGING_MARTS. That is rarely what anyone wants.

    Here the custom schema wins outright, so:
        +schema: staging  ->  ZOMATO.STAGING
        +schema: marts    ->  ZOMATO.MARTS
    and models with no custom schema fall back to the target schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
