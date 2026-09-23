"""
Shared helpers for the AI layer.

Every AI script in this directory talks to the same two systems — Snowflake and
OpenAI — and reads the same `.env`. Keeping that in one place means the
credential handling (including key-pair auth) is written once and the three apps
stay focused on the interesting part.

Credentials are read from the environment, never from code. Locally that comes
from the project-root `.env`; in the Airflow container it comes from the
environment variables docker-compose injects.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import snowflake.connector
from dotenv import load_dotenv
from openai import OpenAI

# ai/common.py -> ai/ -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# The read-only role the query-running apps use. Created in snowflake/01_setup.sql.
AI_READONLY_ROLE = os.getenv("SNOWFLAKE_AI_ROLE", "ZOMATO_AI_RO")


class ConfigError(RuntimeError):
    """A required environment variable is missing."""


def require_env(name: str) -> str:
    """Return an environment variable, or explain exactly what is missing."""
    value = os.getenv(name)
    if not value:
        raise ConfigError(
            f"{name} is not set.\n"
            f"Copy the template and fill it in:\n"
            f"    cp {PROJECT_ROOT / '.env.example'} {PROJECT_ROOT / '.env'}"
        )
    return value


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def get_connection(
    *,
    role: str | None = None,
    schema: str | None = None,
    database: str | None = None,
):
    """
    Open a Snowflake connection from environment variables.

    Supports both auth styles, choosing automatically:

      * key-pair  — set SNOWFLAKE_PRIVATE_KEY_PATH (preferred; nothing secret
                    is typed, copied or pasted)
      * password  — set SNOWFLAKE_PASSWORD

    Pass `role=AI_READONLY_ROLE` for anything that runs model-generated SQL.
    Pass `schema`/`database` to change the session default from the .env values.
    """
    params: dict[str, Any] = {
        "account": require_env("SNOWFLAKE_ACCOUNT"),
        "user": require_env("SNOWFLAKE_USER"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "ZOMATO_WH"),
        "database": database or os.getenv("SNOWFLAKE_DATABASE", "ZOMATO"),
        "schema": schema or os.getenv("SNOWFLAKE_SCHEMA", "STAGING"),
        "role": role or os.getenv("SNOWFLAKE_ROLE", "DBT_ROLE"),
        "client_session_keep_alive": False,
    }

    private_key_path = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH")
    if private_key_path:
        params["private_key_file"] = private_key_path
        passphrase = os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "")
        if passphrase:
            params["private_key_file_pwd"] = passphrase
    else:
        params["password"] = require_env("SNOWFLAKE_PASSWORD")

    return snowflake.connector.connect(**params)


def get_client() -> OpenAI:
    """OpenAI client. Raises ConfigError with instructions if the key is absent."""
    return OpenAI(api_key=require_env("OPENAI_API_KEY"))


def fetch_dataframe(conn, sql: str, params: dict | None = None):
    """Run a query and return a pandas DataFrame with lowercased column names."""
    with conn.cursor() as cur:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        df = cur.fetch_pandas_all()
    df.columns = [c.lower() for c in df.columns]
    return df


def fail(message: str) -> None:
    """Print a clean error to stderr and exit non-zero (no traceback wall)."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)
