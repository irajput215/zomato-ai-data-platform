{#-
    Normalise a messy city field to a single canonical value.

    The source data stores cities two different ways depending on the file:

        restaurants.city       "Koramangala, Bangalore"
        orders.restaurant_city "Koramangala, Bangalore"
        users                  (no city column)

    Both staging models call this macro instead of inlining the expression, so
    the value that lands in dim_restaurants.city is character-for-character the
    same as fct_orders.city. Without that guarantee the city-level marts would
    silently split "Bangalore" into two groups.

    Logic: take the text after the final comma ("the city"), title-case it, and
    fall back to the whole (title-cased) value when there is no comma.
#}
{% macro clean_city(column_name) -%}
coalesce(
    nullif(initcap(trim(regexp_substr({{ column_name }}, '[^,]+$'))), ''),
    initcap(trim({{ column_name }}))
)
{%- endmacro %}
