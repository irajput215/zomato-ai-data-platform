-- =============================================================================
-- 04 · RAW (Bronze) tables
-- =============================================================================
-- Column ORDER is the contract: raw/<table>/<table>.csv is loaded positionally
-- after the header row is skipped, so the column order here must match the CSV
-- exactly. Every column is STRING except the generated fact files, which are
-- clean and typed — typing them here lets COPY INTO reject genuinely bad rows.
--
-- The four DIMENSION files (restaurants, users, food, menu) carry a leading
-- unnamed pandas index column, so those tables start with a throwaway `_idx`.
-- The three FACT files (orders, order_items, reviews) have no index column.
-- =============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE ZOMATO;
USE SCHEMA RAW;
USE WAREHOUSE ZOMATO_WH;

-- -----------------------------------------------------------------------------
-- Dimensions — deliberately messy source data, all STRING
-- -----------------------------------------------------------------------------

-- restaurants.csv: ,id,name,city,rating,rating_count,cost,cuisine,lic_no,link,address,menu
-- Messy on purpose: rating can be '--' or 'NEW', rating_count looks like
-- '50+ ratings', cost looks like '₹ 200', city looks like 'Koramangala, Bangalore'.
-- stg_restaurants is where all of that gets cleaned.
CREATE OR REPLACE TABLE RAW.restaurants (
  _idx         STRING,   -- leading index column from the CSV, ignored downstream
  id           STRING,
  name         STRING,
  city         STRING,
  rating       STRING,
  rating_count STRING,
  cost         STRING,
  cuisine      STRING,
  lic_no       STRING,
  link         STRING,
  address      STRING,
  menu         STRING
);

-- users.csv: ,user_id,name,email,password,Age,Gender,Marital Status,Occupation,
--            Monthly Income,Educational Qualifications,Family size
-- Header names are never used (SKIP_HEADER = 1); these are the canonical names.
CREATE OR REPLACE TABLE RAW.users (
  _idx             STRING,   -- leading index column from the CSV
  user_id          STRING,
  name             STRING,
  email            STRING,
  password         STRING,
  age              STRING,
  gender           STRING,
  marital_status   STRING,
  occupation       STRING,
  monthly_income   STRING,
  education        STRING,
  family_size      STRING
);

-- food.csv: ,f_id,item,veg_or_non_veg
-- A small number of rows are missing the trailing field; the file format
-- NULL-fills them rather than failing the load.
CREATE OR REPLACE TABLE RAW.food (
  _idx           STRING,   -- leading index column from the CSV
  f_id           STRING,
  item           STRING,
  veg_or_non_veg STRING
);

-- menu.csv: ,menu_id,r_id,f_id,cuisine,price
CREATE OR REPLACE TABLE RAW.menu (
  _idx     STRING,   -- leading index column from the CSV
  menu_id  STRING,
  r_id     STRING,
  f_id     STRING,
  cuisine  STRING,
  price    STRING
);

-- -----------------------------------------------------------------------------
-- Facts — clean generated data, typed
-- -----------------------------------------------------------------------------

-- orders.csv — 10,000,000 rows at default scale.
CREATE OR REPLACE TABLE RAW.orders (
  order_id          NUMBER,
  order_timestamp   TIMESTAMP_NTZ,
  order_date        DATE,
  user_id           NUMBER,
  r_id              NUMBER,
  restaurant_city   STRING,   -- "<Area>, <City>"; stg_orders keeps the city
  cuisine           STRING,
  items_count       NUMBER,
  sales_qty         NUMBER,
  subtotal          NUMBER,
  discount          NUMBER,
  delivery_fee      NUMBER,
  gst               NUMBER,
  sales_amount      NUMBER,
  currency          STRING,
  payment_method    STRING,
  order_status      STRING,   -- Delivered | Cancelled | Refunded
  customer_rating   NUMBER,   -- NULL for Cancelled / Refunded
  delivery_time_min NUMBER    -- NULL for Cancelled / Refunded
);

-- order_items.csv — ~23,000,000 rows at default scale (≈2.3 lines per order).
CREATE OR REPLACE TABLE RAW.order_items (
  order_item_id NUMBER,
  order_id      NUMBER,
  r_id          NUMBER,
  f_id          STRING,
  price         NUMBER,
  quantity      NUMBER,
  line_amount   NUMBER
);

-- reviews.csv — 300,000 rows. This free text is what the AI layer enriches.
CREATE OR REPLACE TABLE RAW.reviews (
  review_id     NUMBER,
  order_id      NUMBER,
  user_id       NUMBER,
  restaurant_id NUMBER,
  rating        NUMBER,
  comment       STRING,
  review_date   DATE
);

-- -----------------------------------------------------------------------------
-- Verify the shapes landed as expected
-- -----------------------------------------------------------------------------
SHOW COLUMNS IN TABLE RAW.restaurants;
SHOW COLUMNS IN TABLE RAW.orders;

SELECT '04_raw_tables complete' AS status;
