{{
    config(
        materialized='table',
        tags=['marts', 'dimensions']
    )
}}

-- Dish dimension. Thin on purpose: all the cleaning happened in stg_food.

select
    food_id,
    food_name,
    veg_or_non_veg
from {{ ref('stg_food') }}
