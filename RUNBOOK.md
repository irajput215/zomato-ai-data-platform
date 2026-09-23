# RUNBOOK — from zero to a running pipeline

Follow this once. It takes about 45 minutes, most of which is AWS console
clicking and a first `dbt build` over 33 million rows.

Everything here is idempotent and every step tells you how to check it worked
before you move on. If something breaks, jump to [Troubleshooting](#troubleshooting)
at the bottom — the error messages there are the real ones.

**Order matters in steps 4–7.** The AWS role and the Snowflake storage
integration have a circular dependency (each needs a value from the other), and
the placeholder-then-final trust policy dance is how that is resolved.

---

## 0 · Prerequisites

| Need | Notes |
|---|---|
| Snowflake account | The 30-day trial is more than enough. `ACCOUNTADMIN` access required. |
| AWS account | Free tier is fine. S3 + IAM only — no compute. |
| Python 3.9+ | For the generator, the upload scripts and the AI apps. |
| Docker Desktop | For Airflow. Give it at least 4 GB of RAM. |
| OpenAI API key | Only needed for step 11. `gpt-4o-mini` costs cents for a demo. |
| AWS CLI (optional) | The console steps have CLI equivalents below each one. |

```bash
git clone <your-fork> zomato-ai-data-engineering
cd zomato-ai-data-engineering
cp .env.example .env      # fill this in as you go
pip install -r ai/requirements.txt -r ingestion/requirements.txt -r requirements-dev.txt
```

---

## 1 · Snowflake: warehouse, database, schemas, roles

Open a Snowsight worksheet and run **`snowflake/01_setup.sql`** top to bottom.

This creates:

* warehouse `ZOMATO_WH` (XSMALL, auto-suspend 60s)
* database `ZOMATO` with schemas `RAW`, `STAGING`, `MARTS`, `SNAPSHOTS`, `AI`, `ADMIN`
* role `DBT_ROLE` — read/write, used by dbt and the Airflow load task
* role `ZOMATO_AI_RO` — `SELECT` only, used by the Streamlit apps

> **Why two roles?** `ZOMATO_AI_RO` is what makes the text-to-SQL app safe to put
> in front of a human. Even if the model writes a `DELETE`, the role cannot
> execute it. See step 10.

**Check**

```sql
SHOW SCHEMAS IN DATABASE ZOMATO;
-- expect: ADMIN, AI, MARTS, PUBLIC, RAW, SNAPSHOTS, STAGING
```

---

## 2 · AWS: create the bucket

Console: **S3 → Create bucket**.

* Name: `zomato-datalake-<yourname>` (globally unique)
* Region: pick one and stay in it
* Block Public Access: **on** (the default)
* Versioning: optional but cheap for a demo

CLI:

```bash
export BUCKET=zomato-datalake-yourname
export REGION=us-east-1
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
```

Put the bucket name in `.env` as `S3_BUCKET`.

> Why a separate bucket rather than a prefix in an existing one? Because the
> Snowflake IAM policy in the next step is then scoped to exactly one resource,
> and the `STORAGE_ALLOWED_LOCATIONS` clause can name it outright. Blast radius.

---

## 3 · AWS: create the IAM policy

Console: **IAM → Policies → Create policy → JSON**. Paste
`aws/iam/s3-read-policy.json`, replacing `<BUCKET>` with your bucket name.

* Name: `zomato-s3-read`

CLI:

```bash
sed "s/<BUCKET>/$BUCKET/g" aws/iam/s3-read-policy.json > /tmp/zomato-s3-read.json
aws iam create-policy \
  --policy-name zomato-s3-read \
  --policy-document file:///tmp/zomato-s3-read.json
```

The policy grants read on `arn:aws:s3:::<BUCKET>/raw/*` only — not the whole
bucket — and allows `s3:ListBucket` only under the `raw/` prefix. Snowflake
never needs to write, and never needs to see the rest of your account.

**Check**

```bash
aws iam get-policy-version \
  --policy-arn arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):policy/zomato-s3-read \
  --version-id v1 --query 'PolicyVersion.Document'
```

---

## 4 · AWS: create the IAM role with the *placeholder* trust policy

Console: **IAM → Roles → Create role → Custom trust policy**. Paste
`aws/iam/snowflake-role-trust-policy-initial.json`, replacing `<ACCOUNT_ID>` with
your 12-digit account id.

* Name: `snowflake-zomato-role`
* Attach the policy from step 3: `zomato-s3-read`

CLI:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" \
  aws/iam/snowflake-role-trust-policy-initial.json > /tmp/trust-initial.json

aws iam create-role \
  --role-name snowflake-zomato-role \
  --assume-role-policy-document file:///tmp/trust-initial.json

aws iam attach-role-policy \
  --role-name snowflake-zomato-role \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/zomato-s3-read"
```

> This trust policy is **temporary and too broad** — it trusts your whole
> account. It exists only so the role can be created before Snowflake has told
> us its IAM user ARN. Step 6 replaces it. Do not stop here.

Note the role ARN:

```bash
echo "arn:aws:iam::${ACCOUNT_ID}:role/snowflake-zomato-role"
```

---

## 5 · Snowflake: the storage integration

Edit **`snowflake/02_storage_integration.sql`**, replacing `<ROLE_ARN>` (from the
end of step 4) and `<BUCKET>`. Run it in Snowsight as `ACCOUNTADMIN`.

```sql
CREATE STORAGE INTEGRATION IF NOT EXISTS ZOMATO_S3_INT
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::123456789012:role/snowflake-zomato-role'
  STORAGE_ALLOWED_LOCATIONS = ('s3://zomato-datalake-yourname/raw/');
```

---

## 6 · Snowflake ↠ AWS: close the loop

This is the step everyone gets wrong.

**6a.** In Snowsight:

```sql
DESC INTEGRATION ZOMATO_S3_INT;
```

Copy two values out of the result:

| Column | Where it goes |
|---|---|
| `STORAGE_AWS_IAM_USER_ARN` | the `Principal.AWS` in the trust policy |
| `STORAGE_AWS_EXTERNAL_ID` | the `sts:ExternalId` condition |

**6b.** Edit `aws/iam/snowflake-role-trust-policy-final.json` with both values,
then apply it to the role.

Console: **IAM → Roles → snowflake-zomato-role → Trust relationships → Edit**.

CLI:

```bash
# paste the two values in by hand, then:
aws iam update-assume-role-policy \
  --role-name snowflake-zomato-role \
  --policy-document file://aws/iam/snowflake-role-trust-policy-final.json
```

**6c.** Verify the handshake:

```sql
SELECT SYSTEM$VALIDATE_STORAGE_INTEGRATION('ZOMATO_S3_INT', 's3://<BUCKET>/raw/', '');
```

Two hard-won details:

* The principal must be Snowflake's generated IAM **user** ARN
  (`arn:aws:iam::<account>:user/<prefix>-<snowflake-account>`), **not** `:root`.
  `:root` here produces a silent, confusing failure later.
* **Never re-run `CREATE OR REPLACE` on an existing integration.** It mints a
  new external ID, which invalidates the trust policy you just wired up, and
  every load breaks until you redo 6a–6b. That is why the script uses
  `CREATE ... IF NOT EXISTS`.

---

## 7 · Snowflake: stage, tables, and the first load

Run these in order, editing `<BUCKET>` in `03`:

| File | Creates | Check |
|---|---|---|
| `snowflake/03_stage_and_formats.sql` | `CSV_FMT`, `ZOMATO_RAW_STAGE` | `LIST @ZOMATO.RAW.ZOMATO_RAW_STAGE;` lists your folders |
| `snowflake/04_raw_tables.sql` | the seven Bronze tables | `SHOW COLUMNS IN TABLE RAW.orders;` |
| `snowflake/05_copy_into.sql` | loads everything from S3 | the final `SELECT` shows the row counts |

`LIST` returning nothing almost always means step 6 is wrong — check the trust
policy before going any further.

The load itself needs data in the bucket, so do step 8 before `05` if you have
not uploaded anything yet.

---

## 8 · Generate and upload the data

```bash
# Full scale: 148,541 restaurants / 200,000 users / 10M orders / ~23M items / 300K reviews
make data

# Or a fast smoke test while you learn the ropes (~30 seconds)
make data-small
```

Then publish to the lake and verify it arrived:

```bash
make upload-dry-run     # show the plan, touching nothing
make upload             # the real thing (multipart, ~2.3 GB)
make verify-s3          # both directions: missing, extra, size mismatch
```

`verify_s3.py` exits non-zero on any mismatch, so a truncated upload cannot slip
through into a `COPY INTO` that "succeeds" with wrong row counts.

Now go back and run `snowflake/05_copy_into.sql`.

> **Prefer the original dataset?** `data/README.md` explains how to drop the real
> Zomato dimension CSVs into `data/raw/<table>/<table>.csv` instead. The
> generator exists so the pipeline is reproducible without a 2.3 GB download.

---

## 9 · dbt: transform

```bash
cd zomato
export SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...

dbt debug   --profiles-dir .                     # connection check first
dbt build   --exclude tag:ai --exclude resource_type:snapshot --profiles-dir .
dbt snapshot              --profiles-dir .       # SCD2 (excluded from the build above)
```

> **Why `--exclude resource_type:snapshot`?** Because `dbt build` DOES run
> snapshots — it builds models, tests, snapshots and seeds in DAG order. Without
> the exclusion the snapshot would run here *and* again on the next line. The
> exclusion gives the SCD2 step one owner, which is why the Airflow DAG can give
> it its own task, timeout and retry.

Expected: 7 staging views, 4 dimensions, 2 incremental facts, 3 business marts,
plus ~60 tests. The 10M-row `fct_orders` build is the slow part on an XSMALL
warehouse — a few minutes.

Re-run `dbt build` and notice it is much faster: the incremental models only
process rows past their watermark.

```bash
dbt docs generate --profiles-dir .
dbt docs serve    --profiles-dir .    # lineage graph, including the exposures
```

---

## 10 · Snowflake: cost guard and monitoring

Run **`snowflake/06_grants_and_monitoring.sql`**.

* a resource monitor that suspends the warehouse at 50 credits
* a 1-hour statement timeout
* `ZOMATO.ADMIN.PIPELINE_HEALTH` — row counts per raw table
* `ZOMATO.ADMIN.AI_ENRICHMENT_BACKLOG` — how many reviews still need enriching

Then prove the read-only role really is read-only. This **should fail**:

```sql
USE ROLE ZOMATO_AI_RO;
CREATE TABLE ZOMATO.MARTS.this_must_not_work (x INT);
-- SQL access control error: Insufficient privileges to operate on schema 'MARTS'
```

That error is the security control working.

---

## 11 · Airflow: schedule it

```bash
cd airflow
cp example.env .env        # fill SNOWFLAKE_ACCOUNT / USER / PASSWORD / OPENAI_API_KEY
docker compose build
docker compose up -d
```

Open <http://localhost:8080> and log in as **admin / admin**.

Un-pause `zomato_batch` and trigger it. The graph:

```
reload_raw → dbt_build_core → dbt_snapshot → enrich_reviews → dbt_build_ai → dbt_docs_generate
```

> On Linux, run `echo "AIRFLOW_UID=$(id -u)" >> airflow/.env` first, or files
> written into `airflow/logs` and `zomato/target` will be owned by root.

Watch a task's logs from the UI, or:

```bash
make airflow-logs
```

---

## 12 · The AI layer

With `OPENAI_API_KEY` set:

```bash
python ai/enrich_reviews.py --sample-n 25     # LLM as a transformation step
dbt build --select tag:ai --profiles-dir zomato   # mart_review_insights

streamlit run ai/dashboard.py     # operations dashboard over the marts
streamlit run ai/rag_chat.py      # chat with your reviews
streamlit run ai/text_to_sql.py   # chat with your warehouse
```

`--sample-n` is a spend cap, and the job is idempotent: reviews already in
`ZOMATO.AI.REVIEW_ENRICHED` are never sent to the API twice. Raise it
deliberately, not accidentally.

---

## Troubleshooting

### Snowflake

**`Not authorized to perform sts:AssumeRole`** during `COPY INTO` or `LIST`.
The trust policy is wrong. Re-run `DESC INTEGRATION ZOMATO_S3_INT` and confirm
`STORAGE_AWS_IAM_USER_ARN` is the `Principal.AWS` value — it must be an IAM
**user** ARN, not `:root` — and that `STORAGE_AWS_EXTERNAL_ID` matches
`sts:ExternalId` exactly, including case.

**`LIST @ZOMATO_RAW_STAGE` returns nothing.** Either the bucket has no `raw/`
prefix yet (run step 8), or `STORAGE_ALLOWED_LOCATIONS` does not cover the
prefix you are staging from.

**`Failed to cast variant value ... to NUMBER`** during `COPY INTO RAW.orders`.
Your CSVs were written with CRLF line endings, so a stray `\r` is sitting at the
end of the last column. The generator writes `\n` explicitly and the file format
sets `RECORD_DELIMITER = '\n'`; if you brought your own CSVs, convert them with
`dos2unix` or `sed -i 's/\r$//'`.

**`Numeric value '' is not recognized`** on a dimension load. Expected for messy
source rows — that is what `ON_ERROR = 'CONTINUE'` is for. Inspect what was
rejected with:

```sql
SELECT * FROM TABLE(VALIDATE(RAW.restaurants, JOB_ID => '_last'));
```

**`Insufficient privileges to operate on schema 'MARTS'`** from dbt. Re-run the
grant block at the end of `snowflake/06_grants_and_monitoring.sql`; `dbt build`
creates new objects on every run and the `ON FUTURE` grants must be in place.

**The warehouse is suspended and the first query is slow.** Auto-resume takes a
few seconds. That is the cost control doing its job.

### Airflow

**Tasks fail immediately with `state mismatch ... failed`.** Airflow 3 tasks call
the Execution API over HTTP. `AIRFLOW__CORE__EXECUTION_API_SERVER_URL` must point
at the api-server's **service name** (`http://apiserver:8080/execution/`), not
`localhost`. Already set correctly in `airflow/docker-compose.yaml` — this bites
people who copy a 2.x compose file.

**`dbt: command not found`.** dbt lives in its own venv at
`/opt/airflow/dbt_venv/bin/dbt` so it cannot clash with Airflow's dependencies.
The DAG references it by absolute path; do not change it to bare `dbt`.

**`ModuleNotFoundError: No module named 'common'`** in the enrichment task. The
`../ai` directory must be mounted at `/opt/airflow/ai`, and the DAG calls the
script as `/opt/airflow/ai/enrich_reviews.py` so the script's own directory is on
`sys.path`.

**`dbt_build_ai` fails on the very first run.** It reads
`ZOMATO.AI.REVIEW_ENRICHED`, which does not exist until `enrich_reviews` has run
once. Check the `enrich_reviews` task first; if `SAMPLE_N=0` or there are no
un-enriched reviews, the table is created empty and the build still succeeds.

### dbt

**`Could not find profile named 'zomato'`.** You forgot `--profiles-dir .`. Every
command in the Makefile, the DAG and CI passes it; do the same by hand.

**`Env var required but not provided: 'SNOWFLAKE_ACCOUNT'`.** `profiles.yml`
reads every credential from the environment on purpose — nothing is committed.
`export` the variables or use the project-root `.env` with `make`.

**`assert_order_items_reconcile_to_orders` fails.** The headline reconciliation
broke: an order's summary columns no longer match its line items. Usually a
partially loaded `order_items` file, or an incremental watermark that skipped a
batch. Check `ZOMATO.ADMIN.PIPELINE_HEALTH`, then re-run with
`dbt build --full-refresh --select fct_order_items+`.

**The build takes too long.** Skip the expensive tests while iterating:

```bash
dbt build --exclude tag:ai assert_order_items_reconcile_to_orders fct_order_items
```

### AI

**`openai.RateLimitError` / HTTP 429.** Lower `--workers` and let the built-in
exponential backoff do its job. `enrich_reviews.py` retries four times by
default.

**`openai.AuthenticationError` / HTTP 401.** `OPENAI_API_KEY` is unset or stale.
`ai/common.py` prints the exact `cp .env.example .env` command when it is missing.

**`ModuleNotFoundError: No module named 'snowflake.connector'`.** The AI layer has
its own dependencies: `pip install -r ai/requirements.txt`.

**`snowflake.connector.errors.ProgrammingError: Insufficient privileges`** from
the Streamlit apps. The apps connect as `ZOMATO_AI_RO`, which only has `SELECT`
on `STAGING`, `MARTS` and `AI` — not on `RAW`. If an app needs a raw table, model
it in dbt rather than widening the grant.
