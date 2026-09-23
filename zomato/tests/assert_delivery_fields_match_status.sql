-- =============================================================================
-- Singular test: a delivered order has both a rating and a delivery time;
-- a cancelled or refunded order has neither.
-- =============================================================================
-- This invariant spans four columns, so no generic dbt test can express it.
-- Any row this query returns is a failure.
--
-- It is worth having because every downstream metric silently depends on it:
-- mart_delivery_sla counts `delivery_time_min` only where is_delivered, and
-- mart_restaurant_performance averages customer_rating. If a cancelled order
-- ever carried a delivery time, both marts would quietly report fiction.

select
    order_id,
    order_status,
    is_delivered,
    customer_rating,
    delivery_time_min
from {{ ref('stg_orders') }}
where (is_delivered and (customer_rating is null or delivery_time_min is null))
   or (not is_delivered and (customer_rating is not null or delivery_time_min is not null))
