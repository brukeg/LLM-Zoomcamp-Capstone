"""Embed every ground-truth question and cache the vector in
ground_truth.question_embedding, so search evaluation (eval/evaluate_search.py)
can do vector/hybrid retrieval without re-embedding ~7,500 questions on every
run.

Idempotent, same as ingestion/assets/embedding.py's chunk pass: only embeds
rows where question_embedding IS NULL, and commits per batch, so a partial
failure (rate limit, network blip) doesn't lose completed work or force a
full redo.

Run as a module from the repo root (needs the repo root on sys.path for the
db/ingestion imports):

    uv run python -m eval.embed_questions
"""

from dotenv import load_dotenv

from db.connection import get_db_connection
from ingestion.embedding import BATCH_SIZE, embed_batch, get_openai_client

UPDATE_QUESTION_EMBEDDING_SQL = "UPDATE ground_truth SET question_embedding = %s WHERE id = %s"


def embed_questions() -> tuple[int, int]:
    """Returns (embedded_this_run, total_pending_at_start)."""
    client = get_openai_client()
    conn = get_db_connection()
    embedded = 0
    total = 0

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, question FROM ground_truth WHERE question_embedding IS NULL ORDER BY id")
            rows = cur.fetchall()
            total = len(rows)

            for i in range(0, total, BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                ids = [r[0] for r in batch]
                texts = [r[1] for r in batch]
                embeddings = embed_batch(client, texts)

                for gt_id, embedding in zip(ids, embeddings):
                    cur.execute(UPDATE_QUESTION_EMBEDDING_SQL, (embedding, gt_id))
                conn.commit()

                embedded += len(batch)
                print(f"Embedded {embedded}/{total} questions")
    finally:
        conn.close()

    return embedded, total


if __name__ == "__main__":
    load_dotenv()
    embedded, total = embed_questions()
    if total == 0:
        print("Nothing to do -- every question already has an embedding.")
    else:
        print(f"Done: embedded {embedded} questions.")
