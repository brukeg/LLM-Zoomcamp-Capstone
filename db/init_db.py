"""Apply db/schema.sql against the configured Postgres database.

Run once after `docker compose up` (or whenever schema.sql changes), as a
module from the repo root -- not as a bare script, since `from db.connection
import ...` needs the repo root on sys.path:

    uv run python -m db.init_db
"""

from pathlib import Path

from db.connection import get_db_connection

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db() -> None:
    schema_sql = SCHEMA_PATH.read_text()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized (documents, sections, chunks, conversations, feedback).")
