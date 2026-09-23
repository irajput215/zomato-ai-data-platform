"""
Text-to-SQL — chat with your warehouse.

    English question --> LLM writes Snowflake SQL --> guard checks it --> runs as a read-only role

Three things make this safe enough to put in front of a person:

  1. A read-only role. The app connects as ZOMATO_AI_RO, which holds SELECT and
     nothing else (snowflake/01_setup.sql). Even a guard bypass cannot write.
  2. A generated-SQL guard. Comments are stripped first, then the statement must
     begin with SELECT or WITH, must be a single statement, and must not contain
     any DDL/DML keyword as a whole word.
  3. An enforced row limit. If the model forgets LIMIT, the query is wrapped in
     an outer one. A surprise 10M-row result cannot hang the browser.

The model is given the real column list, introspected live from
INFORMATION_SCHEMA, so it does not have to guess what exists.

Usage:
    streamlit run ai/text_to_sql.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AI_READONLY_ROLE,
    ConfigError,
    DEFAULT_CHAT_MODEL,
    fetch_dataframe,
    get_client,
    get_connection,
)

EXAMPLE_QUESTIONS = [
    "Top 10 cities by GMV",
    "Which cuisine has the most orders?",
    "Average delivery time by city, worst first",
    "Cancel rate by payment method",
    "Which restaurants have the worst late-delivery rate?",
    "How does sentiment differ by topic?",
]

# Matched as whole words only, so a column called `created_at` cannot trip the
# guard.
#
# ⚠️ Whole-word matching alone is NOT enough, which is easy to get wrong. The word
# boundary in `\bdrop\b` sits between `p` and `-`, so it DOES match the "Drop" in
# the innocent string literal 'Drop-off'. That is why check_sql() blanks string
# literals before scanning: the guard should block statements, not data.
#
# NOTE: `comment` is deliberately NOT in this list. It is a Snowflake DDL
# keyword (COMMENT ON TABLE ...) but it is also a real column name in
# STAGING.STG_REVIEWS, and blocking it would break the single most obvious
# question anyone asks this app. The "must start with SELECT or WITH" check
# already rules out `COMMENT ON`.
FORBIDDEN_PATTERN = re.compile(
    r"\b(drop|delete|truncate|alter|update|insert|create|replace|grant|revoke"
    r"|merge|call|copy|put|remove|use|execute|undelete)\b",
    re.IGNORECASE,
)

# Curated fallback, used only if INFORMATION_SCHEMA is unreachable.
FALLBACK_SCHEMA = """
FCT_ORDERS(order_id, order_timestamp, order_date, customer_id, restaurant_id, city,
           cuisine, payment_method, order_status, is_delivered, items_count, sales_qty,
           subtotal, discount, delivery_fee, gst, sales_amount, customer_rating, delivery_time_min)
FCT_ORDER_ITEMS(order_item_id, order_id, restaurant_id, food_id, order_ts, order_date, city,
                price, quantity, line_amount)
DIM_RESTAURANTS(restaurant_id, restaurant_name, city, cuisine, rating, rating_count, cost_for_two)
DIM_CUSTOMER(customer_id, customer_name, email, age, age_segment, gender, marital_status,
             occupation, income_band, education, family_size)
DIM_FOOD(food_id, food_name, veg_or_non_veg)
DIM_DATE(date_day, year, month, month_name, day_name, day_of_week, is_weekend, month_start)
MART_DAILY_CITY_REVENUE(order_date, city, orders, delivered_orders, cancelled_orders,
                         refunded_orders, cancel_rate, gmv, aov, discount_given, avg_customer_rating)
MART_DELIVERY_SLA(city, order_hour, delivered_orders, p50_delivery_min, p90_delivery_min,
                  avg_delivery_min, worst_delivery_min, late_orders, late_rate)
MART_RESTAURANT_PERFORMANCE(restaurant_id, restaurant_name, city, cuisine, orders,
                            delivered_orders, revenue, aov, avg_customer_rating,
                            avg_delivery_min, cancel_rate)
MART_REVIEW_INSIGHTS(city, topic, sentiment_label, reviews, avg_sentiment_score,
                     avg_star_rating, flagged_issues, first_review_date, last_review_date)
"""

SYSTEM_PROMPT_TEMPLATE = """
You are a Snowflake SQL expert. Write ONE SELECT query that answers the question.

Rules:
- SELECT (or WITH ... SELECT) only. Never modify data.
- Use bare table names: FCT_ORDERS, not ZOMATO.MARTS.FCT_ORDERS.
- Prefer the MART_ tables when they already answer the question.
- gmv means delivered revenue; is_delivered is a boolean column.
- Add a LIMIT of 100 or less, unless the question asks for a single total.
- Reply as JSON in this exact format: {{"sql": "your query here"}}

