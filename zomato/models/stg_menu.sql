{{
    config(
        materialized='view',
        tags=['staging', 'dimensions']
    )
}}

-- menu.csv links restaurants to the food items they sell, with a price.
-- price arrives as a numeric string ('250', '349.50'); rows whose price will
-- not cast, or that cast to zero/negative, are dropped rather than passed on
-- as misleading free food.

with source as (

    select * from {{ source('raw', 'menu') }}
    where try_to_number(r_id) is not null

),

cleaned as (

    select
        nullif(trim(menu_id), '')                       as menu_id,
        try_to_number(r_id)                             as restaurant_id,
        nullif(trim(f_id), '')                          as food_id,
        nullif(trim(cuisine), '')                       as cuisine,
        try_to_decimal(price, 10, 2)                    as price

    from source

)

select *
from cleaned
where price > 0
