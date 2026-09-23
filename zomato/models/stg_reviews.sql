{{
    config(
        materialized='view',
        tags=['staging', 'facts', 'reviews']
    )
}}

-- 300,000 free-text reviews — the input to the AI layer.
--
-- The review row itself does not carry a city, so it is joined in from the
-- restaurant dimension. The join is on restaurant_id (not city) because that is
-- the key that actually exists in both places.
--
-- The LEFT JOIN is deliberate: a review whose restaurant is missing from the
-- dimension must still reach enrich_reviews.py, it just has a null city.

with reviews as (

    select * from {{ source('raw', 'reviews') }}
    where review_id is not null
      and nullif(trim(comment), '') is not null

),

enriched_with_city as (

    select
        r.review_id,
        r.order_id,
        r.user_id::number           as customer_id,
        r.restaurant_id::number     as restaurant_id,
        r.rating::number            as rating,
        trim(r.comment)             as comment,
        r.review_date::date         as review_date,
        res.city

    from reviews r
    left join {{ ref('stg_restaurants') }} res
           on r.restaurant_id::number = res.restaurant_id

)

select * from enriched_with_city
