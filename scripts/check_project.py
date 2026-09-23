#!/usr/bin/env python3
"""
Static consistency checks for the project.

`dbt build` only catches these problems after it has a live Snowflake
connection — usually several minutes in, and usually with a confusing error.
This script catches them in about a second, offline:

  1. Every YAML file parses.
  2. Every JSON file parses.
  3. Every `ref()` and `source()` in the dbt project resolves to something that
     actually exists. A typo'd ref is the single most common dbt mistake.
  4. Every declared dbt `source()` really is created by the SQL (or Python) that
     is supposed to create it — and vice versa.
  5. If data/raw/ has been generated, each CSV's header row matches the column
     order of its Snowflake RAW table. This is the check that catches a
     generator/DDL drift before COPY INTO silently loads the wrong values into
     the wrong columns. Column *names* are compared only where they are machine
     identifiers; the messy human-readable headers in the original dimension
     exports are normalised by the DDL on purpose and are reported, not failed.

Run it with:

    python3 scripts/check_project.py
    make check
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBT_PROJECT = ROOT / "zomato"
RAW_DDL_FILE = ROOT / "snowflake" / "04_raw_tables.sql"
ENRICH_SCRIPT = ROOT / "ai" / "enrich_reviews.py"
GENERATED_DATA = ROOT / "data" / "raw"

# Directories never worth walking.
SKIP_DIRS = {".git", "target", "dbt_packages", "logs", "__pycache__", ".venv", "node_modules"}

# A header field that is a machine-generated identifier rather than a
# human-readable label. Only these are held to an exact name match against the
# Snowflake DDL; see check_csv_headers_match_ddl().
CLEAN_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

errors: list[str] = []
warnings: list[str] = []


def ok(message: str) -> None:
    print(f"  \033[32mok\033[0m    {message}")


def fail(message: str) -> None:
    errors.append(message)
    print(f"  \033[31mFAIL\033[0m  {message}")


def warn(message: str) -> None:
    warnings.append(message)
    print(f"  \033[33mwarn\033[0m  {message}")


def walk(suffixes: tuple[str, ...]) -> list[Path]:
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in suffixes:
            found.append(path)
    return sorted(found)


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


# ---------------------------------------------------------------------------
# 1 + 2 · Config files parse
# ---------------------------------------------------------------------------
def check_config_files() -> None:
    section("Config files")

    try:
        import yaml
    except ImportError:
        warn(
            "pyyaml is not installed — YAML validation skipped. "
            "Install it with: pip install -r requirements-dev.txt"
        )
        yaml = None

    if yaml is not None:
        yaml_files = walk((".yml", ".yaml"))
        broken = 0
        skipped_jinja = 0
        for path in yaml_files:
            text = path.read_text(encoding="utf-8")

            # profiles.yml contains Jinja *statements*, which dbt renders before
            # parsing and a raw YAML parser cannot read. `dbt parse` in CI is
            # what validates that file.
            #
            # Comments are stripped first, so that prose *about* Jinja (like the
            # note in profiles.yml explaining why `{% if %}` is unsupported)
            # does not trigger the skip.
            #
            # Only `{% ... %}` blocks are skipped — deliberately. Quoted
            # `{{ ... }}` expressions are perfectly valid YAML, so leaving them
            # in the check is what catches the classic profiles.yml bug:
            #
            #     threads: {{ env_var('DBT_THREADS', '8') }}
            #
            # which YAML reads as the start of a flow mapping and rejects with
            # "did not find expected ',' or '}'". Quoting it fixes it, and this
            # check notices when someone forgets.
            code_lines = [
                line for line in text.splitlines()
                if not line.lstrip().startswith("#")
            ]
            if any("{%" in line for line in code_lines):
                skipped_jinja += 1
                continue

            try:
                yaml.safe_load(text)
            except yaml.YAMLError as exc:
                broken += 1
                fail(f"{path.relative_to(ROOT)}: {exc}")

        if not broken:
            note = f" ({skipped_jinja} Jinja template skipped)" if skipped_jinja else ""
            ok(f"{len(yaml_files) - skipped_jinja} YAML file(s) parse{note}")

    json_files = walk((".json",))
    broken = 0
    for path in json_files:
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            broken += 1
            fail(f"{path.relative_to(ROOT)}: {exc}")
    if not broken:
        ok(f"{len(json_files)} JSON file(s) parse")


# ---------------------------------------------------------------------------
# 3 · Every ref() and source() resolves
# ---------------------------------------------------------------------------
def collect_model_names() -> set[str]:
    """Every model name dbt will know about, i.e. the file stem of each model."""
    names: set[str] = set()
    for directory in ("models", "snapshots"):
        base = DBT_PROJECT / directory
        if base.is_dir():
            names.update(p.stem for p in base.rglob("*.sql"))
    return names


def collect_sources() -> tuple[set[tuple[str, str]], dict[tuple[str, str], dict]]:
    """Parse every _*.yml for declared sources -> {(source_name, table_name)}."""
    import yaml

    declared: set[tuple[str, str]] = set()
    meta: dict[tuple[str, str], dict] = {}

    for path in DBT_PROJECT.rglob("*.yml"):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue

        for source in doc.get("sources", []) or []:
            source_name = source.get("name")
            for table in source.get("tables", []) or []:
                key = (source_name, table.get("name"))
                declared.add(key)
                meta[key] = {
                    "database": source.get("database"),
                    "schema": source.get("schema"),
                    "file": path.relative_to(ROOT),
                }

    return declared, meta


REF_PATTERN = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
SOURCE_PATTERN = re.compile(r"source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


def check_dbt_references() -> None:
    section("dbt references")

    try:
        import yaml  # noqa: F401
    except ImportError:
        warn("pyyaml is not installed — reference validation skipped")
        return

    models = collect_model_names()
    sources, _ = collect_sources()

    scan_files = [
        p for p in DBT_PROJECT.rglob("*")
        if p.is_file() and p.suffix in (".sql", ".yml", ".yaml")
    ]

    bad_refs: dict[str, set[str]] = {}
    bad_sources: dict[tuple[str, str], set[str]] = {}

    for path in scan_files:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(ROOT))

        for name in REF_PATTERN.findall(text):
            if name not in models:
                bad_refs.setdefault(name, set()).add(rel)

        for source_name, table_name in SOURCE_PATTERN.findall(text):
            if (source_name, table_name) not in sources:
                bad_sources.setdefault((source_name, table_name), set()).add(rel)

    if bad_refs:
        for name, where in sorted(bad_refs.items()):
            fail(f"ref('{name}') does not resolve — used in {', '.join(sorted(where))}")
    else:
        ok(f"every ref() resolves ({len(models)} model(s))")

    if bad_sources:
        for (source_name, table_name), where in sorted(bad_sources.items()):
            fail(
                f"source('{source_name}', '{table_name}') is not declared "
                f"— used in {', '.join(sorted(where))}"
            )
    else:
        ok(f"every source() is declared ({len(sources)} source table(s))")


# ---------------------------------------------------------------------------
# 4 · Declared sources match what actually creates them
# ---------------------------------------------------------------------------
def parse_raw_ddl_tables() -> dict[str, list[str]]:
    """{table_name: [column, ...]} from snowflake/04_raw_tables.sql, in order."""
    if not RAW_DDL_FILE.is_file():
        return {}

    text = RAW_DDL_FILE.read_text(encoding="utf-8")
    # Ignore commented-out lines so the example DDL at the bottom does not count.
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("--"))

    tables: dict[str, list[str]] = {}
    pattern = re.compile(
        r"CREATE\s+OR\s+REPLACE\s+TABLE\s+RAW\.(\w+)\s*\((.*?)\n\s*\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )

    for match in pattern.finditer(text):
        table = match.group(1)
        body = match.group(2)
        columns = []
        for line in body.splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if not line or line.startswith(")"):
                continue
            columns.append(line.split()[0])
        tables[table] = columns

    return tables


def check_sources_match_producers() -> None:
    section("Sources vs producers")

    try:
        import yaml  # noqa: F401
    except ImportError:
        warn("pyyaml is not installed — source/producer cross-check skipped")
        return

    sources, _ = collect_sources()
    raw_ddl = parse_raw_ddl_tables()

    declared_raw = {table for (name, table) in sources if name == "raw"}

    missing_ddl = declared_raw - set(raw_ddl)
    for table in sorted(missing_ddl):
        fail(f"dbt declares source raw.{table} but snowflake/04_raw_tables.sql never creates it")

    undeclared = set(raw_ddl) - declared_raw
    for table in sorted(undeclared):
        warn(f"snowflake/04_raw_tables.sql creates RAW.{table} but no dbt source declares it")

    if not missing_ddl and raw_ddl:
        ok(f"all {len(declared_raw)} raw source(s) are created by snowflake/04_raw_tables.sql")

    # The AI source is produced by Python, not SQL.
    ai_tables = {table for (name, table) in sources if name == "ai"}
    if ai_tables and ENRICH_SCRIPT.is_file():
        script = ENRICH_SCRIPT.read_text(encoding="utf-8")
        not_created = [t for t in sorted(ai_tables) if t.upper() not in script.upper()]
        for table in not_created:
            fail(
                f"dbt declares source ai.{table} but ai/enrich_reviews.py never creates it"
            )
        if not not_created:
            ok(f"ai source(s) {sorted(ai_tables)} are created by ai/enrich_reviews.py")


# ---------------------------------------------------------------------------
# 5 · CSV headers match RAW DDL column order
# ---------------------------------------------------------------------------
def check_csv_headers_match_ddl() -> None:
    section("CSV headers vs RAW DDL")

    raw_ddl = parse_raw_ddl_tables()
    if not raw_ddl:
        warn("could not parse snowflake/04_raw_tables.sql — header check skipped")
        return

    if not GENERATED_DATA.is_dir():
        warn(
            "data/raw/ does not exist — skipping header check. "
            "Generate a small dataset to enable it: make data-small"
        )
        return

    checked = 0
    informational: list[tuple[str, int, str, str]] = []
    for table, columns in sorted(raw_ddl.items()):
        csv_path = GENERATED_DATA / table / f"{table}.csv"
        if not csv_path.is_file():
            warn(f"{csv_path.relative_to(ROOT)} not found — skipping")
            continue

        with csv_path.open(encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n")

        fields = header.split(",")

        if len(fields) != len(columns):
            fail(
                f"{table}.csv has {len(fields)} header field(s) but RAW.{table} "
                f"has {len(columns)} column(s)"
            )
            continue

        # Two different kinds of header field, checked two different ways:
        #
        #   * A clean snake_case name (the generated fact files, and the columns
        #     the DDL renames nothing in) MUST match its DDL column. A rename
        #     here is a real bug: it would mean the generator and the table have
        #     drifted apart.
        #
        #   * A human-readable header from the original messy exports
        #     ("Marital Status", "Monthly Income", "Family size") is
        #     documentation only. Snowflake never reads it — SKIP_HEADER = 1 and
        #     the load is positional — so the DDL deliberately normalises those
        #     names. Report, do not fail.
        #
        # Both kinds must still be in the right POSITION, which the count check
        # above plus the ordered comparison below enforce.
        mismatched = []
        for index, (field, column) in enumerate(zip(fields, columns)):
            # The dimension files carry an unnamed leading index column.
            if not field:
                continue
            if not CLEAN_IDENTIFIER.match(field):
                informational.append((table, index, field, column))
                continue
            if field.lower() != column.lower():
                mismatched.append((index, field, column))

        if mismatched:
            for index, field, column in mismatched:
                fail(
                    f"{table}.csv column {index} is {field!r} but RAW.{table} "
                    f"column {index} is {column!r}"
                )
        else:
            checked += 1

    if checked:
        ok(f"{checked} CSV header(s) match their RAW table column order")

    if informational:
        # Expected for the four dimension exports. Positional load, so harmless.
        ok(
            f"{len(informational)} header name(s) differ by design "
            f"(messy source headers the DDL normalises; position still checked)"
        )


def main() -> int:
    print("Project consistency checks")
    print(f"root: {ROOT}")

    try:
        import yaml  # noqa: F401
    except ImportError:
        pass

    check_config_files()
    check_dbt_references()
    check_sources_match_producers()
    check_csv_headers_match_ddl()

    print()
    if errors:
        print(f"\033[31m{len(errors)} error(s)\033[0m, {len(warnings)} warning(s)")
        return 1

    print(f"\033[32mAll checks passed\033[0m ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
