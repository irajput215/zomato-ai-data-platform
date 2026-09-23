"""
RAG — chat with your reviews.

    question --> embed --> nearest reviews --> LLM answers, grounded in those reviews

No fine-tuning, no vector database. 500 reviews is a few thousand floats, so a
numpy dot product over a small in-memory matrix is both simpler and faster than
standing up an index.

The point of the exercise is the "grounded" part: the model is told to answer
ONLY from the retrieved reviews, and the app shows you exactly which reviews it
used. If the answer is wrong, you can see which source misled it.

Embeddings are cached to a parquet file so you pay OpenAI once per sample size
rather than once per page interaction.

Usage:
    streamlit run ai/rag_chat.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    AI_READONLY_ROLE,
    ConfigError,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    env_int,
    get_client,
    get_connection,
)

CACHE_FILE = Path(__file__).resolve().parent / "review_embeddings.parquet"
EMBED_BATCH_SIZE = 256


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def read_reviews_from_snowflake(sample_n: int) -> pd.DataFrame:
    """Pull a random sample of reviews. SAMPLE is a Snowflake table function."""
    # Read-only role: this app only ever SELECTs, so it has no business holding a
    # role that can write. Same reason text_to_sql.py uses it.
    with get_connection(role=AI_READONLY_ROLE, schema="STAGING") as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT review_id, city, rating, comment
                FROM ZOMATO.STAGING.STG_REVIEWS
                SAMPLE ({int(sample_n)} ROWS)
                """
            )
            df = cur.fetch_pandas_all()
    df.columns = [c.lower() for c in df.columns]
    return df.reset_index(drop=True)


def embed_texts(client, texts: list[str], model: str) -> list[list[float]]:
    """Embed in batches — the API accepts many inputs per request."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        response = client.embeddings.create(model=model, input=batch)
        # The API does not guarantee ordering; `index` does.
        ordered = sorted(response.data, key=lambda item: item.index)
        vectors.extend(item.embedding for item in ordered)
    return vectors


@st.cache_data(show_spinner=False)
def load_reviews(sample_n: int, embedding_model: str) -> pd.DataFrame:
    """
    Reviews + embeddings, cached on disk.

    The cache filename carries the sample size, so changing the slider does not
    silently serve you embeddings for a different set of rows.
    """
    cache_file = CACHE_FILE.with_name(f"review_embeddings_{sample_n}.parquet")

    if cache_file.exists():
        return pd.read_parquet(cache_file)

    df = read_reviews_from_snowflake(sample_n)
    if df.empty:
        return df

    with st.spinner(f"Embedding {len(df)} reviews with {embedding_model}…"):
        df["embedding"] = embed_texts(
            get_client(), df["comment"].astype(str).tolist(), embedding_model
        )

    df.to_parquet(cache_file)
    return df


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def cosine_similarities(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """
    Cosine similarity between one query and every row, in two matrix ops.

    The obvious Python loop over rows is ~100x slower and buys nothing.
    The epsilon stops a zero vector from producing a divide-by-zero warning.
    """
    query_norm = query_vector / (np.linalg.norm(query_vector) + 1e-10)
    row_norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    return (matrix / row_norms) @ query_norm


def find_similar_reviews(question: str, df: pd.DataFrame, top_k: int, model: str) -> pd.DataFrame:
    query_vector = np.asarray(embed_texts(get_client(), [question], model)[0])
    matrix = np.vstack(df["embedding"].to_numpy())

    scored = df.drop(columns=["embedding"]).copy()
    scored["similarity"] = cosine_similarities(query_vector, matrix)
    return scored.nlargest(top_k, "similarity")


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def ask_llm(question: str, top_reviews: pd.DataFrame, model: str) -> str:
    context = "\n".join(
        f"- ({row.city or 'unknown city'}, {row.rating} stars) {row.comment}"
        for row in top_reviews.itertuples()
    )

    system_prompt = (
        "You answer questions about customer reviews for a food delivery app. "
        "Use ONLY the reviews provided below. Be concise and specific. "
        "If the reviews do not cover the question, say so plainly instead of guessing. "
        "When you make a claim, mention roughly how many of the reviews support it."
    )

    response = get_client().chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Question: {question}\n\nReviews:\n{context}"},
        ],
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Chat with your Zomato reviews", page_icon="🍽️", layout="wide")
st.title("Chat with your Zomato reviews")
st.caption("Retrieval-augmented generation over real customer reviews — answers are grounded in the reviews shown below.")

try:
    get_client()
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

with st.sidebar:
    st.header("Settings")
    sample_n = st.slider(
        "Reviews to load",
        min_value=50,
        max_value=5000,
        value=env_int("RAG_SAMPLE_N", 500),
        step=50,
        help="More reviews means better recall and a larger embedding bill. Cached per size.",
    )
    top_k = st.slider("Reviews retrieved per question", 3, 15, 5)
    chat_model = st.text_input("Answer model", DEFAULT_CHAT_MODEL)
    embedding_model = st.text_input("Embedding model", DEFAULT_EMBEDDING_MODEL)

try:
    reviews = load_reviews(sample_n, embedding_model)
except Exception as exc:  # noqa: BLE001 - surface it instead of a blank page
    st.error(f"Could not load reviews: {exc}")
    st.stop()

if reviews.empty:
    st.warning(
        "No reviews found in ZOMATO.STAGING.STG_REVIEWS. "
        "Run the pipeline first: `make pipeline` or trigger the `zomato_batch` DAG."
    )
    st.stop()

st.caption(f"{len(reviews):,} reviews loaded and embedded.")

question = st.text_input(
    "Ask a question about your reviews",
    placeholder="e.g. What are the most common complaints about delivery?",
)

if question:
    with st.spinner("Retrieving and answering…"):
        top_reviews = find_similar_reviews(question, reviews, top_k, embedding_model)
        answer = ask_llm(question, top_reviews, chat_model)

    st.markdown("**Answer**")
    st.write(answer)

    with st.expander(f"Reviews used to build this answer ({len(top_reviews)})", expanded=False):
        st.dataframe(
            top_reviews[["review_id", "city", "rating", "similarity", "comment"]],
            hide_index=True,
            use_container_width=True,
        )
