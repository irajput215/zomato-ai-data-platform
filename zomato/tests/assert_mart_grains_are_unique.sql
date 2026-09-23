-- =============================================================================
-- Singular test: every business mart has a genuinely unique grain.
-- =============================================================================
-- The project deliberately takes no package dependency (no dbt_utils), so the
-- "unique combination of columns" check is written by hand instead.
--
-- Each branch contributes only VIOLATING keys, so a passing run returns zero
-- rows overall. The grain_key is a readable concatenation, which makes the
-- failure output tell you exactly which combination duplicated.
--
-- mart_review_insights is checked separately in
-- assert_review_insight_grain_is_unique.sql, because it is built in the second
-- phase of the DAG and does not exist during `dbt build --exclude tag:ai`.

with duplicate_grains as (

    -- mart_daily_city_revenue: one row per day per city
    select
        'mart_daily_city_revenue'           as model_name,
        order_date::string || ' | ' || city as grain_key,
        count(*)                            as row_count
    from {{ ref('mart_daily_city_revenue') }}
    group by 1, 2
    having count(*) > 1

    union all

    -- mart_restaurant_performance: one row per restaurant
    select
        'mart_restaurant_performance',
        restaurant_id::string,
        count(*)
    from {{ ref('mart_restaurant_performance') }}
    group by 1, 2
    having count(*) > 1

    union all

    -- mart_delivery_sla: one row per city per hour
    select
        'mart_delivery_sla',
        city || ' | ' || order_hour::string,
        count(*)
    from {{ ref('mart_delivery_sla') }}
    group by 1, 2
    having count(*) > 1

)

select * from duplicate_grains
