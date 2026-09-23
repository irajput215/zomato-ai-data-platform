-- =============================================================================
-- Analysis: where is delivery actually breaching the SLA?
-- =============================================================================
-- Ranked worst-first, with a minimum-volume filter so a single late order at
-- 3am in a small city does not top the list.
--
--   dbt compile --select sla_regression --profiles-dir .
--   cat target/compiled/zomato/analyses/sla_regression.sql

select
    city,
    order_hour,
    delivered_orders,
    p50_delivery_min,
    p90_delivery_min,
    avg_delivery_min,
    worst_delivery_min,
    late_orders,
    late_rate
from {{ ref('mart_delivery_sla') }}
where delivered_orders >= 100
order by late_rate desc, delivered_orders desc
limit 50