Tables available:
{schema}
"""


def strip_sql_comments(sql: str) -> str:
    """Remove -- line comments and /* block */ comments before inspecting."""
    without_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", without_block)


def get_schema_description(conn) -> str:
    """Live column list for every queryable schema, falling back to a static one."""
    try:
        df = fetch_dataframe(
            conn,
            """
            SELECT table_schema, table_name, column_name
            FROM ZOMATO.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema IN ('MARTS', 'STAGING', 'AI')
              AND table_name <> 'PIPELINE_HEALTH'
            ORDER BY table_schema, table_name, ordinal_position
            """,
        )
        if df.empty:
            return FALLBACK_SCHEMA

        lines = []
        for (schema, table), group in df.groupby(["table_schema", "table_name"], sort=True):
            columns = ", ".join(group["column_name"])
            lines.append(f"-- {schema}\n{table}({columns})")
        return "\n".join(lines)

    except Exception:  # noqa: BLE001 - introspection is a nicety, not a requirement
        return FALLBACK_SCHEMA


@st.cache_resource(show_spinner=False)
def get_readonly_connection():
    """One cached connection, as the SELECT-only role."""
    return get_connection(role=AI_READONLY_ROLE, schema="MARTS")


@st.cache_data(show_spinner=False)
def load_schema_description() -> str:
    try:
        return get_schema_description(get_readonly_connection())
    except Exception:  # noqa: BLE001
        return FALLBACK_SCHEMA


def generate_sql(question: str, schema: str, model: str) -> str:
    response = get_client().chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(schema=schema)},
            {"role": "user", "content": question},
        ],
    )
    sql = json.loads(response.choices[0].message.content)["sql"]

    # Models like to qualify names even when told not to; harmless to strip.
    sql = sql.replace("ZOMATO.MARTS.", "").replace("ZOMATO.STAGING.", "").replace("ZOMATO.", "")
    return sql.strip().rstrip(";").strip()


def strip_sql_strings(sql: str) -> str:
    """
    Blank out '...' literals before the keyword scan.

    Two false positives this removes, both of which the whole-word regex alone
    gets wrong:

      * `\\bdrop\\b` matches "Drop" in the literal 'Drop-off', because `-` is a
        word boundary. A question about drop-off rates was being blocked.
      * a semicolon inside a literal ('a;b') looked like a second statement.

    Emptying the literals keeps the guard honest in both directions: real DDL
    keywords are still caught, and data that merely spells like one is not.
    """
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def check_sql(sql: str) -> tuple[bool, str]:
    """Return (is_safe, reason). Comments and string literals are removed first."""
    cleaned = strip_sql_comments(sql).strip()

    if not cleaned:
        return False, "The model returned an empty statement."

    # Scan the statement, not its data — see strip_sql_strings().
    body = strip_sql_strings(cleaned)
    body = body[:-1] if body.endswith(";") else body

    if not re.match(r"^(select|with)\b", body, re.IGNORECASE):
        return False, "Only SELECT queries are allowed."

    if ";" in body:
        return False, "Only a single statement is allowed."

    match = FORBIDDEN_PATTERN.search(body)
    if match:
        return False, f"The statement contains a forbidden keyword: {match.group(0)!r}"

    # A SELECT can still call a function with side effects; these are the ones
    # that realistically matter in Snowflake.
    if re.search(r"\bsystem\$|\butil\.db\b|information_schema\.|account_usage\.", body, re.IGNORECASE):
        return False, "Queries against system or account-level metadata are not allowed."

    return True, ""


def enforce_limit(sql: str, max_rows: int) -> str:
    """
    Guarantee the row cap, including when the model wrote its own LIMIT.

    A generated `LIMIT 5000000` is not a cap — it is a very large number the model
    picked, and the first version of this function returned it unchanged, which
    made the UI's "Row cap" slider decorative. Now the query is wrapped unless its
    own LIMIT is already at or below the ceiling.

    Wrapping is always safe: an outer LIMIT bounds the result set however large
    the inner one is, and Snowflake pushes the outer limit down.
    """
    match = re.search(r"\blimit\s+(\d+)", strip_sql_comments(sql), re.IGNORECASE)
    if match and int(match.group(1)) <= int(max_rows):
        return sql
    return f"SELECT * FROM (\n{sql}\n) LIMIT {int(max_rows)}"


def run_query(sql: str) -> pd.DataFrame:
    return fetch_dataframe(get_readonly_connection(), sql)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Chat with your Zomato data", page_icon="📊", layout="wide")
st.title("Chat with your Zomato data")
st.caption(
    "Ask in English · the model writes the SQL · Snowflake runs it as "
    f"`{AI_READONLY_ROLE}` (SELECT only)"
)

with st.sidebar:
    st.header("Example questions")
    for example in EXAMPLE_QUESTIONS:
        st.markdown(f"- {example}")

    st.divider()
    st.header("Settings")
    model = st.text_input("Model", DEFAULT_CHAT_MODEL)
    max_rows = st.number_input("Row cap", min_value=10, max_value=5000, value=100, step=10)
    show_schema = st.toggle("Show schema sent to the model", value=False)

schema_description = load_schema_description()

if show_schema:
    with st.expander("Schema", expanded=False):
        st.code(schema_description, language="sql")

question = st.text_input(
    "Enter your question",
    placeholder="e.g. Top 10 restaurants by revenue in Bangalore",
)

if question:
    try:
        sql = generate_sql(question, schema_description, model)
    except ConfigError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not generate SQL: {exc}")
        st.stop()

    st.code(sql, language="sql")

    is_safe, reason = check_sql(sql)
    if not is_safe:
        st.error(f"Blocked by the SQL guard: {reason}")

    else:
        safe_sql = enforce_limit(sql, max_rows)
        if safe_sql != sql:
            st.caption(f"Row cap applied: wrapped in an outer `LIMIT {int(max_rows)}`.")

        try:
            df = run_query(safe_sql)
            st.success(f"{len(df)} row(s) returned as `{AI_READONLY_ROLE}`")
            st.dataframe(df, hide_index=True, use_container_width=True)

            # One dimension + one measure: draw it. Anything else would need a
            # chart-config UI, which is a different app.
            if len(df.columns) == 2 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
                st.bar_chart(df, x=df.columns[0], y=df.columns[1])

        except Exception as exc:  # noqa: BLE001
            st.error(f"Snowflake rejected the query: {exc}")
