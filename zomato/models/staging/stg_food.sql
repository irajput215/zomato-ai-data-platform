{{
    config(
        materialized='view',
        tags=['staging', 'dimensions']
    )
}}

-- food.csv is small and mostly clean, but the exporter drops the trailing
-- veg_or_non_veg field on a handful of rows. The file format NULL-fills those
-- (ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE), so we only have to normalise case.

with source as (

    select * from {{ source('raw', 'food') }}
    where nullif(trim(f_id), '') is not null

),

cleaned as (

    select
        trim(f_id)                      as food_id,
        nullif(trim(item), '')          as food_name,

        case
            when trim(veg_or_non_veg) is null then null
            when upper(trim(veg_or_non_veg)) like 'VEG%' then 'Veg'
            else 'Non-Veg'
        end                             as veg_or_non_veg

    from source

)

select * from cleaned
