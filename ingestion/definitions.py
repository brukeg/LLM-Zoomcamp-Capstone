"""Dagster entry point.

    DAGSTER_HOME=$(pwd)/.dagster_home uv run dagster dev -f ingestion/definitions.py

(DAGSTER_HOME must be absolute -- see .env.example) opens the UI at
http://localhost:3000.

Two jobs, deliberately separate (Jobs tab, select one, Launch Run):

- `full_ingestion_pipeline` -- fetch -> sections -> all three chunking
  strategies -> embeddings. Everything in the "ingestion" group. Safe and
  cheap to re-run whenever source code or data changes.
- `generate_ground_truth` -- the "evaluation" group's one asset. Kept OUT
  of full_ingestion_pipeline on purpose: it makes real (if small) LLM calls
  per section, so it shouldn't silently re-run and re-pay every time the
  ingestion pipeline does. Run it deliberately, after sections looks right,
  and don't expect to re-run it often.

To materialize a subset by hand instead of using a job, the dependency
order is:
1. `gutenberg_books` and `extension_factsheets` (independent of each other).
2. `sections`, once those land.
3. `fixed_chunks`, `structure_chunks`, `recursive_chunks` (independent of
   each other, all three depend only on `sections`).
4. `chunk_embeddings`, once at least one chunking strategy has run --
   embeds every chunk across all three strategies in one pass, and skips
   any chunk that already has an embedding, so it's safe to re-run after a
   partial failure or after only one strategy changed.
5. `ground_truth`, once `sections` looks right -- independent of chunking/
   embeddings, only depends on `sections`.
"""

import dagster as dg
from dotenv import load_dotenv

from ingestion.assets.chunking import fixed_chunks, recursive_chunks, structure_chunks
from ingestion.assets.embedding import chunk_embeddings
from ingestion.assets.fetch import extension_factsheets, gutenberg_books
from ingestion.assets.ground_truth import ground_truth
from ingestion.assets.sections import sections
from ingestion.resources import PostgresResource

# Load once, here, at the actual Dagster entry point -- nothing else in the
# process does this automatically. Postgres connections have worked without
# it so far only by coincidence (get_db_connection()'s hardcoded fallback
# defaults happen to match docker-compose.yaml's values), but
# OPENAI_API_KEY has no safe fallback to fall back to: without this,
# chunk_embeddings and ground_truth would call the OpenAI client with
# api_key=None. Safe to do after the asset imports above -- none of them
# read env vars at import time, only when their asset function actually
# runs.
load_dotenv()

all_assets = [
    gutenberg_books,
    extension_factsheets,
    sections,
    fixed_chunks,
    structure_chunks,
    recursive_chunks,
    chunk_embeddings,
    ground_truth,
]

# Scoped to the "ingestion" group explicitly, NOT AssetSelection.all() --
# that would silently sweep in `ground_truth` (a different group) and
# re-trigger paid LLM calls on every routine ingestion re-run.
full_ingestion_pipeline = dg.define_asset_job(
    name="full_ingestion_pipeline",
    selection=dg.AssetSelection.groups("ingestion"),
)

generate_ground_truth = dg.define_asset_job(
    name="generate_ground_truth",
    selection=dg.AssetSelection.groups("evaluation"),
)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[full_ingestion_pipeline, generate_ground_truth],
    resources={"postgres": PostgresResource()},
)
