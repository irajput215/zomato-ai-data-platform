-- =============================================================================
-- 05 · Load RAW from S3 (COPY INTO)
-- =============================================================================
-- Run after 03 (stage exists) and 04 (tables exist).
--
-- ON_ERROR semantics used here
--   'CONTINUE'        skip the bad row, keep loading, report it in the result.
--                     Right for the messy real-world dimension files.
--   'ABORT_STATEMENT' fail the whole statement on the first bad row. Right for
--                     the generated fact files: a parse error there means the
--                     generator or the file format is wrong, and silently
--                     dropping rows would corrupt every downstream number.
--
-- Re-running is safe and cheap. Snowflake records the files it has already
-- loaded in the table's load metadata, so a second run processes zero files
-- unless you pass FORCE = TRUE.
-- =============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE ZOMATO;
USE SCHEMA RAW;
USE WAREHOUSE ZOMATO_WH;

-- -----------------------------------------------------------------------------
-- Dimensions — tolerate and skip bad rows
-- -----------------------------------------------------------------------------
COPY INTO RAW.restaurants FROM @ZOMATO_RAW_STAGE/restaurants/ ON_ERROR = 'CONTINUE';
COPY INTO RAW.users       FROM @ZOMATO_RAW_STAGE/users/       ON_ERROR = 'CONTINUE';
COPY INTO RAW.food        FROM @ZOMATO_RAW_STAGE/food/        ON_ERROR = 'CONTINUE';
COPY INTO RAW.menu        FROM @ZOMATO_RAW_STAGE/menu/        ON_ERROR = 'CONTINUE';

-- -----------------------------------------------------------------------------
-- Facts — strict, so the row counts are exact
-- -----------------------------------------------------------------------------
COPY INTO RAW.orders      FROM @ZOMATO_RAW_STAGE/orders/      ON_ERROR = 'ABORT_STATEMENT';
COPY INTO RAW.order_items FROM @ZOMATO_RAW_STAGE/order_items/ ON_ERROR = 'ABORT_STATEMENT';
COPY INTO RAW.reviews     FROM @ZOMATO_RAW_STAGE/reviews/     ON_ERROR = 'ABORT_STATEMENT';

-- -----------------------------------------------------------------------------
-- Sanity check
-- -----------------------------------------------------------------------------
-- Expected at default generator scale:
--   orders      10,000,000
--   order_items ~23,000,000
--   reviews        300,000
--   restaurants    148,541  (or whatever --restaurants you generated)
SELECT 'restaurants' AS table_name, COUNT(*) AS rows_loaded FROM RAW.restaurants
UNION ALL SELECT 'users',       COUNT(*) FROM RAW.users
UNION ALL SELECT 'food',        COUNT(*) FROM RAW.food
UNION ALL SELECT 'menu',        COUNT(*) FROM RAW.menu
UNION ALL SELECT 'orders',      COUNT(*) FROM RAW.orders
UNION ALL SELECT 'order_items', COUNT(*) FROM RAW.order_items
UNION ALL SELECT 'reviews',     COUNT(*) FROM RAW.reviews
ORDER BY table_name;

-- Inspect any rows the dimension loads rejected (ON_ERROR = 'CONTINUE').
-- Empty is what you want; a handful of rows is normal for messy source data.
SELECT *
FROM TABLE(VALIDATE(RAW.restaurants, JOB_ID => '_last'))
LIMIT 20;

-- -----------------------------------------------------------------------------
-- Reload from scratch, if you ever need to (destructive)
-- -----------------------------------------------------------------------------
-- TRUNCATE TABLE RAW.orders;
-- COPY INTO RAW.orders FROM @ZOMATO_RAW_STAGE/orders/ FORCE = TRUE ON_ERROR = 'ABORT_STATEMENT';

-- -----------------------------------------------------------------------------
-- OPTIONAL — auto-ingest new files with Snowpipe instead of a daily COPY.
-- The DAG in airflow/dags/zomato_batch.py uses the batch path above; this is the
-- streaming alternative. Remember to wire the pipe's notification channel
-- (SHOW PIPES -> notification_channel) to an S3 event notification.
-- -----------------------------------------------------------------------------
-- CREATE PIPE RAW.orders_pipe AUTO_INGEST = TRUE AS
--   COPY INTO RAW.orders FROM @ZOMATO_RAW_STAGE/orders/;

SELECT '05_copy_into complete' AS status;
