"""Dagster entry point.

    DAGSTER_HOME=$(pwd)/.dagster_home uv run dagster dev -f ingestion/definitions.py

(DAGSTER_HOME must be absolute -- see .env.example) opens the UI at
http://localhost:3000. Materialize in dependency order:
1. `gutenberg_books` and `extension_factsheets` (select both and hit
   Materialize -- Dagster runs them in parallel since they're independent).
2. `sections`, once those land.
3. `fixed_chunks`, `structure_chunks`, `recursive_chunks` -- independent of
   each other, all three depend only on `sections`, select all three and
   materialize together.
"""

import dagster as dg

from ingestion.assets.chunking import fixed_chunks, recursive_chunks, structure_chunks
from ingestion.assets.fetch import extension_factsheets, gutenberg_books
from ingestion.assets.sections import sections
from ingestion.resources import PostgresResource

defs = dg.Definitions(
    assets=[
        gutenberg_books,
        extension_factsheets,
        sections,
        fixed_chunks,
        structure_chunks,
        recursive_chunks,
    ],
    resources={"postgres": PostgresResource()},
)
