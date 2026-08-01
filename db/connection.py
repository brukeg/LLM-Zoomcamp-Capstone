"""Shared Postgres connection helper, used by ingestion, rag, eval, and app.

Same pattern as module 5's db_init.py: env vars with sane local-dev
defaults matching docker-compose.yaml.
"""

import os
from datetime import datetime

import psycopg
from pgvector.psycopg import register_vector

DB_TIMEZONE = datetime.now().astimezone().tzinfo


def get_db_connection() -> psycopg.Connection:
    conn = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "garden_companion"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
    )
    # Registered here, once, so every caller (ingestion assets, rag/, eval/,
    # the Streamlit app) gets automatic list<->vector conversion for free --
    # a plain Python list of floats can go straight into an INSERT/UPDATE
    # against the `embedding vector(1536)` column without manual casting,
    # and SELECTs come back as numpy arrays instead of raw strings.
    register_vector(conn)
    return conn
