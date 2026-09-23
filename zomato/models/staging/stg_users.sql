{{
    config(
        materialized='view',
        tags=['staging', 'dimensions']
    )
}}

-- users.csv is a messy "real world" export:
--   gender        'Male' | 'male' | 'M' | 'F'
--   email         'Rahul.Sharma@Gmail.com'
--   age           '28' | 'NA'
--   monthly_income '25000' | 'No Income'
--   family_size   '4' | 'NA'

with source as (

    select * from {{ source('raw', 'users') }}
    where try_to_number(user_id) is not null

),

cleaned as (

    select
        user_id::number                     as customer_id,
        nullif(trim(name), '')              as customer_name,
        nullif(lower(trim(email)), '')      as email,

        try_to_number(age)                  as age,

        -- Collapse the mixed casing and the single-letter forms so
        -- accepted_values tests and BI groupings actually line up.
        case upper(trim(gender))
            when 'M' then 'Male'
            when 'F' then 'Female'
            else initcap(lower(trim(gender)))
        end                                 as gender,

        nullif(trim(marital_status), '')    as marital_status,
        nullif(trim(occupation), '')        as occupation,
        nullif(trim(monthly_income), '')    as income_band,
        nullif(trim(education), '')         as education,
        try_to_number(family_size)          as family_size

    from source

)

select * from cleaned
