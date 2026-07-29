"""Shared Postgres connection helper, used by ingestion, rag, eval, and app.

Same pattern as module 5's db_init.py: env vars with sane local-dev
defaults matching docker-compose.yaml.
"""

import os
from datetime import datetime

import psycopg

DB_TIMEZONE = datetime.now().astimezone().tzinfo


def get_db_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "garden_companion"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
    )
