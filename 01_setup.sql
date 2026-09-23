-- =============================================================================
-- 01 · Warehouse, database, schemas, roles
-- =============================================================================
-- Run in a Snowsight worksheet as ACCOUNTADMIN.
-- Everything here is idempotent (IF NOT EXISTS), so it is safe to re-run.
--
--   Role layout
--   -----------
--   DBT_ROLE        read/write  — used by dbt and the Airflow load task
--   ZOMATO_AI_RO    read-only   — used by the Streamlit text-to-SQL app
--
-- Giving the text-to-SQL app a SELECT-only role is defence in depth: even if
-- the LLM is tricked into emitting a write statement, the role cannot execute
-- it. See snowflake/06_grants_and_monitoring.sql.
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- -----------------------------------------------------------------------------
-- Compute
-- -----------------------------------------------------------------------------
-- XSMALL with aggressive auto-suspend keeps trial credits alive. dbt's
-- incremental models mean a re-run only touches new rows, so a small warehouse
-- is genuinely enough for the 10M-row fact tables.
CREATE WAREHOUSE IF NOT EXISTS ZOMATO_WH
  WAREHOUSE_SIZE      = 'XSMALL'
  AUTO_SUSPEND        = 60
  AUTO_RESUME         = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT             = 'Compute for the Zomato batch pipeline (dbt + COPY INTO).';

-- -----------------------------------------------------------------------------
-- Database + medallion schemas
-- -----------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS ZOMATO
  COMMENT = 'Zomato food-delivery analytics — medallion architecture.';

CREATE SCHEMA IF NOT EXISTS ZOMATO.RAW
  COMMENT = 'Bronze. Tables loaded verbatim from S3 with COPY INTO.';
CREATE SCHEMA IF NOT EXISTS ZOMATO.STAGING
  COMMENT = 'Silver. dbt views that clean, type and rename every RAW source.';
CREATE SCHEMA IF NOT EXISTS ZOMATO.MARTS
  COMMENT = 'Gold. Dimensions, incremental facts, business marts.';
CREATE SCHEMA IF NOT EXISTS ZOMATO.SNAPSHOTS
  COMMENT = 'SCD2 history produced by dbt snapshots.';
CREATE SCHEMA IF NOT EXISTS ZOMATO.AI
  COMMENT = 'LLM-enriched tables written by ai/enrich_reviews.py.';
CREATE SCHEMA IF NOT EXISTS ZOMATO.ADMIN
  COMMENT = 'Operational views: pipeline health, freshness, row-count monitoring.';

-- -----------------------------------------------------------------------------
-- Roles
-- -----------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS DBT_ROLE
  COMMENT = 'Read/write role for dbt and the Airflow ingestion + transform tasks.';
CREATE ROLE IF NOT EXISTS ZOMATO_AI_RO
  COMMENT = 'Read-only role for the Streamlit text-to-SQL and dashboard apps.';

-- -----------------------------------------------------------------------------
-- Warehouse access
-- -----------------------------------------------------------------------------
GRANT USAGE   ON WAREHOUSE ZOMATO_WH TO ROLE DBT_ROLE;
GRANT OPERATE ON WAREHOUSE ZOMATO_WH TO ROLE DBT_ROLE;
GRANT USAGE   ON WAREHOUSE ZOMATO_WH TO ROLE ZOMATO_AI_RO;

-- -----------------------------------------------------------------------------
-- DBT_ROLE — full control of the ZOMATO database (including future objects,
-- so dbt can create new models without a follow-up grant).
-- -----------------------------------------------------------------------------
GRANT USAGE ON DATABASE ZOMATO TO ROLE DBT_ROLE;

GRANT ALL ON SCHEMA ZOMATO.RAW       TO ROLE DBT_ROLE;
GRANT ALL ON SCHEMA ZOMATO.STAGING   TO ROLE DBT_ROLE;
GRANT ALL ON SCHEMA ZOMATO.MARTS     TO ROLE DBT_ROLE;
GRANT ALL ON SCHEMA ZOMATO.SNAPSHOTS TO ROLE DBT_ROLE;
GRANT ALL ON SCHEMA ZOMATO.AI        TO ROLE DBT_ROLE;
GRANT ALL ON SCHEMA ZOMATO.ADMIN     TO ROLE DBT_ROLE;

GRANT ALL ON ALL    TABLES IN DATABASE ZOMATO TO ROLE DBT_ROLE;
GRANT ALL ON FUTURE TABLES IN DATABASE ZOMATO TO ROLE DBT_ROLE;
GRANT ALL ON ALL    VIEWS  IN DATABASE ZOMATO TO ROLE DBT_ROLE;
GRANT ALL ON FUTURE VIEWS  IN DATABASE ZOMATO TO ROLE DBT_ROLE;

-- -----------------------------------------------------------------------------
-- ZOMATO_AI_RO — SELECT only, and only on the layers the apps read.
-- -----------------------------------------------------------------------------
GRANT USAGE ON DATABASE ZOMATO TO ROLE ZOMATO_AI_RO;

GRANT USAGE ON SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT USAGE ON SCHEMA ZOMATO.MARTS   TO ROLE ZOMATO_AI_RO;
GRANT USAGE ON SCHEMA ZOMATO.AI      TO ROLE ZOMATO_AI_RO;

GRANT SELECT ON ALL    TABLES IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON ALL    VIEWS  IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ZOMATO.STAGING TO ROLE ZOMATO_AI_RO;

GRANT SELECT ON ALL    TABLES IN SCHEMA ZOMATO.MARTS TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ZOMATO.MARTS TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON ALL    VIEWS  IN SCHEMA ZOMATO.MARTS TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON FUTURE VIEWS  IN SCHEMA ZOMATO.MARTS TO ROLE ZOMATO_AI_RO;

GRANT SELECT ON ALL    TABLES IN SCHEMA ZOMATO.AI TO ROLE ZOMATO_AI_RO;
GRANT SELECT ON FUTURE TABLES IN SCHEMA ZOMATO.AI TO ROLE ZOMATO_AI_RO;

-- -----------------------------------------------------------------------------
-- Let the human running this script use both roles.
-- Replace with an explicit username if you prefer, e.g.
--   GRANT ROLE DBT_ROLE TO USER my_login;
-- -----------------------------------------------------------------------------
SET my_user = CURRENT_USER();
GRANT ROLE DBT_ROLE     TO USER IDENTIFIER($my_user);
GRANT ROLE ZOMATO_AI_RO TO USER IDENTIFIER($my_user);

-- -----------------------------------------------------------------------------
-- Verify
-- -----------------------------------------------------------------------------
SHOW SCHEMAS IN DATABASE ZOMATO;

SELECT '01_setup complete' AS status;
