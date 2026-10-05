# How to Run — Zomato AI Data Platform

A step-by-step developer guide to configure, run, and explore the **Zomato AI Data Engineering** platform locally.

---

## 1. Quick Prerequisites

- **Python 3.9+** (recommend using a virtual environment: `python3 -m venv .venv && source .venv/bin/activate`)
- **Docker & Docker Compose** (for running Airflow)
- **Snowflake Account** (with `ACCOUNTADMIN` or setup role privileges)
- **AWS Account** (S3 bucket for data lake and IAM role for keyless integration)
- **OpenAI API Key** (for review enrichment, RAG, and Text-to-SQL features)

---

## 2. Environment Configuration

1. Copy the sample environment file:
   ```bash
   cp .env.example .env
   ```

2. Fill in the required variables in `.env`:
   - **Snowflake**: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD` (or key-pair auth variables)
   - **AWS**: `AWS_REGION`, `S3_BUCKET` (ensure AWS CLI or local AWS profile is configured)
   - **OpenAI**: `OPENAI_API_KEY`

---

## 3. Install Dependencies

Install the Python libraries required for data generation, ingestion, dbt, and AI apps:

```bash
make install
# Or manually:
pip install -r ai/requirements.txt -r ingestion/requirements.txt -r requirements-dev.txt
```

---

## 4. Initial Cloud & Warehouse Setup

Before running the data pipelines, ensure Snowflake and AWS S3 are configured:

1. **Snowflake Setup**:
   Execute the setup SQL scripts in Snowsight in order:
   - `snowflake/01_setup.sql`: Database (`ZOMATO`), schemas, warehouses, and roles (`DBT_ROLE`, `ZOMATO_AI_RO`).
   - `snowflake/02_storage_integration.sql`: S3 keyless integration (requires IAM trust setup; see [RUNBOOK.md](RUNBOOK.md)).
   - `snowflake/03_stage_and_formats.sql`: External stage & CSV formats.
   - `snowflake/04_raw_tables.sql`: Bronze/RAW table definitions.

2. **AWS S3 Bucket & IAM**:
   - Create your S3 bucket (matches `S3_BUCKET` in `.env`).
   - Configure IAM role and trust relationship with Snowflake as documented in [RUNBOOK.md](RUNBOOK.md).

---

## 5. End-to-End Pipeline Execution

### Step A: Generate Data
Generate either a lightweight sample dataset (recommended for fast smoke testing) or the full 10M rows:

```bash
# Smoke test dataset (fast)
make data-small

# OR full dataset (~10M orders, 23M order items, 300K reviews)
make data
```

### Step B: Upload & Ingest into S3
Upload the generated raw CSVs to your S3 bucket:

```bash
# Check files that will be uploaded
make upload-dry-run

# Upload to S3
make upload

# Verify lake matches local raw data
make verify-s3
```

### Step C: Load to Snowflake & Transform (dbt + AI)
Run the full transformation chain:
1. Load RAW tables into Snowflake (via Snowsight: `snowflake/05_copy_into.sql` or via Airflow).
2. Run dbt models (Silver staging + Gold marts):
   ```bash
   make pipeline
   ```
   *What `make pipeline` runs:*
   - `dbt build --exclude tag:ai --exclude resource_type:snapshot` (Staging & core marts)
   - `dbt snapshot` (SCD Type 2 dimensional history)
   - `python3 ai/enrich_reviews.py` (LLM review enrichment using OpenAI)
   - `dbt build --select tag:ai` (Enriched AI marts)

---

## 6. Running Airflow (Orchestration)

To run the orchestration layer using Docker:

```bash
# Start Airflow webserver and scheduler in background
make airflow-up

# Check logs
make airflow-logs

# Stop Airflow
make airflow-down
```
- **Airflow Web UI**: [http://localhost:8080](http://localhost:8080)
- **Default Credentials**: `admin` / `admin`
- Unpause and trigger the `zomato_batch` DAG to run the full workflow automated.

---

## 7. Launching AI & Analytics Applications

Interactive Streamlit applications running on top of Snowflake:

### Operations Dashboard
Visualizes key operational metrics, sales trends, and restaurant performance:
```bash
make dashboard
```

### RAG Review Intelligence
Interactive conversational search over customer reviews using vector embeddings:
```bash
make rag
```

### Text-to-SQL Warehouse Assistant
Query the Snowflake warehouse using natural language:
```bash
make text2sql
```

---

## 8. Development & Verification Commands

```bash
# Run offline code, DAG, and dbt integrity checks
make check

# Test dbt Snowflake connection
make dbt-debug

# Generate and serve dbt interactive documentation & lineage graph
make docs

# Clean build artifacts and cached embeddings
make clean
```

For detailed architectural decisions and troubleshooting guide, refer to [README.md](README.md) and [RUNBOOK.md](RUNBOOK.md).
