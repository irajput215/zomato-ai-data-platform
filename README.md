# AI Data Platform

A complete production-grade data engineering and AI analytics platform that takes food-delivery data from
raw CSVs all the way to AI-powered analytics:

**Zomato Dataset → Amazon S3 → Snowflake → dbt → Apache Airflow → AI (DeepSeek / OpenAI)**

The dataset lands in an S3 data lake and flows into Snowflake through a keyless
storage integration, where dbt transforms it through medallion layers — **RAW**
(Bronze) tables loaded via `COPY INTO`, cleaned **STAGING** (Silver) views, and
business-ready **MARTS** (Gold) with dimensions, incremental facts, SCD2 history
and aggregate marts. Apache Airflow orchestrates the whole thing as one daily DAG.

On top of the warehouse sits an AI lane: LLM enrichment turns free-text reviews
into structured, queryable columns; RAG lets you chat with your reviews;
text-to-SQL lets you query the warehouse in plain English; and a Streamlit
dashboard serves the marts. Every AI app that *reads* the warehouse does so as a
**read-only role**; the enrichment job is the only one that writes, and the only
one that needs a role which can.

---

## Architecture

[![Interactive GitDiagram](https://img.shields.io/badge/Interactive_Architecture-GitDiagram-2563eb?style=for-the-badge&logo=diagramsdotnet)](https://gitdiagram.com/irajput215/zomato-ai-data-platform)

```mermaid
flowchart TD

subgraph group_data["Data Preparation & Ingestion"]
  node_dimension_generator["Dimension Generator"]
  node_fact_generator["Fact Generator<br/>[generate_facts.py]"]
  node_generator_config["Generator Config<br/>[config.py]"]
  node_s3_uploader["S3 Uploader<br/>[upload_to_s3.py]"]
  node_s3_verifier["S3 Verifier<br/>[verify_s3.py]"]
  node_s3_lake[("AWS S3 Data Lake")]
end

subgraph group_warehouse["Warehouse & Medallion Pipeline"]
  node_snowflake_load["Snowflake RAW Load<br/>[05_copy_into.sql]"]
  node_staging["dbt Staging (Silver)"]
  node_marts["dbt Marts (Gold)"]
  node_snapshot["Restaurant SCD2 Snapshot"]
  node_warehouse_store[("Snowflake Data Warehouse")]
end

subgraph group_orchestration["Orchestration"]
  node_daily_dag["Airflow 3 Batch DAG<br/>[zomato_batch.py]"]
end

subgraph group_ai["AI Analytics & Consumption"]
  node_ai_common["AI Engine Client<br/>[DeepSeek / OpenAI]"]
  node_enrichment["Review Enrichment<br/>[enrich_reviews.py]"]
  node_rag["RAG Review Chat<br/>[rag_chat.py]"]
  node_text_sql["Governed Text-to-SQL<br/>[text_to_sql.py]"]
  node_dashboard["Streamlit Operations Dashboard<br/>[dashboard.py]"]
end

node_dimension_generator -->|"uses settings"| node_generator_config
node_fact_generator -->|"uses settings"| node_generator_config
node_fact_generator -->|"reads dimensions"| node_dimension_generator
node_s3_uploader -->|"uploads CSVs"| node_s3_lake
node_s3_verifier -->|"validates objects"| node_s3_lake
node_s3_lake -->|"COPY INTO"| node_snowflake_load
node_snowflake_load -->|"writes RAW"| node_warehouse_store
node_warehouse_store -->|"cleans sources"| node_staging
node_staging -->|"builds models"| node_marts
node_marts -->|"tracks history"| node_snapshot
node_snapshot -.->|"stores history"| node_warehouse_store
node_daily_dag -->|"runs COPY INTO"| node_snowflake_load
node_daily_dag -->|"runs dbt build"| node_staging
node_daily_dag -->|"runs snapshot"| node_snapshot
node_daily_dag -->|"runs enrichment"| node_enrichment
node_daily_dag -->|"builds AI mart"| node_marts
node_enrichment -->|"uses"| node_ai_common
node_rag -->|"uses"| node_ai_common
node_text_sql -->|"uses"| node_ai_common
node_dashboard -->|"queries marts"| node_warehouse_store
node_enrichment -->|"writes enriched reviews"| node_warehouse_store
node_rag -->|"reads reviews"| node_warehouse_store
node_text_sql -->|"validates & executes SQL"| node_warehouse_store

click node_dimension_generator "https://github.com/irajput215/zomato-ai-data-platform/blob/main/data/generator/generate_dimensions.py"
click node_fact_generator "https://github.com/irajput215/zomato-ai-data-platform/blob/main/data/generator/generate_facts.py"
click node_generator_config "https://github.com/irajput215/zomato-ai-data-platform/blob/main/data/generator/config.py"
click node_s3_uploader "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ingestion/upload_to_s3.py"
click node_s3_verifier "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ingestion/verify_s3.py"
click node_snowflake_load "https://github.com/irajput215/zomato-ai-data-platform/blob/main/snowflake/05_copy_into.sql"
click node_staging "https://github.com/irajput215/zomato-ai-data-platform/tree/main/zomato/models/staging"
click node_marts "https://github.com/irajput215/zomato-ai-data-platform/tree/main/zomato/models/marts"
click node_snapshot "https://github.com/irajput215/zomato-ai-data-platform/blob/main/zomato/snapshots/dim_restaurants_snapshot.sql"
click node_warehouse_store "https://github.com/irajput215/zomato-ai-data-platform/blob/main/snowflake/01_setup.sql"
click node_daily_dag "https://github.com/irajput215/zomato-ai-data-platform/blob/main/airflow/dags/zomato_batch.py"
click node_ai_common "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ai/common.py"
click node_enrichment "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ai/enrich_reviews.py"
click node_rag "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ai/rag_chat.py"
click node_text_sql "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ai/text_to_sql.py"
click node_dashboard "https://github.com/irajput215/zomato-ai-data-platform/blob/main/ai/dashboard.py"
```

> **Interactive Visualization:** Explore the live interactive graph on [GitDiagram](https://gitdiagram.com/irajput215/zomato-ai-data-platform).

<details>
<summary><b>View Graphic Overview Diagram</b></summary>

![Architecture](docs/architecture.png)

</details>

## What gets built

| Layer | Where | What |
|---|---|---|
| **Source** | `data/raw/` | 4 dimension CSVs (restaurants, users, food, menu) + 3 fact files: **10M orders**, **~23M order items**, **300K free-text reviews** |
| **Lake** | Amazon S3 | One bucket, `raw/<table>/` — one prefix per CSV |
| **Bronze** | Snowflake `ZOMATO.RAW` | `COPY INTO` from S3 via a **keyless** storage integration + IAM role |
| **Silver** | Snowflake `ZOMATO.STAGING` | 7 dbt staging views — clean, type and rename every source |
| **Gold** | Snowflake `ZOMATO.MARTS` | 4 dimensions, **incremental** facts (MERGE), 4 business marts, plus an SCD2 snapshot |
| **AI** | Snowflake `ZOMATO.AI` | LLM-enriched reviews (sentiment/topic/key issue), RAG chat, text-to-SQL |
| **Orchestration** | Airflow 3 (Docker) | One daily DAG: load → transform → snapshot → enrich → AI mart → docs |

### Tech stack

Python · Pandas · Amazon S3 · Snowflake · dbt (dbt-snowflake 1.8) · Apache Airflow 3 (Docker) · DeepSeek (`deepseek-chat`) / OpenAI · SentenceTransformers · Streamlit · GitHub Actions CI/CD

---

## Quickstart

Five commands, once the [RUNBOOK](RUNBOOK.md) has walked you through the AWS and
Snowflake setup:

```bash
make install                     # Python dependencies
make data-small                  # tiny dataset — or `make data` for the full 10M rows

make upload                      # CSVs -> s3://<bucket>/raw/
make verify-s3                   # did it all actually arrive?

make pipeline                    # dbt build -> snapshot -> enrich -> dbt build tag:ai
make airflow-up                  # http://localhost:8080  (admin / admin)
```

Then explore:

```bash
make dashboard                   # operations dashboard over the Gold marts
make rag                         # chat with your reviews (RAG)
make text2sql                    # chat with your warehouse (text-to-SQL)
make docs                        # dbt docs: lineage, tests, exposures
make check                       # offline consistency checks (~1 second)
```

`make` on its own lists every target.

> **Only two things are required before `make pipeline` works:** the Snowflake
> objects from `snowflake/01`–`04`, and the S3 bucket plus IAM role from
> `aws/iam/`. [RUNBOOK.md](RUNBOOK.md) covers both, including the two mistakes
> everybody makes on the Snowflake ↔ IAM trust handshake.

---

## Repository structure

```
├── RUNBOOK.md                    # zero-to-running setup, with real error messages
├── Makefile                      # every entry point, discoverable via `make`
│
├── data/
│   ├── generator/                # reproducible dataset: dimensions + 10M facts
│   └── README.md                 # or bring the original CSVs instead
├── ingestion/
│   ├── upload_to_s3.py           # multipart upload, mirrors the lake layout
│   └── verify_s3.py              # both-directions lake/local diff; exits non-zero
│
├── snowflake/                    # run in Snowsight, in order
│   ├── 01_setup.sql              #   warehouse, database, schemas, DBT_ROLE, ZOMATO_AI_RO
│   ├── 02_storage_integration.sql#   keyless S3 link
│   ├── 03_stage_and_formats.sql  #   external stage + CSV file format
│   ├── 04_raw_tables.sql         #   Bronze DDL (column order = the CSV contract)
│   ├── 05_copy_into.sql          #   load, with strict/tolerant error modes
│   └── 06_grants_and_monitoring.sql # cost guard, read-only role, health views
├── aws/iam/                      # the S3 ↔ Snowflake handshake, as JSON
│
├── zomato/                       # the dbt project
│   ├── profiles.yml              #   committed, but 100% env-var driven
│   ├── models/staging/           #   Silver: 7 views + sources + tests
│   ├── models/marts/             #   Gold: dims, incremental facts, marts, exposures
│   ├── snapshots/                #   SCD2 history for dim_restaurants
│   ├── tests/                    #   singular tests for cross-column invariants
│   └── analyses/                 #   ad-hoc SQL that compiles but never materialises
│
├── ai/
│   ├── common.py                 # shared Snowflake + OpenAI clients (password or key-pair)
│   ├── enrich_reviews.py         # LLM as a transformation step
│   ├── rag_chat.py               # chat with your reviews
│   ├── text_to_sql.py            # chat with your warehouse
│   └── dashboard.py              # Streamlit dashboard over the marts
│
├── airflow/                      # Airflow 3 on Docker
│   ├── Dockerfile                #   Snowflake + FAB providers; dbt in its own venv
│   ├── docker-compose.yaml       #   postgres + api-server + scheduler + dag-processor
│   └── dags/zomato_batch.py      #   the 6-task daily DAG
│
├── scripts/check_project.py      # offline consistency checks used by CI
├── docs/architecture.md          # design rationale
└── .github/workflows/ci.yml      # lint, generator smoke test, dbt parse, docker build
```

---

## How the pipeline works

### 1 · Data lands in S3

Seven CSVs are uploaded to `s3://<BUCKET>/raw/<table>/` — one prefix per table. The
local tree under `data/raw/` mirrors the lake exactly, so publishing is a straight
recursive upload. `verify_s3.py` then diffs both directions and exits non-zero on a
missing file, a stale extra object, or a size mismatch.

### 2 · S3 → Snowflake: one keyless handshake

Snowflake reads the bucket with **no stored keys**, using a storage integration plus
an IAM role. The Snowflake side is
[`snowflake/02_storage_integration.sql`](snowflake/02_storage_integration.sql); the
AWS documents live in [`aws/iam/`](aws/iam/):

| File | Used for |
|---|---|
| [`s3-read-policy.json`](aws/iam/s3-read-policy.json) | IAM policy `zomato-s3-read` — read-only, scoped to `<BUCKET>/raw/*` |
| [`snowflake-role-trust-policy-initial.json`](aws/iam/snowflake-role-trust-policy-initial.json) | Placeholder trust, used only so the role can be created |
| [`snowflake-role-trust-policy-final.json`](aws/iam/snowflake-role-trust-policy-final.json) | Final trust — Snowflake's IAM **user** ARN + external ID from `DESC INTEGRATION` |

Order matters: create the policy and role → create the `STORAGE INTEGRATION` with the
role ARN → `DESC INTEGRATION` for `STORAGE_AWS_IAM_USER_ARN` and
`STORAGE_AWS_EXTERNAL_ID` → paste both into the role's trust policy.

Two hard-won lessons, both in the runbook: the trust `Principal` must be Snowflake's
IAM **user** ARN and not `:root`; and never re-run `CREATE OR REPLACE` on an existing
integration, because it regenerates the external ID and breaks the trust you just wired up.

### 3 · Load — `COPY INTO`

Bronze DDL ([`snowflake/04_raw_tables.sql`](snowflake/04_raw_tables.sql)) matches each
CSV's column order, then [`snowflake/05_copy_into.sql`](snowflake/05_copy_into.sql)
pulls each file from the stage. Loads are **strict** for the generated facts
(`ABORT_STATEMENT` — a parse error there means the generator is broken) and
**tolerant** for the messy dimensions (`CONTINUE` — a malformed restaurant rating is
just Tuesday, and `VALIDATE()` shows you what was skipped).

Re-running is free: Snowflake remembers which files it has already loaded.

### 4 · Transform — dbt (medallion)

- **Staging (Silver)** — one view per source, and the *only* place that knows the
  source is dirty: `'--'` → null, `'₹ 200'` → `200`, `'Koramangala, Bangalore'` →
  `'Bangalore'`, `'M'` → `'Male'`. The city normalisation is a shared `clean_city()`
  macro, because `stg_restaurants.city` and `stg_orders.city` must match
  character-for-character or the city marts silently split one city in two.
- **Dimensions (Gold)** — `dim_restaurants` (deduped), `dim_customer` (age segments),
  `dim_food`, and a generated `dim_date` calendar built with Snowflake's `GENERATOR`.
- **Facts (Gold, incremental)** — `fct_orders` (10M) and `fct_order_items` (~23M) use
  `materialized='incremental'` with a MERGE strategy, so a re-run processes only new
  rows instead of rebuilding 33M.
- **Marts (Gold)** — `mart_daily_city_revenue` (GMV/AOV/cancel rate),
  `mart_delivery_sla` (p50/p90/late rate by city and hour),
  `mart_restaurant_performance`, `mart_review_insights`.
- **SCD2** — `snapshots/dim_restaurants_snapshot.sql` keeps the history an incremental
  model cannot: what a restaurant's rating was *at the time*.
- **Tests** — ~60 generic tests (`unique`, `not_null`, `relationships`,
  `accepted_values`) plus 7 singular tests, including the headline
  `assert_order_items_reconcile_to_orders`: every order's stored totals must agree
  with the line items actually sold.

### 5 · Orchestrate — Airflow

One daily DAG, [`zomato_batch`](airflow/dags/zomato_batch.py):

```
reload_raw → dbt_build_core → dbt_snapshot → enrich_reviews → dbt_build_ai → dbt_docs_generate
(COPY INTO)   (dbt build        (SCD2)         (OpenAI)         (dbt build        (docs site)
               --exclude tag:ai)                                 --select tag:ai)
               --exclude snapshot
```

The split is not cosmetic. `mart_review_insights` reads a table that does not exist
until the AI job has run, so `dbt build --exclude tag:ai` has to come first — and the
tests on that model are tagged `ai` so they are skipped too. Without that tag the very
first pipeline run fails, not on a data problem, but because dbt tries to test a table
that has not been created yet.

Credentials never touch the code: docker-compose injects `SNOWFLAKE_*` (read by dbt's
`profiles.yml` via `env_var()`) and an `AIRFLOW_CONN_SNOWFLAKE_DEFAULT` connection.

### 6 · AI layer — four capabilities

1. **LLM enrichment** ([`ai/enrich_reviews.py`](ai/enrich_reviews.py)) — *LLM as a
   transformation step.* Reads review text, uses DeepSeek (`deepseek-chat`) or OpenAI for structured JSON
   (sentiment, score, topic, key issue), validates it against the allowed label sets,
   and writes it to `ZOMATO.AI.REVIEW_ENRICHED` — which dbt then models into
   `mart_review_insights` like any other table. Idempotent (only un-enriched reviews are
   fetched), sample-capped (`SAMPLE_N`), concurrent, and retried with backoff.
2. **RAG** ([`ai/rag_chat.py`](ai/rag_chat.py)) — *chat with your reviews.* Embeds
   reviews using local SentenceTransformers (`all-MiniLM-L6-v2`) or API embeddings, retrieves the nearest neighbours for a question with fast matrix operations, and
   answers grounded only in those reviews, showing source citations.
3. **Text-to-SQL** ([`ai/text_to_sql.py`](ai/text_to_sql.py)) — *chat with your
   warehouse.* The model is given the marts' schema introspected live from
   `INFORMATION_SCHEMA`, writes Snowflake SQL, and a guard (comments stripped, single
   statement, `SELECT`/`WITH` only, no DDL/DML keywords, enforced row cap) validates it
   before it runs as the **read-only** `ZOMATO_AI_RO` role.
4. **Dashboard** ([`ai/dashboard.py`](ai/dashboard.py)) — the fixed BI layer: GMV trend,
   SLA heatmap, restaurant leaderboard, LLM review insights.

---

## Key Production-Grade Engineering Highlights

**The AI output is a testable table, not a chat log.** Because enrichment writes to
`ZOMATO.AI.REVIEW_ENRICHED` and dbt declares it as a source, the LLM's output is
covered by `accepted_values` tests, is joinable, is versioned, and can be re-modelled
without re-calling the API. A hallucinated topic fails the build instead of quietly
reaching a dashboard.

**Text-to-SQL is defended twice.** The generated-SQL guard is the *second* line of
defence; the first is a database role that only holds `SELECT`. A prompt injection
that defeats the regex still hits a wall in Snowflake.

**Dimension keys warn, dimension models error.** Raw exports can legitimately repeat a
`restaurant_id`, so uniqueness at staging is `severity: warn`. The dedupe happens in
`dim_restaurants`, and *that* uniqueness is an error. The strictness is placed where
the guarantee is actually made.

**The project is dependency-free.** There is no `packages.yml` and no `dbt deps` step:
the calendar uses Snowflake's `GENERATOR`, and custom cross-column invariants are
written in [`zomato/tests/`](zomato/tests). One less thing to break on a fresh
clone, and zero version conflicts in the Airflow image.

**CI runs without any cloud credentials.** `dbt parse` validates the whole project
offline; the generator produces a small dataset; `scripts/check_project.py` then
verifies that every YAML and JSON file parses, that every `ref()` and `source()`
resolves, that every declared source is really created by the SQL or Python that is
supposed to create it, and that each CSV's header row matches its `RAW` table's column
order. That check catches generator/DDL drift before `COPY INTO` runs.

---

## Cost Optimization & Resource Controls

Built-in cost safeguards ensure high performance without runaway cloud spend:

| Item | Cost Profile |
|---|---|
| **S3 Storage** | ~2.3 GB ≈ **$0.05/month** |
| **Snowflake Warehouse** | XSMALL, auto-suspends after 60s + 50-credit resource monitor |
| **DeepSeek Enrichment** | Near-zero inference cost via `deepseek-chat`; `SAMPLE_N=25` for dev smoke testing |
| **Local RAG Embeddings** | Free in-memory CPU embeddings via `all-MiniLM-L6-v2` (`sentence-transformers`) |
| **Airflow Orchestration** | Local Docker Compose stack, zero infrastructure cost |

The cost controls are baked directly into the repo: the warehouse auto-suspends after
60s, a resource monitor suspends it at 50 credits, a 1-hour statement timeout stops a
runaway query, `SAMPLE_N` caps enrichment spend per run, and the text-to-SQL app wraps
unbounded queries in an outer `LIMIT`.

---

## Documentation

| Document | Contents |
|---|---|
| [HOW_TO_RUN.md](HOW_TO_RUN.md) | Developer quickstart and execution commands |
| [RUNBOOK.md](RUNBOOK.md) | Zero-to-running setup and a troubleshooting table of real error messages |
| [docs/architecture.md](docs/architecture.md) | Why each layer exists, and the failure behaviour of every stage |
| [zomato/README.md](zomato/README.md) | The dbt project: conventions, model reference, two-phase build |
| [ingestion/README.md](ingestion/README.md) | Upload and verification, and why `upload_file` not `put_object` |
| [data/generator/README.md](data/generator/README.md) | Generating the dataset, or bringing your own |
