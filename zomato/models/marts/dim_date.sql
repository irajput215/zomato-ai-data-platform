{{
    config(
        materialized='table',
        tags=['marts', 'dimensions']
    )
}}

-- Generated calendar. Snowflake's GENERATOR gives us a row spine without
-- pulling in a package like dbt_utils.date_spine, which keeps this project
-- dependency-free (`dbt build` works with no `dbt deps` step).
--
-- 1,200 days from the spine start comfortably covers the configured end date.

with spine as (

    select
        dateadd(day, seq4(), '{{ var("date_spine_start") }}'::date) as date_day
    from table(generator(rowcount => 1200))

)

select
    date_day,
    year(date_day)                       as year,
    month(date_day)                      as month,
    monthname(date_day)                  as month_name,
    dayname(date_day)                    as day_name,
    dayofweekiso(date_day)               as day_of_week,
    (dayofweekiso(date_day) >= 6)        as is_weekend,
    date_trunc('month', date_day)::date  as month_start
from spine
where date_day <= '{{ var("date_spine_end") }}'::date
