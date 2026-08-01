"""Dagster entry point.

    DAGSTER_HOME=$(pwd)/.dagster_home uv run dagster dev -f ingestion/definitions.py

(DAGSTER_HOME must be absolute -- see .env.example) opens the UI at
http://localhost:3000.

Easiest path: open the Jobs tab, select `full_ingestion_pipeline`, and hit
Launch Run -- it materializes every asset below in the correct dependency
order in one go (fetch -> sections -> all three chunking strategies ->
embeddings), so there's no more manually re-selecting asset groups each
session.

To materialize a subset by hand instead (e.g. re-running just one strategy
after a code change), the dependency order is:
1. `gutenberg_books` and `extension_factsheets` (independent of each other).
2. `sections`, once those land.
3. `fixed_chunks`, `structure_chunks`, `recursive_chunks` (independent of
   each other, all three depend only on `sections`).
4. `chunk_embeddings`, once at least one chunking strategy has run --
   embeds every chunk across all three strategies in one pass, and skips
   any chunk that already has an embedding, so it's safe to re-run after a
   partial failure or after only one strategy changed.
"""

import dagster as dg
from dotenv import load_dotenv

from ingestion.assets.chunking import fixed_chunks, recursive_chunks, structure_chunks
from ingestion.assets.embedding import chunk_embeddings
from ingestion.assets.fetch import extension_factsheets, gutenberg_books
from ingestion.assets.sections import sections
from ingestion.resources import PostgresResource

# Load once, here, at the actual Dagster entry point -- nothing else in the
# process does this automatically. Postgres connections have worked without
# it so far only by coincidence (get_db_connection()'s hardcoded fallback
# defaults happen to match docker-compose.yaml's values), but
# OPENAI_API_KEY has no safe fallback to fall back to: without this,
# chunk_embeddings would call the OpenAI client with api_key=None. Safe to
# do after the asset imports above -- none of them read env vars at import
# time, only when their asset function actually runs.
load_dotenv()

all_assets = [
    gutenberg_books,
    extension_factsheets,
    sections,
    fixed_chunks,
    structure_chunks,
    recursive_chunks,
    chunk_embeddings,
]

full_ingestion_pipeline = dg.define_asset_job(
    name="full_ingestion_pipeline",
    selection=dg.AssetSelection.all(),
)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[full_ingestion_pipeline],
    resources={"postgres": PostgresResource()},
)
