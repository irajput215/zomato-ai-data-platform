{{
    config(
        tags=['ai'],
        severity='error'
    )
}}

-- =============================================================================
-- Singular test: mart_review_insights grain is unique.
-- =============================================================================
-- One row per (city, topic, sentiment_label).
--
-- TAGGED `ai` ON PURPOSE. mart_review_insights is only built after
-- ai/enrich_reviews.py has run, so during `dbt build --exclude tag:ai` this
-- test must be excluded too — otherwise the DAG fails on its first ever run
-- because the table it reads does not exist yet.

with counted as (

    select
        coalesce(city, 'unknown')   as city,
        topic,
        sentiment_label,
        count(*)                    as row_count
    from {{ ref('mart_review_insights') }}
    group by 1, 2, 3

)

select *
from counted
where row_count > 1
