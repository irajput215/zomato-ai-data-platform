{{
    config(
        materialized='view',
        tags=['staging', 'dimensions']
    )
}}

-- The messiest source in the project. Everything the real Zomato export throws
-- at us gets handled here so no downstream model has to know about it:
--
--   rating        '4.1' | '--' | 'NEW'          -> decimal or null
--   rating_count  '50+ ratings' | '1234 ratings' -> integer
--   cost          '₹ 200' | '₹ 200 for two'      -> integer
--   city          'Koramangala, Bangalore'       -> 'Bangalore'
--   _idx          pandas index column            -> dropped

with source as (

    select * from {{ source('raw', 'restaurants') }}
    -- Rows with a non-numeric id cannot be joined to anything downstream.
    where try_to_number(id) is not null

),

cleaned as (

    select
        id::number                                   as restaurant_id,
        nullif(trim(name), '')                       as restaurant_name,
        {{ clean_city('city') }}                     as city,
        nullif(trim(cuisine), '')                    as cuisine,

        -- '--' and 'NEW' both mean "no rating yet", not zero.
        try_to_decimal(
            nullif(nullif(trim(rating), '--'), 'NEW'), 3, 1
        )                                            as rating,

        try_to_number(regexp_substr(rating_count, '[0-9]+'))  as rating_count,
        try_to_number(regexp_substr(cost,         '[0-9]+'))  as cost_for_two,

        nullif(trim(lic_no), '')                     as license_no,
        nullif(trim(link), '')                       as link,
        nullif(trim(address), '')                    as address,

        -- Kept for completeness: the raw menu is a free-text blob. The
        -- structured menu items live in stg_menu.
        nullif(trim(menu), '')                       as menu_raw

    from source

)

select * from cleaned
