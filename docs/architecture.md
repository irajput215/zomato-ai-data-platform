# Architecture

## The pipeline

![Architecture](architecture.png)

```
7 CSVs ──▶ Amazon S3 ──▶ Snowflake ────────────────────────────▶ AI applications
           raw/<table>/   RAW → STAGING → MARTS → AI            enrichment · RAG · text-to-SQL
                                    ▲
                          Apache Airflow 3 (@daily)
              reload_raw → dbt_build_core → dbt_snapshot
              → enrich_reviews → dbt_build_ai → dbt_docs_generate
```

## Why each layer exists

### Source — `data/raw/<table>/<table>.csv`

Seven files: four messy "real world" dimension exports (restaurants, users,
food, menu) and three generated fact files (10M orders, ~23M order items, 300K
free-text reviews).

The directory tree mirrors the S3 layout exactly, so publishing is a straight
recursive upload with no renaming rules to remember.

### Lake — `s3://<bucket>/raw/<table>/`

One prefix per table. Nothing is transformed on the way in — the lake is the
system of record for "what we received", warts included. That is what makes the
Bronze layer replayable: if a staging model turns out to be wrong, you re-run
dbt, you do not re-request the data.

### Bronze — `ZOMATO.RAW`

`COPY INTO` loads each CSV positionally, header skipped, so the table DDL's
column order *is* the contract with the producer. Everything is `STRING` except
the generated fact files.

Loads are strict for the facts (`ON_ERROR = 'ABORT_STATEMENT'`) and tolerant for
the dimensions (`'CONTINUE'`), because a malformed generated row means the
generator is broken, whereas a malformed restaurant rating is just Tuesday.

### Silver — `ZOMATO.STAGING`

One view per source, and the only place in the project that knows the source
data is dirty. `'--'` becomes null, `'₹ 200'` becomes `200`,
`'Koramangala, Bangalore'` becomes `'Bangalore'`, `'M'` becomes `'Male'`.

Views, not tables: they cost nothing to store and always reflect Bronze, so a
Bronze reload is visible immediately.

The city normalisation lives in a shared `clean_city()` macro rather than being
copy-pasted, because `stg_restaurants.city` and `stg_orders.city` must match
character-for-character or the city-level marts silently split one city in two.

### Gold — `ZOMATO.MARTS`

* **Dimensions** — `dim_restaurants`, `dim_customer`, `dim_food`, `dim_date`
  (a generated calendar, built with Snowflake's `GENERATOR` so the project needs
  no dbt packages).
* **Facts, incremental** — `fct_orders` (MERGE on `order_id`) and
  `fct_order_items` (MERGE on `order_item_id`). Only rows past the watermark are
  processed. The generator writes `order_timestamp` monotonically with
  `order_id`, so a `> max()` watermark cannot skip rows.
* **Business marts** — one table per question: `mart_daily_city_revenue`
  (GMV/AOV/cancel rate), `mart_delivery_sla` (p50/p90/late rate by city and
  hour), `mart_restaurant_performance`, `mart_review_insights`.
* **SCD2** — `snapshots/dim_restaurants_snapshot.sql` keeps the history that an
  incremental model cannot: what a restaurant's rating was *at the time*.

### AI — `ZOMATO.AI` and the apps

The architectural idea worth taking away: **the LLM is a transformation step,
not a separate system.** `ai/enrich_reviews.py` reads `RAW.REVIEWS`, asks the
model for structured JSON, and writes it to `ZOMATO.AI.REVIEW_ENRICHED`. dbt then
declares that table as a `source` and models it like anything else.

The consequences are concrete:

* the LLM's output is **testable** (`accepted_values` on topic and sentiment)
* it is **idempotent** — only un-enriched reviews are processed, so a retry never
  pays twice
* it is **replayable** — re-running dbt rebuilds downstream marts without
  re-calling the API
* it is **budgeted** — `SAMPLE_N` caps the spend per run

Three apps sit on top:

| App | Pattern | Reads |
|---|---|---|
| `ai/enrich_reviews.py` | LLM as transformation | `RAW.REVIEWS` → `AI.REVIEW_ENRICHED` |
| `ai/rag_chat.py` | retrieval-augmented generation | `STAGING.STG_REVIEWS` |
| `ai/text_to_sql.py` | natural language → SQL | `MARTS.*` as a read-only role |
| `ai/dashboard.py` | fixed BI | `MARTS.*` |

## Two design decisions worth defending

**Text-to-SQL runs as a read-only role.** `ZOMATO_AI_RO` holds `SELECT` and
nothing else (granted in `snowflake/01_setup.sql`). The generated-SQL guard in
the app is the second line of defence, not the only one — a prompt injection that
defeats the regex still hits a wall in the database.

**The build is split in two phases.** `dbt build --exclude tag:ai` must run
before enrichment, because `mart_review_insights` reads a table that does not
exist on a fresh warehouse. The tests on it are tagged `ai` for the same reason:
without the tag the very first pipeline run fails, not on a data problem, but
because dbt tries to test a table that has not been created yet.

## Failure behaviour

| Stage fails | Effect | Recovery |
|---|---|---|
| S3 upload | nothing downstream runs | re-run the upload; `verify_s3.py` shows the gap |
| `COPY INTO` | RAW stale | re-run; Snowflake skips already-loaded files |
| `dbt build` core | marts stale, tests block bad data | fix the model, re-run — incremental facts only process new rows |
| `enrich_reviews` | AI mart stale | un-enriched reviews stay pending; the next run picks them up |
| `dbt build` AI | only the AI mart stale | safe to re-run on its own |

Nothing in the pipeline is destructive and every stage is independently
re-runnable, which is what makes a daily `@daily` schedule with `retries: 1`
sufficient rather than optimistic.
