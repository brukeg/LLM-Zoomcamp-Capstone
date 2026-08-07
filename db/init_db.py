"""Apply db/schema.sql against the configured Postgres database.

Run once after `docker compose up` (or whenever schema.sql changes), as a
module from the repo root -- not as a bare script, since `from db.connection
import ...` needs the repo root on sys.path:

    uv run python -m db.init_db
"""

from pathlib import Path

from db.connection import get_db_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db() -> list[str]:
    schema_sql = SCHEMA_PATH.read_text()

    # register=False: on a fresh database the `vector` extension doesn't exist
    # yet -- schema.sql (run just below) is what creates it -- so we must not
    # try to register the vector type on this bootstrap connection.
    conn = get_db_connection(register=False)
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
            conn.commit()

            # Read back the actual table list rather than hardcoding it in
            # the print statement below -- a hardcoded list goes stale the
            # next time a table gets added to schema.sql (as just happened
            # with `ground_truth`) and silently prints something untrue.
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


if __name__ == "__main__":
    tables = init_db()
    print(f"Database initialized ({', '.join(tables)}).")
