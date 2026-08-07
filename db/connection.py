"""Shared Postgres connection helper, used by ingestion, rag, eval, and app.

Same pattern as module 5's db_init.py: env vars with sane local-dev
defaults matching docker-compose.yaml.
"""

import os
from datetime import datetime

import psycopg
from pgvector.psycopg import register_vector

DB_TIMEZONE = datetime.now().astimezone().tzinfo


def get_db_connection(register: bool = True) -> psycopg.Connection:
    conn = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.getenv("POSTGRES_DB", "garden_companion"),
        user=os.getenv("POSTGRES_USER", "user"),
        password=os.getenv("POSTGRES_PASSWORD", "password"),
    )
    # register_vector requires the `vector` extension to already exist in the
    # database -- but that extension is created BY db/schema.sql, which
    # init_db hasn't run yet on a brand-new database. So init_db connects with
    # register=False to bootstrap the schema (and the extension) first; every
    # other caller uses the default register=True to get automatic
    # list<->vector conversion (a plain list of floats goes straight into the
    # embedding column, and SELECTs come back as numpy arrays). Caught by the
    # from-zero reproducibility check -- invisible until the DB is truly empty.
    if register:
        register_vector(conn)
    return conn
