-- =============================================================================
-- 02 · Secure S3 <-> Snowflake link (storage integration)
-- =============================================================================
-- This is the production way to read a bucket: Snowflake assumes an IAM role
-- via STS. No AWS access keys are ever stored in Snowflake.
--
-- ORDER OF OPERATIONS — the order matters, and step D is the one everybody
-- gets wrong. Full click-by-click detail is in RUNBOOK.md.
--
--   A. AWS  : create IAM policy `zomato-s3-read`      (aws/iam/s3-read-policy.json)
--   B. AWS  : create IAM role `snowflake-zomato-role` and attach the policy.
--             Give it the PLACEHOLDER trust policy first
--             (aws/iam/snowflake-role-trust-policy-initial.json).
--   C. HERE : run CREATE STORAGE INTEGRATION below with that role's ARN.
--   D. HERE : run DESC INTEGRATION and copy two values out of it:
--               STORAGE_AWS_IAM_USER_ARN  -> the "AWS" principal in AWS
--               STORAGE_AWS_EXTERNAL_ID   -> the sts:ExternalId condition
--   E. AWS  : replace the role's trust policy with the FINAL one
--             (aws/iam/snowflake-role-trust-policy-final.json), filled in.
--
-- TWO HARD-WON LESSONS
--   1. The trust principal must be Snowflake's generated IAM *user* ARN
--      (arn:aws:iam::<account>:user/<prefix>-<snowflake-account>), NOT
--      :root. Using :root silently fails the handshake.
--   2. Never re-run CREATE OR REPLACE on an existing integration. It mints a
--      NEW external ID, which invalidates the trust policy you already wired
--      up and breaks every load until you redo step E.
--      Use CREATE ... IF NOT EXISTS, or ALTER, once it exists.
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- >>> EDIT THESE TWO VALUES <<<
--   <ROLE_ARN> : arn:aws:iam::<your-account-id>:role/snowflake-zomato-role
--   <BUCKET>   : your bucket name, e.g. zomato-datalake-yourname
--
-- Keep the trailing slashes. STORAGE_ALLOWED_LOCATIONS is what stops a
-- compromised Snowflake account from reading the rest of your AWS estate.

CREATE STORAGE INTEGRATION IF NOT EXISTS ZOMATO_S3_INT
  TYPE                      = EXTERNAL_STAGE
  STORAGE_PROVIDER          = 'S3'
  ENABLED                   = TRUE
  STORAGE_AWS_ROLE_ARN      = '<ROLE_ARN>'
  STORAGE_ALLOWED_LOCATIONS = ('s3://<BUCKET>/raw/')
  COMMENT                   = 'Keyless read access to the Zomato raw bucket.';

-- Only DBT_ROLE needs it; the read-only AI role never touches the lake.
GRANT USAGE ON INTEGRATION ZOMATO_S3_INT TO ROLE DBT_ROLE;

-- -----------------------------------------------------------------------------
-- Step D — read the two values you must paste into the IAM trust policy.
-- -----------------------------------------------------------------------------
DESC INTEGRATION ZOMATO_S3_INT;
--   property                    | where it goes in AWS
--   ----------------------------+--------------------------------------------
--   STORAGE_AWS_IAM_USER_ARN    | Statement.Principal.AWS
--   STORAGE_AWS_EXTERNAL_ID     | Statement.Condition.StringEquals["sts:ExternalId"]
--
-- Copy both exactly. The external ID is case sensitive.

-- If you ever DO need to rotate, drop and recreate deliberately, then redo
-- step E immediately:
--   DROP INTEGRATION IF EXISTS ZOMATO_S3_INT;
