"""Embed every chunk's text via OpenAI's API and load into pgvector.

FTS doesn't need a separate load step -- `chunks.search_vector` is a
GENERATED ALWAYS AS (to_tsvector(...)) STORED column, computed automatically
whenever a chunk row is inserted (see db/schema.sql). This asset only
handles the vector half.
"""

import dagster as dg

from ingestion.assets.chunking import fixed_chunks, recursive_chunks, structure_chunks
from ingestion.embedding import BATCH_SIZE, embed_batch, get_openai_client
from ingestion.resources import PostgresResource

UPDATE_EMBEDDING_SQL = "UPDATE chunks SET embedding = %s WHERE id = %s"


@dg.asset(group_name="ingestion", deps=[fixed_chunks, structure_chunks, recursive_chunks])
def chunk_embeddings(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Embeds every chunk across all three strategies in one pass -- search
    evaluation (Aug 3) needs vector search against all of them, so there's
    no reason to split this asset by strategy the way chunking is split.

    Only embeds chunks that don't already have one (`embedding IS NULL`),
    so re-running after a partial failure, or after a fresh chunking run
    that only touched one strategy, doesn't re-pay for chunks already
    embedded. Commits per batch rather than once at the end, so a failure
    partway through (rate limit, network blip) doesn't lose completed work.
    """
    client = get_openai_client()
    conn = postgres.get_connection()
    embedded_count = 0
    total = 0

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id")
            rows = cur.fetchall()
            total = len(rows)

            for i in range(0, total, BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                ids = [r[0] for r in batch]
                texts = [r[1] for r in batch]
                embeddings = embed_batch(client, texts)

                for chunk_id, embedding in zip(ids, embeddings):
                    cur.execute(UPDATE_EMBEDDING_SQL, (embedding, chunk_id))
                conn.commit()

                embedded_count += len(batch)
                context.log.info(f"Embedded {embedded_count}/{total} chunks")
    finally:
        conn.close()

    return dg.MaterializeResult(metadata={"chunks_embedded": embedded_count, "pending_at_start": total})
