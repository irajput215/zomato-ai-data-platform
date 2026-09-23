# Zomato data generator

Deterministic, **standard-library-only** (no pandas / numpy / faker) Python
package that produces the seven CSVs which mirror the S3 data lake exactly.
Nothing is installed and nothing is held in memory: rows are streamed to disk
through a buffered `csv.writer`.

```
data/generator/
├── __init__.py                # package marker
├── config.py                  # header contract, catalogues, weights, defaults
├── generate_dimensions.py     # CLI → restaurants, users, food, menu (messy)
├── generate_facts.py          # CLI → orders, order_items, reviews (clean)
├── requirements.txt           # "no third-party dependencies"
└── README.md                  # this file
```

## Quick start

From the **project root** (`zomato-ai-data-engineering/`):

```bash
# 1. fast smoke test (~0.5s) into /tmp
python3 data/generator/generate_dimensions.py --small --out-dir /tmp/zgen
python3 data/generator/generate_facts.py      --small --out-dir /tmp/zgen

# 2. the real thing (~2.3 GB) into data/raw
python3 data/generator/generate_dimensions.py            # 148,541 restaurants, 200k users, 8k food
python3 data/generator/generate_facts.py                 # 10M orders, ~23M items, 300k reviews
```

`--out-dir` defaults to `data/raw` **resolved against the project root**
(`Path(__file__).resolve().parents[2]`), never the current working directory.
Relative `--out-dir` values are joined to the project root; absolute ones are
used as-is.

## Output layout

One file per table, `<out-dir>/<table>/<table>.csv`:

```
data/raw/
├── restaurants/restaurants.csv     148,541 rows
├── users/users.csv                 200,000 rows
├── food/food.csv                     8,000 rows
├── menu/menu.csv                   891,246 rows   (restaurants × menu-per-restaurant)
├── orders/orders.csv            10,000,000 rows
├── order_items/order_items.csv  ~23,000,000 rows
└── reviews/reviews.csv             300,000 rows
```

Upload each folder to `s3://<bucket>/raw/<table>/` before running the
Snowflake `COPY INTO` statements in `snowflake/05_copy_into.sql`.

## CLI reference

Both scripts accept `--out-dir`, `--seed`, `--small` and `--help`.

### `generate_dimensions.py`

| Flag | Default | Meaning |
|---|---|---|
| `--restaurants N` | `148541` | restaurant rows |
| `--users N` | `200000` | user rows |
| `--food N` | `8000` | distinct food items |
| `--menu-per-restaurant N` | `6` | menu rows per restaurant (≈891k total) |
| `--seed N` | `42` | RNG seed |
| `--small` | off | 500 / 2000 / 300 / 3 preset |

### `generate_facts.py`

| Flag | Default | Meaning |
|---|---|---|
| `--orders N` | `10000000` | order rows |
| `--reviews N` | `300000` | review rows (Delivered orders only) |
| `--order-items-mean M` | `2.3` | mean line items per order |
| `--start-date YYYY-MM-DD` | `2024-01-01` | first possible order date |
| `--end-date YYYY-MM-DD` | `2026-12-31` | last possible order date |
| `--seed N` | `42` | RNG seed |
| `--small` | off | 20,000 orders / 2,000 reviews preset |

`--small` is a preset: any explicitly-passed size flag overrides it.
`generate_facts.py` reads `restaurants.csv`, `users.csv`, `food.csv` and (when
present) `menu.csv` from the same `--out-dir` and **exits with an error telling
you to run `generate_dimensions.py` first** if they are missing.

Run either script directly (`python3 data/generator/generate_dimensions.py`) or
as a module (`python3 -m data.generator.generate_dimensions`).

## CSV contract (Snowflake `COPY INTO`)

Loaded positionally after `SKIP_HEADER = 1`, with
`FIELD_OPTIONALLY_ENCLOSED_BY = '"'`, `EMPTY_FIELD_AS_NULL = TRUE`,
`NULL_IF = ('', '\N', 'NULL')`, `ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE`.

The four **dimension** files carry a leading unnamed index column, so their
header line starts with a comma. The three **fact** files do not.

```text
restaurants  ,id,name,city,rating,rating_count,cost,cuisine,lic_no,link,address,menu
users        ,user_id,name,email,password,Age,Gender,Marital Status,Occupation,Monthly Income,Educational Qualifications,Family size
food         ,f_id,item,veg_or_non_veg
menu         ,menu_id,r_id,f_id,cuisine,price
orders       order_id,order_timestamp,order_date,user_id,r_id,restaurant_city,cuisine,items_count,sales_qty,subtotal,discount,delivery_fee,gst,sales_amount,currency,payment_method,order_status,customer_rating,delivery_time_min
order_items  order_item_id,order_id,r_id,f_id,price,quantity,line_amount
reviews      review_id,order_id,user_id,restaurant_id,rating,comment,review_date
```

