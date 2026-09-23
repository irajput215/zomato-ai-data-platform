"""
LLM as a transformation step.

Reads un-enriched review text out of ZOMATO.RAW.REVIEWS, asks an LLM to turn
each free-text comment into structured columns (sentiment, topic, key issue),
and writes the result to ZOMATO.AI.REVIEW_ENRICHED.

From there dbt treats it like any other source: `mart_review_insights` groups it
by city and topic. That is the whole trick — the model output lands in a table,
so it is testable, versionable and joinable like everything else.

Design choices that matter:

  Idempotent      Only reviews NOT already in the output table are processed, so
                  re-running never pays OpenAI twice for the same comment.
  Sample-capped   SAMPLE_N bounds the spend per run. Raise it deliberately.
  Validated       The model's JSON is coerced into the allowed label sets before
                  it touches the warehouse. A hallucinated topic cannot poison
                  the accepted_values test on the mart.
  Concurrent      A small thread pool, because 300K sequential API calls is a
                  very long wait.

Usage:
    python ai/enrich_reviews.py                      # SAMPLE_N from .env (default 5)
    python ai/enrich_reviews.py --sample-n 500
    python ai/enrich_reviews.py --dry-run --sample-n 3
    python ai/enrich_reviews.py --workers 8 --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402  (path shim above must run first)
    ConfigError,
    DEFAULT_CHAT_MODEL,
    env_int,
    fail,
    get_client,
    get_connection,
)

log = logging.getLogger("enrich_reviews")

TOPICS = ["food quality", "delivery", "pricing", "service", "packaging", "other"]
SENTIMENTS = ["positive", "negative", "neutral"]

OUTPUT_TABLE = "ZOMATO.AI.REVIEW_ENRICHED"

SYSTEM_PROMPT = f"""
You classify customer reviews for a food delivery app.

For the review you are given, return:
- sentiment_label: one of {SENTIMENTS}
- sentiment_score: a number between -1.0 and 1.0 (-1 = furious, 1 = delighted)
- topic: one of {TOPICS}
- key_issue: a short phrase of 6 words or less describing the main problem, or
  null when the review reports no problem

Judge only what the review actually says. Do not invent problems, and do not
let a high star rating override clearly negative text.

Reply as JSON in this exact format:
{{
    "sentiment_label": "<sentiment_label>",
    "sentiment_score": <sentiment_score>,
    "topic": "<topic>",
    "key_issue": <"<key_issue>" or null>
}}
"""

CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS ZOMATO.AI"

# Snowflake does not enforce PRIMARY KEY, but declaring it documents the grain
# and lets BI tools and the query optimiser use it.
CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (
    REVIEW_ID        STRING,
    SENTIMENT_LABEL  STRING,
    SENTIMENT_SCORE  FLOAT,
    TOPIC            STRING,
    KEY_ISSUE        STRING,
    MODEL            STRING,
    ENRICHED_AT      TIMESTAMP_LTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (REVIEW_ID)
)
"""

# NOT EXISTS rather than the more obvious `NOT IN`: it is null-safe and
# Snowflake optimises the anti-join better on a 300K-row table.
SELECT_PENDING_SQL = """
SELECT r.review_id, r.comment
FROM ZOMATO.RAW.REVIEWS r
WHERE r.comment IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM ZOMATO.AI.REVIEW_ENRICHED e
      WHERE e.review_id = r.review_id::STRING
  )
LIMIT %(sample_n)s
"""

