-- =============================================================================
-- 06 · Cost guards, grants and pipeline monitoring
-- =============================================================================
-- Run LAST, after 05, because the monitoring view reads the RAW tables.
-- Everything here is idempotent.
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- -----------------------------------------------------------------------------
-- Cost guard — a resource monitor that suspends the warehouse before it can
-- quietly burn a trial account's credits.
-- -----------------------------------------------------------------------------
CREATE RESOURCE MONITOR IF NOT EXISTS ZOMATO_MONITOR
  WITH CREDIT_QUOTA = 50
       FREQUENCY    = MONTHLY
       START_TIMESTAMP = IMMEDIATELY
  TRIGGERS
    ON 75  PERCENT DO NOTIFY
    ON 90  PERCENT DO NOTIFY
    ON 100 PERCENT DO SUSPEND;

ALTER WAREHOUSE ZOMATO_WH SET RESOURCE_MONITOR = ZOMATO_MONITOR;

-- A single runaway query cannot hold the XSMALL warehouse open for a day.
ALTER WAREHOUSE ZOMATO_WH SET STATEMENT_TIMEOUT_IN_SECONDS = 3600;

-- -----------------------------------------------------------------------------
-- Re-assert read-only grants.
-- dbt creates NEW tables on every run; "ON FUTURE" from 01_setup covers that,
-- but re-running this block after a big `dbt build` is a cheap safety net.
-- -----------------------------------------------------------------------------
GRANT USAGE ON DATABASE ZOMATO TO ROLE ZOMATO_AI_RO;

GRANT USAGE ON SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT USAGE ON SCHEMA ZOMATO.MARTS   TO ROLE ZOMATO_AI_RO;
GRANT USAGE ON SCHEMA ZOMATO.AI      TO ROLE ZOMATO_AI_RO;

GRANT SELECT ON ALL TABLES IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON ALL VIEWS  IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON ALL TABLES IN SCHEMA ZOMATO.MARTS   TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON ALL TABLES IN SCHEMA ZOMATO.AI      TO ROLE ZOMATO_AI_RO;

-- SANITY: the read-only role must NOT be able to write. This should fail with
-- "Insufficient privileges" — that failure is the point. Run it in a worksheet
-- as ZOMATO_AI_RO:
--   USE ROLE ZOMATO_AI_RO;
--   CREATE TABLE ZOMATO.MARTS.should_not_exist (x INT);

-- -----------------------------------------------------------------------------
-- Monitoring view — one row per raw table, with row counts.
-- This is what a freshness/volume alert would read.
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS ZOMATO.ADMIN;
GRANT ALL ON SCHEMA ZOMATO.ADMIN TO ROLE DBT_ROLE;

CREATE OR REPLACE VIEW ZOMATO.ADMIN.PIPELINE_HEALTH
  COMMENT = 'Row counts for every RAW table plus the AI enrichment backlog.'
AS
SELECT 'RAW.restaurants' AS object_name, COUNT(*) AS row_count FROM ZOMATO.RAW.restaurants
UNION ALL SELECT 'RAW.users',       COUNT(*) FROM ZOMATO.RAW.users
UNION ALL SELECT 'RAW.food',        COUNT(*) FROM ZOMATO.RAW.food
UNION ALL SELECT 'RAW.menu',        COUNT(*) FROM ZOMATO.RAW.menu
UNION ALL SELECT 'RAW.orders',      COUNT(*) FROM ZOMATO.RAW.orders
UNION ALL SELECT 'RAW.order_items', COUNT(*) FROM ZOMATO.RAW.order_items
UNION ALL SELECT 'RAW.reviews',     COUNT(*) FROM ZOMATO.RAW.reviews;

GRANT SELECT ON VIEW ZOMATO.ADMIN.PIPELINE_HEALTH TO ROLE ZOMATO_AI_RO;

-- Reviews still waiting on the LLM enrichment job (drives SAMPLE_N sizing).
CREATE OR REPLACE VIEW ZOMATO.ADMIN.AI_ENRICHMENT_BACKLOG
  COMMENT = 'Reviews not yet enriched — the enrich_reviews.py work queue.'
AS
SELECT COUNT(*) AS reviews_waiting
FROM ZOMATO.RAW.reviews r
WHERE NOT EXISTS (
  SELECT 1 FROM ZOMATO.AI.REVIEW_ENRICHED e
  WHERE e.review_id = r.review_id::STRING
);

GRANT SELECT ON VIEW ZOMATO.ADMIN.AI_ENRICHMENT_BACKLOG TO ROLE ZOMATO_AI_RO;

SELECT '06_grants_and_monitoring complete' AS status;
