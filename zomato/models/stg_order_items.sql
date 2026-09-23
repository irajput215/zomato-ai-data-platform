{{
    config(
        materialized='view',
        tags=['staging', 'facts']
    )
}}

-- ~23M rows. This stays a view on purpose: the incremental fact table
-- (fct_order_items) is what actually materialises it, and a view costs nothing
-- to keep around. The inner join to stg_orders in that model is what drops the
-- handful of orphaned order items.

with source as (

    select * from {{ source('raw', 'order_items') }}
    where order_item_id is not null

),

typed as (

    select
        order_item_id,
        order_id,
        r_id                            as restaurant_id,
        nullif(trim(f_id), '')          as food_id,
        price::decimal(10, 2)           as price,
        quantity::number                as quantity,
        line_amount::decimal(10, 2)     as line_amount

    from source

)

select * from typed
