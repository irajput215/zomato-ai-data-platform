{{
    config(
        materialized='table',
        tags=['ai', 'marts', 'reviews']
    )
}}

-- The payoff of the AI lane: free-text reviews turned into a groupable mart.
--
-- `tag:ai` is what makes the two-phase DAG work. Airflow runs
-- `dbt build --exclude tag:ai` BEFORE the enrichment job (the table this model
-- reads does not exist yet), then `dbt build --select tag:ai` after.
--
-- The join needs a cast because the Python job writes REVIEW_ID back as a
-- STRING while RAW.reviews.review_id is a NUMBER. `try_to_number` rather than
-- `::number` so a malformed id can never blow up the whole model.

with enriched as (

    select
        try_to_number(review_id)                        as review_id,
        sentiment_label,
        try_to_number(sentiment_score)                  as sentiment_score,
        topic,
        nullif(trim(key_issue), '')                     as key_issue,
        model
    from {{ source('ai', 'review_enriched') }}
    where try_to_number(review_id) is not null

)

select
    rr.city,
    e.topic,
    e.sentiment_label,

    count(*)                                    as reviews,
    round(avg(e.sentiment_score), 3)            as avg_sentiment_score,
    round(avg(rr.rating), 2)                    as avg_star_rating,
    count_if(e.key_issue is not null)           as flagged_issues,
    min(rr.review_date)                         as first_review_date,
    max(rr.review_date)                         as last_review_date

from enriched e
inner join {{ ref('stg_reviews') }} rr
       on e.review_id = rr.review_id

group by 1, 2, 3
