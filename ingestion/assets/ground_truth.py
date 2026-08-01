"""Generate LLM ground-truth questions per section, across both books and
fact sheets (see docs/decisions.md for the section-scoped methodology, and
db/schema.sql for the ground_truth table).

Deliberately its own group ("evaluation"), separate from "ingestion" -- see
ingestion/definitions.py for why: this costs real (if small) money per run
and doesn't need to regenerate every time the ingestion pipeline does.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import dagster as dg

from ingestion.assets.sections import sections
from ingestion.ground_truth import generate_questions, get_openai_client
from ingestion.resources import PostgresResource

DELETE_GROUND_TRUTH_SQL = "DELETE FROM ground_truth"

INSERT_GROUND_TRUTH_SQL = """
    INSERT INTO ground_truth (section_id, document_id, question)
    VALUES (%s, %s, %s)
"""

# One OpenAI call per section, sequentially, means ~1,500 sections *
# ~1.7s/call ~= 42 minutes of pure network wait (confirmed on a real run
# 8/2/26). The openai client is safe for concurrent use from multiple
# threads, so fire off several requests at once instead -- only the DB
# writes stay serialized on the main thread via as_completed(), since
# psycopg connections aren't safe to share across threads.
#
# 10 concurrent workers was tried first and hit the org's rate limit hard
# (200,000 tokens/minute -- a sustained-throughput cap, not a burst
# allowance; 10 workers at ~880 tokens/call demand roughly 5,800 tokens/sec
# against a ~3,333 tokens/sec budget). 4 keeps sustained demand at roughly
# ~2,000 tokens/sec, comfortably under the cap with margin, while still
# cutting the 42-minute sequential runtime by close to 4x. Paired with the
# retry-with-backoff in ingestion/ground_truth.py as a safety net for
# whatever rate-limit contention still happens at the edges.
MAX_WORKERS = 4


@dg.asset(group_name="evaluation", deps=[sections])
def ground_truth(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Rebuilds from scratch each run (delete all, then reinsert) -- same
    reasoning as sections.py and the chunking assets. One failed section
    (a bad LLM response, a transient API error) logs a warning and gets
    skipped rather than failing the whole run, same pattern as fetch.py's
    per-book/per-factsheet error handling.
    """
    client = get_openai_client()
    conn = postgres.get_connection()
    section_count, question_count = 0, 0
    failed_sections: list[str] = []

    def _generate(row):
        section_id, document_id, section_title, raw_text = row
        try:
            return section_id, document_id, generate_questions(client, section_title, raw_text), None
        except Exception as exc:
            return section_id, document_id, [], exc

    try:
        with conn.cursor() as cur:
            cur.execute(DELETE_GROUND_TRUTH_SQL)
            conn.commit()

            cur.execute(
                "SELECT id, document_id, section_title, raw_text "
                "FROM sections ORDER BY document_id, section_order"
            )
            all_sections = cur.fetchall()
            total = len(all_sections)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = [executor.submit(_generate, row) for row in all_sections]

                for future in as_completed(futures):
                    section_id, document_id, questions, exc = future.result()
                    if exc is not None:
                        context.log.warning(f"{section_id}: question generation failed ({exc})")
                        failed_sections.append(section_id)
                        continue

                    for question in questions:
                        cur.execute(INSERT_GROUND_TRUTH_SQL, (section_id, document_id, question))
                    conn.commit()

                    section_count += 1
                    question_count += len(questions)
                    if section_count % 50 == 0:
                        context.log.info(f"{section_count}/{total} sections -> {question_count} questions so far")
    finally:
        conn.close()

    return dg.MaterializeResult(
        metadata={
            "sections_processed": section_count,
            "questions_generated": question_count,
            "sections_failed": ", ".join(failed_sections) if failed_sections else "none",
        }
    )
