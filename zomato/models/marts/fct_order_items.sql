{{
    config(
        materialized='incremental',
        unique_key='order_item_id',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
        tags=['marts', 'facts']
    )
}}

-- The ~23M-row order line item fact.
--
-- The INNER JOIN to stg_orders does two jobs: it attaches order-level context
-- (timestamp, date, city) to every line, and it drops orphaned line items whose
-- order never loaded — the referential-integrity guarantee that
-- tests/assert_order_items_reconcile_to_orders.sql then verifies.
--
-- Watermarking uses the parent order's timestamp, so a late-arriving order
-- brings its lines with it.

with items as (

    select
        oi.order_item_id,
        oi.order_id,
        oi.restaurant_id,
        oi.food_id,
        o.order_timestamp   as order_ts,
        o.order_date,
        o.city,
        oi.price,
        oi.quantity,
        oi.line_amount

    from {{ ref('stg_order_items') }} oi
    inner join {{ ref('stg_orders') }} o using (order_id)

    {% if is_incremental() %}
    where o.order_timestamp > (
        select coalesce(max(order_ts), '1900-01-01'::timestamp) from {{ this }}
    )
    {% endif %}

)

select * from items
