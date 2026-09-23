-- =============================================================================
-- Singular test: the headline reconciliation.
-- =============================================================================
-- Every order's stored summary columns must agree with the line items that
-- were actually sold:
--
--   fct_orders.items_count  == number of rows in fct_order_items
--   fct_orders.sales_qty    == sum of those rows' quantity
--   fct_orders.subtotal     == sum of those rows' line_amount
--
-- This is the test that catches the classic medallion failure — a partially
-- loaded order_items file, an incremental watermark that skipped a batch, or a
-- join in fct_order_items that silently dropped lines. Any of those would leave
-- the marts reporting revenue that no line item supports.
--
-- It also checks the two ORPHAN cases, which an INNER JOIN between the two facts
-- would quietly drop from the comparison instead of reporting:
--
--   * an order with no line items at all, and
--   * line items whose parent order is not in fct_orders.
--
-- ⚠️ It does NOT validate numbers within a single fact table. If a row went
-- missing from `fct_orders` AND its line items went missing from
-- `fct_order_items` in the same load, both sides shrink together and this test
-- still passes. Catching that needs a row count compared against its source
-- (see ZOMATO.ADMIN.PIPELINE_HEALTH), not a reconciliation between two derived
-- tables.
--
-- Cost note: this is a 23M-row GROUP BY joined to a 10M-row table, so it is the
-- single most expensive test in the project. That is a deliberate trade: it is
-- also the one most likely to catch a real problem. Skip it in a hurry with
--   dbt build --exclude assert_order_items_reconcile_to_orders

with line_sums as (

    select
        order_id,
        count(*)                    as line_items,
        sum(quantity)               as total_quantity,
        round(sum(line_amount), 2)  as items_subtotal
    from {{ ref('fct_order_items') }}
    group by order_id

),

compared as (

    select
        coalesce(o.order_id, s.order_id) as order_id,

        -- These two flags are what an INNER JOIN silently hides. `dbt test`
        -- reports one row per failure, so a flagged row here is a real finding.
        (o.order_id is null)             as only_in_line_items,
        (s.order_id is null)             as order_has_no_line_items,

        o.items_count                    as orders_items_count,
        s.line_items                     as actual_line_items,
        o.sales_qty                      as orders_sales_qty,
        s.total_quantity                 as actual_quantity,
        o.subtotal                       as orders_subtotal,
        s.items_subtotal                 as actual_subtotal
    -- FULL OUTER, not INNER, and that matters. With an INNER JOIN, two real
    -- failures disappear from the comparison instead of being flagged:
    --   * an order in fct_orders whose line items are ALL missing (there is no
    --     line_sums row to join to), and
    --   * line items whose parent order never made it into fct_orders.
    -- Both are exactly the load loss this test exists to catch, so both sides are
    -- kept and surfaced through the flags above.
    from {{ ref('fct_orders') }} o
    full outer join line_sums s on o.order_id = s.order_id

)

select *
from compared
where only_in_line_items
   or order_has_no_line_items
   or orders_items_count <> actual_line_items
   or orders_sales_qty   <> actual_quantity
   or abs(orders_subtotal - actual_subtotal) > 0.01