Every writer is opened with `newline=""` and constructed with an explicit
`lineterminator="\n"`, so **no `\r` byte ever appears** in the output. This
matches Snowflake's default `RECORD_DELIMITER = '\n'`; without it a stray `\r`
would land on the last column of every row (`line_amount`, `price`,
`review_date`, `delivery_time_min`) and break numeric/date parsing.

## Deliberately messy dimensions

The dimensions simulate real, dirty source data and the dbt staging models in
`zomato/models/staging/` clean them:

| Column | Messiness | Downstream fix |
|---|---|---|
| `restaurants.rating` | decimal string (`4.1`), ~12% `--`, a few `NEW`, never empty | `try_to_decimal(nullif(rating,'--'),3,1)` |
| `restaurants.rating_count` | `50+ ratings` / `1234 ratings` (no thousands separators) | `regexp_substr(rating_count,'[0-9]+')` |
| `restaurants.cost` | `₹ 200` / `₹ 200 for two` (no separators, no decimals) | `regexp_substr(cost,'[0-9]+')` |
| `restaurants.city` | always `"<Area>, <City>"` | text after the last comma |
| `users.gender` | `Male` / `male` / `M` / `Female` / `female` / `F` | normalised in staging |
| `users.email` | mixed case (`Rahul.Sharma@Gmail.com`) | `lower(email)` |
| `users.age` / `family_size` | plain integers; ~3% of `age` is literal `NA` | `try_to_number` → null |
| `users.monthly_income` | `25000`, `50000`, … or `No Income` | kept as a string band |
| `food.veg_or_non_veg` | `Veg` / `non-veg` / `VEG` mixed casing | `initcap` |
| `food` short rows | ~0.5% write only `(idx, f_id, item)` — the trailing `veg_or_non_veg` is omitted | `ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE` null-fills the last column. Only the *trailing* field is dropped, so `food_name` is never null |
| `menu.price` | plain numeric (`250`, `349.50`), never `₹`, always `> 0` | `try_to_decimal(price,10,2) > 0` |

## Clean facts

- `order_id`, `order_item_id`, `review_id` are independent sequences starting at 1.
- Line items per order follow `1 + truncated-exponential`, capped at 8, with the
  rate calibrated so the realised mean equals `--order-items-mean` (2.3).
- `subtotal` / `sales_qty` / `items_count` are derived from the emitted line items.
- `discount` is 0 for ~45% of orders, otherwise 5–30% of `subtotal`.
- `delivery_fee ∈ {0, 15, 25, 35, 49}`; `gst = 0.05 × (subtotal − discount)`;
  `sales_amount = subtotal − discount + delivery_fee + gst`; currency always `INR`.
- `order_status` is only ever `Delivered` (≈85%), `Cancelled` (≈8%), `Refunded` (≈7%).
- `customer_rating` (1–5) and `delivery_time_min` (15–90) are **empty** for
  `Cancelled` / `Refunded`, so Snowflake stores NULL. Delivery time is drawn from
  a per-city distribution, so p50/p90 differ by city.
- `order_timestamp` / `order_date` are spread uniformly across the range and are
  **strictly increasing** with `order_id`, so incremental watermarks
  (`where order_timestamp > (select max(...))`) work.
- `reviews` exist only for `Delivered` orders; `rating` is ~60% 4–5, ~25% 3,
  ~15% 1–2; `comment` is never empty, comes from rating-appropriate templates
  and often contains commas (exercising CSV quoting).
- Referential integrity holds: every `orders.user_id` / `orders.r_id`,
  `order_items.order_id` / `.r_id` / `.f_id` and `reviews.order_id` / `.user_id`
  / `.restaurant_id` exists in the dimensions.

## Determinism

`--seed` makes the output **byte-for-byte reproducible**. Two independent runs
with the same seed and same sizes produce identical files. Prices are derived
with `zlib.crc32` (not Python's salted built-in `hash`), and the orders and
reviews use separate RNG streams so changing `--reviews` never perturbs
`orders.csv` / `order_items.csv`.

## Performance & memory

- Dimensions: ~a few seconds for the full 148k restaurants / 891k menu rows.
- Facts: a single streaming pass over 10M orders / ~23M items / 300k reviews;
  progress is reported to **stderr** every 1,000,000 rows emitted.
- Memory stays flat: only the dimension lookup columns (restaurant id/city/
  cuisine, user ids, food ids + a cached base price, and a compact
  per-restaurant menu index) plus the review-target offset set are resident —
  no row buffers, no per-row string concatenation.
