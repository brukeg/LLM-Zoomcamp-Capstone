"""Three chunking strategies over the `sections` table, each writing to the
`chunks` table with its own `strategy` value (see docs/decisions.md and
ingestion/chunking.py for what each one does and why they're scoped to a
single section's text rather than the whole document).
"""

import dagster as dg

from ingestion.assets.sections import sections
from ingestion.chunking import chunk_fixed_size, chunk_recursive, chunk_structure_aware, count_tokens
from ingestion.resources import PostgresResource

DELETE_CHUNKS_SQL = "DELETE FROM chunks WHERE strategy = %s"

INSERT_CHUNK_SQL = """
    INSERT INTO chunks (document_id, section_id, strategy, chunk_index, text, token_count)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


def _run_strategy(
    context: dg.AssetExecutionContext,
    postgres: PostgresResource,
    strategy_name: str,
    split_fn,
) -> dg.MaterializeResult:
    """Shared runner: delete this strategy's existing chunks, re-split every
    section's raw_text with split_fn, reinsert. Rebuilds from scratch each
    run rather than diffing -- same reasoning as sections.py, cheap at our
    volume.
    """
    conn = postgres.get_connection()
    section_count, chunk_count = 0, 0

    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_CHUNKS_SQL, (strategy_name,))

            cur.execute(
                "SELECT id, document_id, raw_text FROM sections ORDER BY document_id, section_order"
            )
            all_sections = cur.fetchall()

            for section_id, document_id, raw_text in all_sections:
                pieces = split_fn(raw_text)
                for chunk_index, piece in enumerate(pieces):
                    cur.execute(
                        INSERT_CHUNK_SQL,
                        (document_id, section_id, strategy_name, chunk_index, piece, count_tokens(piece)),
                    )
                    chunk_count += 1
                section_count += 1

            conn.commit()
    finally:
        conn.close()

    context.log.info(f"{strategy_name}: {section_count} sections -> {chunk_count} chunks")
    return dg.MaterializeResult(
        metadata={
            "strategy": strategy_name,
            "sections_processed": section_count,
            "chunks_created": chunk_count,
        }
    )


@dg.asset(group_name="ingestion", deps=[sections])
def fixed_chunks(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Naive baseline: tiktoken sliding token-count window with overlap."""
    return _run_strategy(context, postgres, "fixed", chunk_fixed_size)


@dg.asset(group_name="ingestion", deps=[sections])
def structure_chunks(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Packs each section's own paragraphs up to a target size; keeps a
    section whole if it's already chunk-sized.
    """
    return _run_strategy(context, postgres, "structure", chunk_structure_aware)


@dg.asset(group_name="ingestion", deps=[sections])
def recursive_chunks(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """langchain's RecursiveCharacterTextSplitter."""
    return _run_strategy(context, postgres, "recursive", chunk_recursive)
