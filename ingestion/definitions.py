"""Dagster entry point.

    uv run dagster dev -f ingestion/definitions.py

opens the UI at http://localhost:3000 where you can materialize
`gutenberg_books` and `extension_factsheets` individually and watch logs.
"""

import dagster as dg

from ingestion.assets.fetch import extension_factsheets, gutenberg_books
from ingestion.resources import PostgresResource

defs = dg.Definitions(
    assets=[gutenberg_books, extension_factsheets],
    resources={"postgres": PostgresResource()},
)
