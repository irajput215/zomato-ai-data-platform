{{
    config(
        materialized='view',
        tags=['staging', 'facts']
    )
}}

-- orders.csv is generated clean, so this model is deliberately thin: rename to
-- the warehouse's vocabulary, canonicalise the city, and derive one boolean
-- that every downstream mart needs.

with source as (

    select * from {{ source('raw', 'orders') }}
    where order_id is not null

),

renamed as (

    select
        order_id,
        order_timestamp,
        order_date,
        user_id                                 as customer_id,
        r_id                                    as restaurant_id,
        {{ clean_city('restaurant_city') }}     as city,
        nullif(trim(cuisine), '')               as cuisine,
        items_count,
        sales_qty,
        subtotal,
        discount,
        delivery_fee,
        gst,
        sales_amount,
        currency,
        payment_method,
        order_status,

        -- The single most reused derived column in the project.
        (order_status = 'Delivered')            as is_delivered,

        customer_rating,
        delivery_time_min

    from source

)

select * from renamed
