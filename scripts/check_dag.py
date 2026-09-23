#!/usr/bin/env python3
"""
Verify the Airflow DAG's structure without installing Airflow.

The `zomato_batch` DAG is the one piece of this project that cannot be checked
by `dbt parse` or by reading CSVs, and it is also the piece most likely to drift
out of sync with the docs. This script imports the real DAG file against a tiny
stub of the Airflow API and asserts:

  * every documented task exists,
  * the task chain is exactly the one in README.md and RUNBOOK.md,
  * the DAG's schedule, catch-up and concurrency settings are what we claim,
  * the COPY INTO list covers every raw table, and
  * the enrichment task points at a script that actually exists.

Run it with:

    python3 scripts/check_dag.py
    make check
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DAG_FILE = ROOT / "airflow" / "dags" / "zomato_batch.py"

# The chain documented in README.md, RUNBOOK.md and docs/architecture.png.
EXPECTED_CHAIN = [
    "reload_raw",
    "dbt_build_core",
    "dbt_snapshot",
    "enrich_reviews",
    "dbt_build_ai",
    "dbt_docs_generate",
]

RAW_TABLES = [
    "restaurants", "users", "food", "menu", "orders", "order_items", "reviews",
]

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)
    print(f"  \033[31mFAIL\033[0m  {message}")


def ok(message: str) -> None:
    print(f"  \033[32mok\033[0m    {message}")


# ---------------------------------------------------------------------------
# A minimal stand-in for the bits of Airflow the DAG touches.
# ---------------------------------------------------------------------------
TASKS: dict[str, object] = {}
EDGES: list[tuple[str, str]] = []


class _BaseOperator:
    def __init__(self, task_id=None, **kwargs):
        self.task_id = task_id
        self.kwargs = kwargs
        TASKS[task_id] = self

    def __rshift__(self, other):
        # `a >> b >> c` parses as `(a >> b) >> c`, so returning `other`
        # reproduces Airflow's own chaining behaviour.
        EDGES.append((self.task_id, other.task_id))
        return other


class _DAG:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def install_airflow_stub() -> None:
    airflow = _module("airflow")
    airflow.DAG = _DAG

    _module("airflow.providers")
    _module("airflow.providers.common")
    _module("airflow.providers.common.sql")
    _module("airflow.providers.common.sql.operators")
    sql_ops = _module("airflow.providers.common.sql.operators.sql")
    sql_ops.SQLExecuteQueryOperator = type(
        "SQLExecuteQueryOperator", (_BaseOperator,), {}
    )

    _module("airflow.providers.standard")
    _module("airflow.providers.standard.operators")
    bash_ops = _module("airflow.providers.standard.operators.bash")
    bash_ops.BashOperator = type("BashOperator", (_BaseOperator,), {})


def load_dag():
    install_airflow_stub()
    spec = importlib.util.spec_from_file_location("zomato_batch_under_test", DAG_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    print("Airflow DAG structure checks")
    print(f"dag: {DAG_FILE.relative_to(ROOT)}")

    if not DAG_FILE.is_file():
        fail(f"{DAG_FILE} does not exist")
        return 1

    try:
        dag_module = load_dag()
    except Exception as exc:  # noqa: BLE001
        fail(f"the DAG file failed to import: {type(exc).__name__}: {exc}")
        return 1

    print("\n\033[1mTask chain\033[0m")

    missing = [t for t in EXPECTED_CHAIN if t not in TASKS]
    for task in missing:
        fail(f"documented task {task!r} is not defined in the DAG")

    unexpected = [t for t in TASKS if t not in EXPECTED_CHAIN]
    for task in unexpected:
        fail(f"task {task!r} exists in the DAG but is not in the documented chain")

    expected_edges = list(zip(EXPECTED_CHAIN, EXPECTED_CHAIN[1:]))
    if EDGES != expected_edges:
        fail(f"task order is {EDGES}, expected {expected_edges}")
    elif not missing and not unexpected:
        ok(f"{len(TASKS)} tasks chained exactly as documented:")
        print("        " + " -> ".join(EXPECTED_CHAIN))

    # -----------------------------------------------------------------------
    print("\n\033[1mDAG settings\033[0m")
    dag = getattr(dag_module, "dag", None)
    if dag is None:
        fail("the module does not expose a `dag` object")
    else:
        settings = dag.kwargs
        checks = [
            ("schedule", "@daily"),
            ("catchup", False),
            ("max_active_runs", 1),
        ]
        for key, expected in checks:
            actual = settings.get(key)
            if actual != expected:
                fail(f"dag {key} is {actual!r}, expected {expected!r}")
            else:
                ok(f"{key} = {actual!r}")

        if settings.get("dag_id") != "zomato_batch":
            fail(f"dag_id is {settings.get('dag_id')!r}, expected 'zomato_batch'")
        else:
            ok("dag_id = 'zomato_batch'")

    # -----------------------------------------------------------------------
    print("\n\033[1mLoad task\033[0m")
    reload_task = TASKS.get("reload_raw")
    if reload_task is None:
        fail("reload_raw is missing, cannot check its SQL")
    else:
        sql = "\n".join(reload_task.kwargs.get("sql", []))
        for table in RAW_TABLES:
            if f"COPY INTO ZOMATO.RAW.{table}" not in sql:
                fail(f"reload_raw never copies RAW.{table}")
        covered = sum(1 for t in RAW_TABLES if f"COPY INTO ZOMATO.RAW.{t}" in sql)
        if covered == len(RAW_TABLES):
            ok(f"COPY INTO covers all {len(RAW_TABLES)} raw tables")

        if "USE WAREHOUSE ZOMATO_WH" not in sql:
            fail("reload_raw does not select the warehouse before copying")
        else:
            ok("warehouse is selected before the COPY statements")

        if reload_task.kwargs.get("split_statements") is not True:
            fail("split_statements must be True or the statement list will not run")
        else:
            ok("split_statements = True")

    # -----------------------------------------------------------------------
    print("\n\033[1mTask commands\033[0m")
    for task_id in ("dbt_build_core", "dbt_snapshot", "dbt_build_ai", "dbt_docs_generate"):
        task = TASKS.get(task_id)
        if task is None:
            continue
        command = task.kwargs.get("bash_command", "")
        if "/opt/airflow/dbt_venv/bin/dbt" not in command:
            fail(f"{task_id} does not use the dbt virtualenv path")
        if "--profiles-dir" not in command or "--project-dir" not in command:
            fail(f"{task_id} does not pass --project-dir and --profiles-dir")

    build_core = TASKS.get("dbt_build_core")
    if build_core and "--exclude tag:ai" not in build_core.kwargs.get("bash_command", ""):
        fail("dbt_build_core must exclude tag:ai, or it will fail on a fresh warehouse")

    # `dbt build` runs snapshots too (models, tests, snapshots and seeds in DAG
    # order). Without this exclusion the snapshot runs twice per scheduled run:
    # once in dbt_build_core and once in dbt_snapshot.
    if build_core and "--exclude resource_type:snapshot" not in build_core.kwargs.get(
        "bash_command", ""
    ):
        fail(
            "dbt_build_core must exclude resource_type:snapshot, or dbt_snapshot "
            "would run the snapshot a second time"
        )

    build_ai = TASKS.get("dbt_build_ai")
    if build_ai and "--select tag:ai" not in build_ai.kwargs.get("bash_command", ""):
        fail("dbt_build_ai must select tag:ai")

    if build_core and build_ai:
        ok("phase 1 excludes tag:ai and the snapshot; phase 2 selects tag:ai")

    # Every dbt task must point at the project directory that is really mounted.
    mounted = ROOT / "zomato"
    if not mounted.is_dir():
        fail("the zomato/ project directory is missing")
    elif build_core and "/opt/airflow/dbt/zomato" in build_core.kwargs.get("bash_command", ""):
        ok("dbt tasks use the path docker-compose mounts the project at")

    enrich = TASKS.get("enrich_reviews")
    if enrich:
        command = enrich.kwargs.get("bash_command", "")
        if "/opt/airflow/ai/enrich_reviews.py" not in command:
            fail("enrich_reviews does not call /opt/airflow/ai/enrich_reviews.py")
        elif not (ROOT / "ai" / "enrich_reviews.py").is_file():
            fail("ai/enrich_reviews.py does not exist, so the task would fail")
        else:
            ok("enrich_reviews points at a script that exists")

    print()
    if errors:
        print(f"\033[31m{len(errors)} error(s)\033[0m")
        return 1

    print("\033[32mDAG structure checks passed\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
