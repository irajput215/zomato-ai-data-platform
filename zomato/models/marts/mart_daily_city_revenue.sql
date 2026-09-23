{{
    config(
        materialized='table',
        tags=['marts', 'revenue']
    )
}}

-- One row per (order_date, city) — the revenue mart behind the dashboard's
-- GMV trend and the "Top 10 cities by GMV" example question in the
-- text-to-SQL app.
--
-- GMV counts *delivered* orders only, so cancellations never inflate revenue.
-- AOV divides that same GMV by delivered orders, not by all orders.

select
    order_date,
    city,

    count(*)                                        as orders,
    count_if(is_delivered)                          as delivered_orders,
    count_if(order_status = 'Cancelled')            as cancelled_orders,
    count_if(order_status = 'Refunded')             as refunded_orders,

    round(div0(count_if(order_status = 'Cancelled'), count(*)), 4)
                                                    as cancel_rate,

    round(sum(iff(is_delivered, sales_amount, 0)), 2)
                                                    as gmv,

    round(div0(sum(iff(is_delivered, sales_amount, 0)), count_if(is_delivered)), 2)
                                                    as aov,

    round(sum(iff(is_delivered, discount, 0)), 2)   as discount_given,
    round(avg(iff(is_delivered, customer_rating, null)), 2)
                                                    as avg_customer_rating

from {{ ref('fct_orders') }}
group by 1, 2
