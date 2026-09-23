-- =============================================================================
-- 03 · External stage on S3 + CSV file format
-- =============================================================================
-- Run after 02. Replace <BUCKET> with your bucket name (no "s3://" and no
-- trailing slash — the URL below adds those).
--
-- The stage points at s3://<BUCKET>/raw/ and the layout underneath it is one
-- folder per table, exactly mirroring data/raw/ locally:
--
--   raw/restaurants/restaurants.csv
--   raw/users/users.csv
--   raw/food/food.csv
--   raw/menu/menu.csv
--   raw/orders/orders.csv
--   raw/order_items/order_items.csv
--   raw/reviews/reviews.csv
-- =============================================================================

USE ROLE ACCOUNTADMIN;
USE DATABASE ZOMATO;
USE SCHEMA RAW;

-- -----------------------------------------------------------------------------
-- File format
-- -----------------------------------------------------------------------------
-- Notes on the settings that actually matter for this dataset:
--
--   SKIP_HEADER = 1                  every CSV keeps its header row
--   FIELD_OPTIONALLY_ENCLOSED_BY     review comments and "Area, City" contain
--                                    commas, so quoted fields must survive
--   NULL_IF includes '' and 'NA'     the messy dimension files use both to mean
--                                    "unknown" (e.g. users.age = 'NA')
--   ERROR_ON_COLUMN_COUNT_MISMATCH   food.csv has a handful of rows missing a
--     = FALSE                        trailing field; NULL-fill them instead of
--                                    aborting the whole load
--   RECORD_DELIMITER = '\n'          the generator writes '\n' line endings
--                                    (never '\r\n' — a stray \r lands in the
--                                    last column and breaks numeric parsing)
--   REPLACE_INVALID_CHARACTERS       the ₹ symbol in restaurants.cost is
--                                    multi-byte UTF-8 and the CSVs are not
--                                    always perfectly encoded
CREATE OR REPLACE FILE FORMAT ZOMATO.RAW.CSV_FMT
  TYPE                           = 'CSV'
  COMPRESSION                    = 'AUTO'
  FIELD_DELIMITER                = ','
  RECORD_DELIMITER               = '\n'
  FIELD_OPTIONALLY_ENCLOSED_BY   = '"'
  SKIP_HEADER                    = 1
  EMPTY_FIELD_AS_NULL            = TRUE
  NULL_IF                        = ('', '\\N', 'NULL', 'null', 'NA', 'N/A')
  TRIM_SPACE                     = FALSE
  ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
  REPLACE_INVALID_CHARACTERS     = TRUE
  DATE_FORMAT                    = 'YYYY-MM-DD'
  TIMESTAMP_FORMAT               = 'YYYY-MM-DD HH24:MI:SS'
  COMMENT                        = 'Plain CSV, header row kept, quoted fields honoured.';

-- -----------------------------------------------------------------------------
-- External stage
-- -----------------------------------------------------------------------------
-- >>> EDIT <BUCKET> <<<
CREATE OR REPLACE STAGE ZOMATO.RAW.ZOMATO_RAW_STAGE
  STORAGE_INTEGRATION = ZOMATO_S3_INT
  URL                 = 's3://<BUCKET>/raw/'
  FILE_FORMAT         = ZOMATO.RAW.CSV_FMT
  COMMENT             = 'Raw CSV landing zone, one folder per table.';

-- -----------------------------------------------------------------------------
-- Verify
-- -----------------------------------------------------------------------------
-- Should list the seven table folders and their CSV files. If this returns
-- nothing, the storage integration trust policy is wrong — go back to 02.
LIST @ZOMATO.RAW.ZOMATO_RAW_STAGE;

-- Peek at the raw text before you create any tables: this is the fastest way to
-- confirm headers, delimiters and quoting are what you expect.
SELECT
  METADATA$FILENAME              AS file_name,
  METADATA$FILE_ROW_NUMBER       AS row_number,
  $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
FROM @ZOMATO.RAW.ZOMATO_RAW_STAGE/restaurants/
  (FILE_FORMAT => 'ZOMATO.RAW.CSV_FMT')
LIMIT 5;
