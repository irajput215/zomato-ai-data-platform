# `data/` — the Zomato data lake mirror

This folder is a local mirror of the S3 data lake (`s3://<bucket>/raw/`). The
Snowflake `COPY INTO` statements expect **one CSV per table**, in the exact
folder layout below, with the exact column order documented in
[`generator/README.md`](generator/README.md).

```
data/
├── .gitignore
├── README.md
├── generator/                     # the synthetic data generator (stdlib only)
└── raw/                           # <- generated/downloaded data (git-ignored)
    ├── restaurants/restaurants.csv
    ├── users/users.csv
    ├── food/food.csv
    ├── menu/menu.csv
    ├── orders/orders.csv
    ├── order_items/order_items.csv
    └── reviews/reviews.csv
```

There are **two ways** to populate `data/raw/`. You can mix them: use the real
dimensions from Google Drive (way 2) and generate the facts (way 1).

---

## Way 1 — run the generator (self-contained, reproducible)

The generator lives in [`generator/`](generator/README.md). It needs **no
third-party packages** — Python 3.9+ and the standard library only.

From the project root (`zomato-ai-data-engineering/`):

```bash
# Fast smoke test (~1 second) into a throwaway folder
python3 data/generator/generate_dimensions.py --small --out-dir /tmp/zgen
python3 data/generator/generate_facts.py      --small --out-dir /tmp/zgen

# Full dataset into data/raw (the default --out-dir)
python3 data/generator/generate_dimensions.py
python3 data/generator/generate_facts.py
```

The full run writes, under `data/raw/`:

| Table | Rows | Notes |
|---|---|---|
| `restaurants` | 148,541 | messy: `--`, `NEW`, `₹ 200 for two`, `"Koramangala, Bangalore"` |
| `users` | 200,000 | messy: mixed-case email/gender, `NA` ages, `No Income` |
| `food` | 8,000 | ~0.5% short rows (missing trailing field) |
| `menu` | 891,246 | 6 menu rows per restaurant |
| `orders` | 10,000,000 | generated facts |
| `order_items` | ~23,000,000 | ~2.3 line items per order |
| `reviews` | 300,000 | Delivered orders only, free-text comments |

Every size is overridable and the output is deterministic for a given
`--seed`. Run either script with `--help` for the full CLI.

```bash
# examples
python3 data/generator/generate_dimensions.py --restaurants 20000 --users 50000 --food 3000 --seed 7
python3 data/generator/generate_facts.py --orders 100000 --reviews 5000 \
    --start-date 2025-01-01 --end-date 2025-06-30 --seed 7

# fastest end-to-end check
python3 data/generator/generate_dimensions.py --small --out-dir /tmp/zgen
python3 data/generator/generate_facts.py      --small --out-dir /tmp/zgen
```

Then upload to S3 (one folder per table):

```bash
aws s3 cp data/raw/restaurants/restaurants.csv s3://<bucket>/raw/restaurants/
# ... and so on for the other six tables
```

---

## Way 2 — download the original real Zomato dimension CSVs

Only the four **dimension** files exist in the real dataset; the three **fact**
files (`orders`, `order_items`, `reviews`) must be produced by the generator.

1. Open the project's Google Drive folder:

   **<https://drive.google.com/drive/folders/1FEnGWMHhHzzTUCZOw1-YnH2v3DMuM-rs?usp=sharing>**

2. Download the dimension CSVs:
   `restaurants.csv`, `users.csv`, `food.csv`, `menu.csv`.

3. Drop each one into its table folder using the exact path
   `data/raw/<table>/<table>.csv`:

   ```text
   data/raw/restaurants/restaurants.csv
   data/raw/users/users.csv
   data/raw/food/food.csv
   data/raw/menu/menu.csv
   ```

   The file name must stay `<table>.csv` (the S3 stage is scanned per folder and
   the dbt sources point at `RAW.<table>`).

4. Generate the facts against those same dimensions (the generator reads them
   from `--out-dir`, so it picks up the real dimensions automatically):

   ```bash
   python3 data/generator/generate_facts.py --out-dir data/raw
   ```

   `generate_facts.py` fails with a clear error if any of
   `restaurants.csv`, `users.csv`, `food.csv` is missing, so run step 3 first.

### Expected layout

```
data/raw/<table>/<table>.csv          # exactly one CSV per table folder
```

Anything else in `data/raw/` is ignored by the generator. The `raw/` tree,
`*.csv` and `*.parquet` are git-ignored (see [`.gitignore`](.gitignore)) — the
full dataset is too large to commit.

---

## Loading into Snowflake

After `data/raw/` is populated (either way), upload to `s3://<bucket>/raw/` and
run the SQL in order:

```bash
# in Snowsight
snowflake/03_stage_and_formats.sql   # external stage + CSV file format
snowflake/04_raw_tables.sql          # RAW table DDL (column order = CSV order)
snowflake/05_copy_into.sql           # COPY INTO RAW... (skips the header row)
```

Key facts the CSVs are built around:

- A header row is always present; Snowflake skips it with `SKIP_HEADER = 1`.
- The four dimension files have a **leading unnamed index column**, so their
  header line starts with a comma and `RAW.<dim>` starts with a throwaway `_idx`.
- Fields containing commas (e.g. `"Koramangala, Bangalore"`, review comments,
  the restaurant `menu` text) are quoted — `FIELD_OPTIONALLY_ENCLOSED_BY = '"'`.
- Empty fields become NULL (`EMPTY_FIELD_AS_NULL = TRUE`,
  `NULL_IF = ('', '\N', 'NULL')`), e.g. `customer_rating` for cancelled orders.
- `food.csv` contains a few short rows, which is why the file format uses
  `ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE`.
- Files use `\n` line endings only (no `\r`), matching Snowflake's default
  `RECORD_DELIMITER`.

See [`generator/README.md`](generator/README.md) for the full column contract
and the exact messy-value rules the dbt staging models clean up.
