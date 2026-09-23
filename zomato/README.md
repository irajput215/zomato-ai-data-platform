# Zomato — dbt project

The transform half of the pipeline. Reads Snowflake `ZOMATO.RAW` (Bronze, loaded
from S3) and `ZOMATO.AI` (LLM output), and builds Silver and Gold.

```
RAW ──▶ staging (Silver, views) ──▶ marts (Gold, tables)
            7 stg_ models            4 dims
                                     2 incremental facts
                                     4 business marts
AI.REVIEW_ENRICHED ──▶ mart_review_insights   (tag: ai)
```

## Layout

```
models/staging/     Silver. One view per RAW source. All cleaning lives here.
models/marts/       Gold. Dimensions, incremental facts, business marts.
snapshots/          SCD2 history for dim_restaurants.
tests/              Singular tests for invariants no generic test can express.
analyses/           Ad-hoc SQL that dbt compiles but never materialises.
macros/             clean_city() and the schema-naming override.
```

## Running it

Always pass `--profiles-dir .` — `profiles.yml` is committed here and reads every
credential from the environment.

```bash
export SNOWFLAKE_ACCOUNT=... SNOWFLAKE_USER=... SNOWFLAKE_PASSWORD=...

dbt debug   --profiles-dir .                      # connection check
dbt build   --exclude tag:ai --profiles-dir .     # Silver + Gold (phase 1)
dbt snapshot              --profiles-dir .        # SCD2
dbt build   --select tag:ai --profiles-dir .      # after enrichment (phase 2)
dbt docs generate && dbt docs serve --profiles-dir .
```

There is **no `packages.yml`** and therefore no `dbt deps` step: the calendar is
built with Snowflake's `GENERATOR`, and the one "unique combination of columns"
check that would normally come from `dbt_utils` is written by hand in
`tests/assert_mart_grains_are_unique.sql`. One less thing to break on a fresh
clone.

## dbt version

The project targets **dbt 1.8** (`dbt-core==1.8.*`, `dbt-snowflake==1.8.*`) —
what `airflow/Dockerfile` pins, what CI parses against, and what has been used to
validate this project offline. `profiles.yml` supports three targets
(`dev`, `prod`, `dev_keypair`); pick one with `DBT_TARGET`.

Two things here are 1.8-era syntax and will emit deprecation warnings on
dbt 1.10+:

| In this project (1.8) | On dbt 1.10+ |
|---|---|
| `invalidate_hard_deletes: True` in the snapshot | `hard_deletes: invalidate` |
| generic-test arguments as `- unique: {config: {...}}` | an `arguments:` block per test |

1.8 was a deliberate choice: it is the version the original reference project
used, it installs cleanly on the Python 3.12 in the Airflow image, and it parses
this project with **no deprecation warnings at all** (that is why the YAML uses
`data_tests:` rather than the older `tests:` key, which 1.8 warns about). If you
move to a newer dbt, make those two changes and bump the pin in
`airflow/Dockerfile` and in `.github/workflows/ci.yml`.

## The two-phase build, and why it exists

`dbt build --exclude tag:ai` deliberately skips `mart_review_insights`, because
the table it reads (`ZOMATO.AI.REVIEW_ENRICHED`) does not exist until
`ai/enrich_reviews.py` has run at least once.

The tests on it are tagged `ai` explicitly so that they are skipped in phase 1
too. Without that tag the very first pipeline run fails — not on a data problem,
but because dbt tries to test a table that has not been created yet.

## Conventions

- **Staging does all the cleaning.** No mart ever parses a string, casts a
  currency symbol, or knows that `--` means null.
- **`clean_city()` is a macro, not copy-paste.** `stg_restaurants` and
  `stg_orders` must produce character-identical city values, or the city-level
  marts silently split one city into two groups.
- **Facts are incremental with `merge`.** Only rows past the watermark are
  processed. The generator writes `order_timestamp` monotonically with
  `order_id`, so a `> max()` watermark cannot skip rows.
- **Uniqueness of raw dimension keys warns; uniqueness of dimension keys
  errors.** Raw exports can repeat a restaurant id — `dim_restaurants` dedupes
  it, and *that* is the guarantee worth failing a build over.
- **Tunables are vars, not literals.** `delivery_sla_minutes`,
  `date_spine_start`, `date_spine_end`:

  ```bash
  dbt build --vars '{delivery_sla_minutes: 60}' --profiles-dir .
  ```

## Model reference

| Layer | Model | Materialisation | Notes |
|---|---|---|---|
| Staging | `stg_restaurants` | view | Parses `--` ratings, `₹ 200` costs, `Area, City` |
| Staging | `stg_users` | view | Lowercases email, normalises `M`/`male` → `Male` |
| Staging | `stg_food` | view | Normalises the veg flag |
| Staging | `stg_menu` | view | Drops unparseable and zero prices |
| Staging | `stg_orders` | view | Renames + derives `is_delivered` |
| Staging | `stg_order_items` | view | Types ~23M rows |
| Staging | `stg_reviews` | view | Joins in the restaurant's city |
| Marts | `dim_restaurants` | table | Deduped; SCD2 snapshot alongside |
| Marts | `dim_customer` | table | Age segmentation |
| Marts | `dim_food` | table | Dish catalogue |
| Marts | `dim_date` | table | Generated calendar |
| Marts | `fct_orders` | **incremental** | MERGE on `order_id`, 10M rows |
| Marts | `fct_order_items` | **incremental** | MERGE on `order_item_id`, ~23M rows |
| Marts | `mart_daily_city_revenue` | table | GMV, AOV, cancel rate |
| Marts | `mart_delivery_sla` | table | p50/p90, late rate per city/hour |
| Marts | `mart_restaurant_performance` | table | Restaurant leaderboard |
| Marts | `mart_review_insights` | table | `tag: ai`. LLM sentiment by city |
