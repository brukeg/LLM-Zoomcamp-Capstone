"""OpenAI embedding calls for chunk text (see docs/decisions.md for why
OpenAI's API instead of sentence-transformers). Kept separate from the
Dagster asset in ingestion/assets/embedding.py the same way parsing.py and
chunking.py are separate from their asset wrappers -- plain functions here,
Dagster/Postgres plumbing there.
"""

import os

from openai import OpenAI

# Matches db/schema.sql's `embedding vector(1536)` column -- text-embedding-3-small
# outputs 1536 dimensions at its default setting.
EMBEDDING_MODEL = "text-embedding-3-small"

# One API call per batch instead of one call per chunk -- matters at our
# volume (~20k chunks across three strategies): ~200 calls instead of
# ~20,000. Well under OpenAI's per-request limits at this size.
BATCH_SIZE = 100


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts in one API call.

    Defensively sorts the response by each item's own `.index` before
    returning, rather than assuming response order matches input order --
    cheap insurance either way, and correct regardless of whether that
    ordering guarantee actually holds.
    """
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]
