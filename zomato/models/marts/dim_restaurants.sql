{{
    config(
        materialized='table',
        tags=['marts', 'dimensions']
    )
}}

-- Current-state restaurant dimension.
--
-- SCD2 history for this dimension is produced separately by
-- snapshots/dim_restaurants_snapshot.sql — this model is "as of now", the
-- snapshot is "how it changed".
--
-- The upstream export can repeat a restaurant_id. A row_number() window keeps the
-- most complete record (most ratings, then highest cost) and the outer
-- `where row_num = 1` discards the rest, so this primary key is genuinely unique.
-- That is what lets _marts.yml test it as an error while the same test on
-- stg_restaurants is only a warning.
--
-- Snowflake's QUALIFY clause would express this in a single step; the CTE form is
-- used deliberately so the dedupe reads the same on any warehouse.

with deduped as (

    select
        *,
        row_number() over (
            partition by restaurant_id
            order by rating_count desc nulls last,
                     cost_for_two desc nulls last,
                     restaurant_name
        ) as row_num

    from {{ ref('stg_restaurants') }}

)

select
    restaurant_id,
    restaurant_name,
    city,
    cuisine,
    rating,
    rating_count,
    cost_for_two
from deduped
where row_num = 1
