-- =============================================================================
-- Analysis: GMV trend per city, with a 28-day rolling window.
-- =============================================================================
-- Files in analyses/ are compiled by dbt but never materialised. They exist so
-- that ad-hoc SQL lives in the repository — versioned, reviewable and aware of
-- ref() lineage — instead of in somebody's scratch worksheet.
--
-- Get the compiled SQL with:
--   dbt compile --select gmv_trend --profiles-dir .
--   cat target/compiled/zomato/analyses/gmv_trend.sql

with daily as (

    select
        order_date,
        city,
        gmv,
        orders,
        aov
    from {{ ref('mart_daily_city_revenue') }}

)

select
    order_date,
    city,
    gmv,
    orders,
    aov,

    round(
        avg(gmv) over (
            partition by city
            order by order_date
            rows between 27 preceding and current row
        ), 2
    )                       as gmv_28d_rolling,

    round(
        sum(gmv) over (
            partition by city
            order by order_date
        ), 2
    )                       as gmv_cumulative

from daily
order by city, order_date
