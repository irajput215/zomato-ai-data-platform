-- =============================================================================
-- Singular test: a review is never dated before the order it reviews.
-- =============================================================================
-- Review dates are generated as order_date + 0..14 days. If this ever returns
-- rows, either the generator drifted or a join in stg_reviews paired a review
-- with the wrong order.

select
    r.review_id,
    r.order_id,
    r.review_date,
    o.order_date,
    datediff('day', o.order_date, r.review_date) as days_between
from {{ ref('stg_reviews') }} r
inner join {{ ref('fct_orders') }} o using (order_id)
where r.review_date < o.order_date
