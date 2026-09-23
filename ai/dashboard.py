"""
Streamlit dashboard over the Gold marts.

This is the "so what" layer: the same tables the text-to-SQL app queries
invisibly, laid out as a fixed set of charts the business actually asked for.

Every chart reads a mart, never a raw table — if a number here looks wrong, the
bug is in dbt, not in this file.

Usage:
    streamlit run ai/dashboard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AI_READONLY_ROLE,
    ConfigError,
    fetch_dataframe,
    get_connection,
)

st.set_page_config(page_title="Zomato operations dashboard", page_icon="📈", layout="wide")


@st.cache_data(ttl=600, show_spinner=False)
def load_marts() -> dict[str, pd.DataFrame]:
    """
    Pull all four marts in one connection.

    A 10-minute TTL: long enough that clicking around the dashboard does not
    re-query Snowflake on every widget interaction, short enough that a fresh
    dbt run shows up while you are still looking at the screen.
    """
    queries = {
        "revenue": "SELECT * FROM ZOMATO.MARTS.MART_DAILY_CITY_REVENUE",
        "sla": "SELECT * FROM ZOMATO.MARTS.MART_DELIVERY_SLA",
        "restaurants": "SELECT * FROM ZOMATO.MARTS.MART_RESTAURANT_PERFORMANCE",
        "reviews": "SELECT * FROM ZOMATO.MARTS.MART_REVIEW_INSIGHTS",
    }
    # Role comes from the shared constant, not a hard-coded string, so changing
    # SNOWFLAKE_AI_ROLE changes it here too.
    with get_connection(role=AI_READONLY_ROLE, schema="MARTS") as conn:
        return {name: fetch_dataframe(conn, sql) for name, sql in queries.items()}


st.title("Zomato operations dashboard")
st.caption("Gold-layer marts, built by dbt and refreshed by the daily `zomato_batch` DAG.")

try:
    data = load_marts()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()
except Exception as exc:  # noqa: BLE001
    st.error(
        f"Could not read the marts: {exc}\n\n"
        "If a table is missing, run `make pipeline` or trigger the `zomato_batch` DAG. "
        "`mart_review_insights` only exists after the AI enrichment step has run."
    )
    st.stop()

revenue = data["revenue"]
sla = data["sla"]
restaurants = data["restaurants"]
reviews = data["reviews"]

if revenue.empty:
    st.warning("The marts are empty. Load some data first.")
    st.stop()

# ---------------------------------------------------------------------------
# Headline KPIs
# ---------------------------------------------------------------------------
total_gmv = revenue["gmv"].sum()
total_orders = revenue["orders"].sum()
delivered = revenue["delivered_orders"].sum()
overall_cancel_rate = revenue["cancelled_orders"].sum() / total_orders if total_orders else 0
overall_aov = total_gmv / delivered if delivered else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("GMV (delivered)", f"₹{total_gmv:,.0f}")
col2.metric("Orders", f"{total_orders:,.0f}")
col3.metric("Average order value", f"₹{overall_aov:,.2f}")
col4.metric("Cancel rate", f"{overall_cancel_rate:.2%}")

st.divider()

# ---------------------------------------------------------------------------
# GMV trend
# ---------------------------------------------------------------------------
st.subheader("GMV trend")

daily = (
    revenue.assign(order_date=pd.to_datetime(revenue["order_date"]))
    .groupby("order_date", as_index=False)
    .agg(gmv=("gmv", "sum"), orders=("orders", "sum"))
    .sort_values("order_date")
)

cities = sorted(revenue["city"].dropna().unique())
selected_cities = st.multiselect("Cities", cities, default=cities[:3])

if selected_cities:
    city_series = (
        revenue[revenue["city"].isin(selected_cities)]
        .assign(order_date=lambda df: pd.to_datetime(df["order_date"]))
        .pivot_table(index="order_date", columns="city", values="gmv", aggfunc="sum")
    )
    st.line_chart(city_series)
else:
    st.line_chart(daily.set_index("order_date")["gmv"])

# ---------------------------------------------------------------------------
# Delivery SLA
# ---------------------------------------------------------------------------
st.subheader("Delivery SLA")
st.caption("p50 and p90 delivery minutes by hour of day. Blank cells mean no delivered orders that hour.")

sla_city = st.selectbox("City", sorted(sla["city"].dropna().unique()))
city_sla = (
    sla[sla["city"] == sla_city]
    .set_index("order_hour")[["p50_delivery_min", "p90_delivery_min"]]
    .sort_index()
)
st.line_chart(city_sla)

left, right = st.columns(2)

with left:
    st.markdown("**Worst hours by late rate**")
    st.dataframe(
        sla[sla["delivered_orders"] >= 50]
        .nlargest(10, "late_rate")[["city", "order_hour", "delivered_orders", "late_rate"]],
        hide_index=True,
        use_container_width=True,
    )

with right:
    st.markdown("**Slowest cities (p90)**")
    st.dataframe(
        sla.groupby("city", as_index=False)
        .agg(delivered_orders=("delivered_orders", "sum"), p90=("p90_delivery_min", "mean"))
        .nlargest(10, "p90"),
        hide_index=True,
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Restaurants
# ---------------------------------------------------------------------------
st.subheader("Restaurant leaderboard")

min_orders = st.slider("Minimum orders", 1, 500, 50, step=10)
leaderboard = (
    restaurants[restaurants["orders"] >= min_orders]
    .nlargest(25, "revenue")[
        ["restaurant_name", "city", "cuisine", "orders", "revenue",
         "avg_customer_rating", "avg_delivery_min", "cancel_rate"]
    ]
)
st.dataframe(leaderboard, hide_index=True, use_container_width=True)

# ---------------------------------------------------------------------------
# Review insights (AI)
# ---------------------------------------------------------------------------
st.subheader("Review insights (LLM-enriched)")

if reviews.empty:
    st.info(
        "No enriched reviews yet. Run `python ai/enrich_reviews.py --sample-n 200`, "
        "then `dbt build --select tag:ai`."
    )
else:
    pivot = reviews.pivot_table(
        index="topic", columns="sentiment_label", values="reviews", aggfunc="sum"
    ).fillna(0)
    st.bar_chart(pivot)

    left, right = st.columns(2)
    with left:
        st.markdown("**Most flagged issues by topic**")
        st.dataframe(
            reviews.groupby("topic", as_index=False)
            .agg(reviews=("reviews", "sum"), flagged_issues=("flagged_issues", "sum"))
            .sort_values("flagged_issues", ascending=False),
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.markdown("**Sentiment by city**")
        st.dataframe(
            reviews.groupby(["city", "sentiment_label"], as_index=False)["reviews"]
            .sum()
            .sort_values("reviews", ascending=False)
            .head(20),
            hide_index=True,
            use_container_width=True,
        )
