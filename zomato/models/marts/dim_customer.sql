{{
    config(
        materialized='table',
        tags=['marts', 'dimensions']
    )
}}

-- Customer dimension with the age segmentation the marketing marts slice by.

with deduped as (

    select
        *,
        row_number() over (
            partition by customer_id
            order by (email is not null) desc,
                     (age is not null) desc,
                     customer_name
        ) as row_num

    from {{ ref('stg_users') }}

)

select
    customer_id,
    customer_name,
    email,
    age,

    -- The null check comes FIRST. Writing `when age < 25 ... when age is null`
    -- also works in Snowflake (null comparisons are never true, so control
    -- falls through) but it reads like a bug and breaks the moment someone
    -- reorders the branches.
    case
        when age is null then 'Unknown'
        when age < 25   then 'Gen Z'
        when age < 40   then 'Millennial'
        when age < 55   then 'Gen X'
        else                 'Boomer'
    end                          as age_segment,

    gender,
    marital_status,
    occupation,
    income_band,
    education,
    family_size
from deduped
where row_num = 1
