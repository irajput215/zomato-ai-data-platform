{{
    config(
        materialized='table',
        tags=['marts', 'delivery']
    )
}}

-- Delivery SLA by city and hour of day: the "where and when are we late?" mart.
--
-- The late threshold is a project variable, not a hard-coded number, so the
-- business can move the goalposts without a code change:
--   dbt build --select mart_delivery_sla --vars '{delivery_sla_minutes: 60}'
--
-- Only delivered orders are considered — a cancelled order has no delivery
-- time, and counting it as "fast" would flatter the numbers.

{% set sla_minutes = var('delivery_sla_minutes', 45) %}

select
    city,
    hour(order_timestamp)                                   as order_hour,
    count_if(is_delivered)                                  as delivered_orders,

    round(median(delivery_time_min), 1)                     as p50_delivery_min,
    round(percentile_cont(0.9) within group (order by delivery_time_min), 1)
                                                            as p90_delivery_min,
    round(avg(delivery_time_min), 1)                        as avg_delivery_min,
    max(delivery_time_min)                                  as worst_delivery_min,

    count_if(delivery_time_min > {{ sla_minutes }})         as late_orders,
    round(
        div0(count_if(delivery_time_min > {{ sla_minutes }}), count_if(is_delivered)), 4
    )                                                       as late_rate
from {{ ref('fct_orders') }}
where is_delivered
group by 1, 2
