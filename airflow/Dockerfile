# =============================================================================
# Airflow 3.x image for the Zomato batch pipeline
# =============================================================================
# Bump the tag to the newest 3.x if you like (3.0.4, 3.1.x, ...). The DAG uses
# the Airflow 3 import paths, so do not drop back to 2.x.
#
# Airflow 3 renamed things you may remember from 2.x:
#   webserver    -> api-server
#   (new)           dag-processor        — DAG parsing is its own component
#   airflow.providers.standard.operators.bash.BashOperator
#                                       — core operators moved to the standard provider
# =============================================================================
FROM apache/airflow:3.0.3

# Providers:
#   snowflake  — SQLExecuteQueryOperator runs the COPY INTO statements
#   fab        — the classic username/password login (admin/admin) still works
RUN pip install --no-cache-dir \
      apache-airflow-providers-snowflake \
      apache-airflow-providers-fab

# dbt lives in its OWN virtualenv.
#
# This is not optional tidiness: dbt and Airflow pin different, incompatible
# versions of common libraries (Jinja2, click, protobuf), and installing dbt
# into Airflow's environment is the classic way to end up with a scheduler that
# will not start. The DAG calls /opt/airflow/dbt_venv/bin/dbt explicitly.
#
# BOTH packages are pinned. Pinning only dbt-snowflake does NOT pin dbt-core:
# pip will happily resolve dbt-core to the newest release, and a 1.12 core with
# a 1.8 adapter is a mismatched pair that fails in confusing ways. Pinning both
# keeps the two in lockstep.
RUN python -m venv /opt/airflow/dbt_venv && \
    /opt/airflow/dbt_venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/airflow/dbt_venv/bin/pip install --no-cache-dir \
      "dbt-core==1.8.*" \
      "dbt-snowflake==1.8.*"

# The AI enrichment task needs the OpenAI SDK and the Snowflake Python driver.
# Unlike dbt, these coexist happily with Airflow's own dependencies.
RUN pip install --no-cache-dir \
      "openai>=1.30,<2" \
      "python-dotenv>=1.0"
