# =============================================================================
# Zomato AI Data Engineering — convenience targets
# =============================================================================
# Every target that talks to dbt passes --profiles-dir so the committed
# zomato/profiles.yml is used and no credentials are hard-coded anywhere.
#
#   make            # list every target
#   make data-small # tiny dataset for a fast end-to-end smoke test
#   make pipeline   # the same chain the Airflow DAG runs
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/bash

DBT_DIR   := zomato
DBT       := dbt
DBT_FLAGS := --project-dir $(DBT_DIR) --profiles-dir $(DBT_DIR)

.PHONY: help install data data-small upload upload-dry-run verify-s3 \
        dbt-debug build snapshot build-ai enrich pipeline docs \
        dashboard rag text2sql airflow-up airflow-down airflow-logs \
        check clean

help:  ## List every target
	@echo "Zomato AI Data Engineering"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
install:  ## Install the Python dependencies for the AI layer and ingestion
	python3 -m pip install -r ai/requirements.txt -r ingestion/requirements.txt

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
data:  ## Generate the full dataset (10M orders, ~23M items, 300K reviews)
	python3 data/generator/generate_dimensions.py
	python3 data/generator/generate_facts.py

data-small:  ## Generate a tiny dataset for a fast smoke test
	python3 data/generator/generate_dimensions.py --small
	python3 data/generator/generate_facts.py --small

upload:  ## Upload data/raw to S3
	python3 ingestion/upload_to_s3.py

upload-dry-run:  ## Show which files would be uploaded, touching nothing
	python3 ingestion/upload_to_s3.py --dry-run

verify-s3:  ## Check that the S3 lake matches data/raw exactly
	python3 ingestion/verify_s3.py

# ---------------------------------------------------------------------------
# Snowflake objects — these are SQL scripts, run them in Snowsight in order
# ---------------------------------------------------------------------------
snowflake:  ## Print the Snowflake setup order
	@echo "Run these in a Snowsight worksheet, in order, as ACCOUNTADMIN:"
	@echo "  snowflake/01_setup.sql                 warehouse, database, schemas, roles"
	@echo "  (AWS: create the IAM policy and role — see aws/iam/ and RUNBOOK.md)"
	@echo "  snowflake/02_storage_integration.sql   keyless S3 link"
	@echo "  (AWS: paste STORAGE_AWS_IAM_USER_ARN + EXTERNAL_ID into the trust policy)"
	@echo "  snowflake/03_stage_and_formats.sql     stage + CSV file format"
	@echo "  snowflake/04_raw_tables.sql            Bronze DDL"
	@echo "  snowflake/05_copy_into.sql             load from S3"
	@echo "  snowflake/06_grants_and_monitoring.sql read-only role, cost guard, health views"

# ---------------------------------------------------------------------------
# dbt
# ---------------------------------------------------------------------------
dbt-debug:  ## Check the dbt <-> Snowflake connection
	$(DBT) debug $(DBT_FLAGS)

build:  ## Silver + Gold, excluding the AI mart and the snapshot
	$(DBT) build --exclude tag:ai --exclude resource_type:snapshot $(DBT_FLAGS)

snapshot:  ## Run the SCD2 snapshot (the core build excludes it, so this owns it)
	$(DBT) snapshot $(DBT_FLAGS)

build-ai:  ## Build the AI-tagged mart; requires enrichment to have run
	$(DBT) build --select tag:ai $(DBT_FLAGS)

docs:  ## Generate and serve the dbt documentation site
	$(DBT) docs generate $(DBT_FLAGS)
	$(DBT) docs serve $(DBT_FLAGS)

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
enrich:  ## LLM-enrich a sample of reviews (SAMPLE_N, default 5)
	python3 ai/enrich_reviews.py

dashboard:  ## Streamlit operations dashboard
	streamlit run ai/dashboard.py

rag:  ## Streamlit RAG app — chat with your reviews
	streamlit run ai/rag_chat.py

text2sql:  ## Streamlit text-to-SQL app — chat with your warehouse
	streamlit run ai/text_to_sql.py

# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
pipeline:  ## The exact chain the zomato_batch Airflow DAG runs
	$(DBT) build --exclude tag:ai --exclude resource_type:snapshot $(DBT_FLAGS)
	$(DBT) snapshot $(DBT_FLAGS)
	python3 ai/enrich_reviews.py
	$(DBT) build --select tag:ai $(DBT_FLAGS)

# ---------------------------------------------------------------------------
# Airflow
# ---------------------------------------------------------------------------
airflow-up:  ## Build and start Airflow (UI on http://localhost:8080)
	cd airflow && docker compose up -d --build

airflow-down:  ## Stop Airflow
	cd airflow && docker compose down

airflow-logs:  ## Tail the Airflow logs
	cd airflow && docker compose logs -f --tail=100

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
check:  ## Offline checks: Python syntax, YAML/JSON, dbt refs, Airflow DAG
	python3 -m compileall -q ai data/generator ingestion scripts && echo "python: ok"
	python3 scripts/check_project.py
	python3 scripts/check_dag.py

clean:  ## Remove build artifacts and cached embeddings
	rm -rf zomato/target zomato/logs zomato/dbt_packages
	rm -rf ai/__pycache__ data/generator/__pycache__ ingestion/__pycache__
	rm -f ai/review_embeddings_*.parquet
