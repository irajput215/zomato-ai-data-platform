{{
    config(
        materialized='table',
        tags=['marts', 'restaurants']
    )
}}

-- One row per restaurant: the leaderboard mart.
--
-- The LEFT JOIN keeps orders whose restaurant is missing from the dimension;
-- they show up with a null name rather than vanishing, which is what you want
-- when you are debugging a data-quality problem.

select
    f.restaurant_id,
    r.restaurant_name,
    r.city,
    r.cuisine,

    count(*)                                            as orders,
    count_if(f.is_delivered)                            as delivered_orders,
    sum(iff(f.is_delivered, f.sales_amount, 0))         as revenue,
    round(div0(sum(iff(f.is_delivered, f.sales_amount, 0)), count_if(f.is_delivered)), 2)
                                                        as aov,

    round(avg(f.customer_rating), 2)                    as avg_customer_rating,
    round(avg(f.delivery_time_min), 1)                  as avg_delivery_min,
    round(div0(count_if(f.order_status = 'Cancelled'), count(*)), 4)
                                                        as cancel_rate

from {{ ref('fct_orders') }} f
left join {{ ref('dim_restaurants') }} r using (restaurant_id)
group by 1, 2, 3, 4
