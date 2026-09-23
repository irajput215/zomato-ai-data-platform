{% snapshot dim_restaurants_snapshot %}

{#
    SCD2 history for the restaurant dimension.

    dbt's incremental models answer "what is true now"; a snapshot answers
    "what was true then, and when did it change". Restaurant ratings and
    cost-for-two drift over time and every historical mart should be able to
    use the values that were true on the order date.

    strategy = 'check'
        The source has no reliable updated_at column, so dbt compares the
        listed columns on every run and writes a new version when any of them
        differ. `dbt_valid_from` / `dbt_valid_to` bracket each version.

    invalidate_hard_deletes = True
        When a restaurant disappears from the source, close its current row
        instead of leaving it open forever. (In dbt 1.9+ this config was
        renamed to `hard_deletes`; `invalidate_hard_deletes` is the correct
        spelling for the dbt 1.8 pinned in airflow/Dockerfile.)

    Run with:  dbt snapshot --profiles-dir .
#}

{{
    config(
        target_schema='snapshots',
        unique_key='restaurant_id',
        strategy='check',
        check_cols=[
            'restaurant_name',
            'city',
            'cuisine',
            'rating',
            'rating_count',
            'cost_for_two'
        ],
        invalidate_hard_deletes=True
    )
}}

select
    restaurant_id,
    restaurant_name,
    city,
    cuisine,
    rating,
    rating_count,
    cost_for_two
from {{ ref('stg_restaurants') }}

{% endsnapshot %}