INSERT_SQL = f"""
INSERT INTO {OUTPUT_TABLE}
    (review_id, sentiment_label, sentiment_score, topic, key_issue, model)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich Zomato reviews with LLM sentiment and topic labels.",
    )
    parser.add_argument(
        "--sample-n",
        type=int,
        default=env_int("SAMPLE_N", 5),
        help="Maximum reviews to process this run (default: SAMPLE_N env var, else 5).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_CHAT_MODEL,
        help=f"OpenAI chat model (default: {DEFAULT_CHAT_MODEL}).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent API calls (default: 4). Lower it if you hit rate limits.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=4,
        help="Retries per review on a transient API error (default: 4).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify but do not write to Snowflake.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Debug logging."
    )
    return parser.parse_args()


def validate_labels(raw: dict, model: str) -> dict:
    """
    Coerce the model's output into the exact vocabulary the warehouse expects.

    This is the guardrail that keeps a hallucinated topic from failing the
    accepted_values test on mart_review_insights three steps later.
    """
    sentiment = str(raw.get("sentiment_label", "")).strip().lower()
    if sentiment not in SENTIMENTS:
        log.warning("unknown sentiment_label %r -> 'neutral'", sentiment)
        sentiment = "neutral"

    try:
        score = float(raw.get("sentiment_score"))
    except (TypeError, ValueError):
        log.warning("unparseable sentiment_score %r -> 0.0", raw.get("sentiment_score"))
        score = 0.0
    score = max(-1.0, min(1.0, score))

    topic = str(raw.get("topic", "")).strip().lower()
    if topic not in TOPICS:
        log.warning("unknown topic %r -> 'other'", topic)
        topic = "other"

    issue = raw.get("key_issue")
    if issue is None or str(issue).strip().lower() in {"", "none", "null", "n/a"}:
        issue = None
    else:
        issue = str(issue).strip()
        if len(issue) > 120:
            issue = issue[:120]

    return {
        "sentiment_label": sentiment,
        "sentiment_score": score,
        "topic": topic,
        "key_issue": issue,
        "model": model,
    }


def classify_review(client, model: str, comment: str, max_retries: int) -> dict:
    """One review -> validated labels, with exponential backoff on transient errors."""
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": comment},
                ],
            )
            raw = json.loads(response.choices[0].message.content)
            return validate_labels(raw, model)

        except Exception as exc:  # noqa: BLE001 - we re-raise after the last try
            last_error = exc
            if attempt == max_retries:
                break
            backoff = min(2 ** attempt, 30)
            log.warning(
                "attempt %d/%d failed (%s) - retrying in %ds",
                attempt, max_retries, type(exc).__name__, backoff,
            )
            time.sleep(backoff)

    raise RuntimeError(f"classification failed after {max_retries} attempts: {last_error}")


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.sample_n <= 0:
        fail("--sample-n must be greater than zero")

    try:
        client = get_client()
        conn = get_connection(schema="AI")
    except ConfigError as exc:
        fail(str(exc))

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_SCHEMA_SQL)
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(SELECT_PENDING_SQL, {"sample_n": args.sample_n})
            pending = cur.fetchall()

        if not pending:
            log.info("no new reviews to enrich - nothing to do")
            return 0

        log.info(
            "enriching %d review(s) with %s (%d worker(s))",
            len(pending), args.model, args.workers,
        )

        results, failures = [], []

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(classify_review, client, args.model, comment, args.max_retries): review_id
                for review_id, comment in pending
            }
            for future in as_completed(futures):
                review_id = futures[future]
                try:
                    labels = future.result()
                except Exception as exc:  # noqa: BLE001
                    log.error("review %s failed: %s", review_id, exc)
                    failures.append(review_id)
                    continue

                log.info(
                    "review %s -> %s / %s / score %.2f",
                    review_id, labels["topic"], labels["sentiment_label"],
                    labels["sentiment_score"],
                )
                results.append((
                    str(review_id),
                    labels["sentiment_label"],
                    labels["sentiment_score"],
                    labels["topic"],
                    labels["key_issue"],
                    labels["model"],
                ))

        if args.dry_run:
            log.info("dry run - %d row(s) were NOT written", len(results))
        elif results:
            with conn.cursor() as cur:
                cur.executemany(INSERT_SQL, results)
            conn.commit()
            log.info("wrote %d row(s) to %s", len(results), OUTPUT_TABLE)

        if failures:
            log.warning(
                "%d review(s) could not be classified and will be retried next run",
                len(failures),
            )
            # Partial failure is not a pipeline failure: the un-enriched rows
            # stay pending and the next run picks them up.
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
