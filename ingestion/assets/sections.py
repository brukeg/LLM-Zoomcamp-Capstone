"""Split each document's raw_text into sections -- the pre-chunk unit
ground truth gets generated from (see docs/decisions.md).

Splitting logic (split_book_sections / split_factsheet_sections) was
validated against real fetched content and the actual chapter-heading
patterns confirmed from the live database on 7/31, not guessed blind --
see ingestion/parsing.py docstrings for specifics.
"""

import dagster as dg

from ingestion.assets.fetch import extension_factsheets, gutenberg_books
from ingestion.parsing import split_book_sections, split_factsheet_sections
from ingestion.resources import PostgresResource

DELETE_SECTIONS_SQL = "DELETE FROM sections WHERE document_id = %s"

INSERT_SECTION_SQL = """
    INSERT INTO sections (id, document_id, section_title, section_order, raw_text)
    VALUES (%s, %s, %s, %s, %s)
"""


@dg.asset(group_name="ingestion", deps=[gutenberg_books, extension_factsheets])
def sections(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Read documents.raw_text, split into sections per source type, land
    in the `sections` table. Re-splits from scratch each run (delete then
    insert per document) rather than trying to diff -- simpler, and cheap
    at our volume.
    """
    conn = postgres.get_connection()
    doc_count, section_count, empty_docs = 0, 0, []

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, source_type, title, raw_text FROM documents ORDER BY id")
            documents = cur.fetchall()

            for doc_id, source_type, title, raw_text in documents:
                if not raw_text:
                    empty_docs.append(doc_id)
                    continue

                if source_type == "book":
                    doc_sections = split_book_sections(raw_text)
                else:
                    doc_sections = split_factsheet_sections(raw_text, fallback_title=title)

                cur.execute(DELETE_SECTIONS_SQL, (doc_id,))

                for order, (section_title, body) in enumerate(doc_sections):
                    section_id = f"{doc_id}-s{order:03d}"
                    cur.execute(
                        INSERT_SECTION_SQL,
                        (section_id, doc_id, section_title, order, body),
                    )

                conn.commit()
                context.log.info(f"{doc_id}: {len(doc_sections)} sections")
                doc_count += 1
                section_count += len(doc_sections)
    finally:
        conn.close()

    return dg.MaterializeResult(
        metadata={
            "documents_processed": doc_count,
            "sections_created": section_count,
            "empty_documents": ", ".join(empty_docs) if empty_docs else "none",
        }
    )
