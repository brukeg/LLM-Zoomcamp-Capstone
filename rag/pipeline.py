"""Core RAG pipeline on the winning search config (recursive chunks +
hybrid retrieval -- see docs/decisions.md).

retrieve() -> build_messages() -> LLM. rag() ties them together and returns
a structured result (answer + the passages used + token usage + latency),
so the Aug 6 Streamlit app can log conversations and cost/latency/tokens
without this function having to change.

Quick manual test from the repo root:

    uv run python -m rag.pipeline "How often should I water tomato seedlings?"
"""

import time

import numpy as np

from db.connection import get_db_connection
from ingestion.embedding import embed_batch, get_openai_client
from rag.search import (
    DEFAULT_TOP_K,
    HYBRID_CANDIDATE_POOL,
    _keyword_candidates,
    _vector_candidates,
    rrf_fuse,
)

# recursive + hybrid won the Aug 3 search evaluation. These are the defaults
# the whole pipeline is built on; overridable per-call mainly so Aug 5's RAG
# evaluation can compare against alternatives if needed.
DEFAULT_STRATEGY = "recursive"

# gpt-5.6-luna: same cheap model as question generation. RAG answers are
# interactive and low-volume (unlike the ~7,500 one-shot ground-truth
# calls), so cost isn't the constraint here -- but luna is perfectly
# capable of a grounded, factual gardening answer when the context is handed
# to it. If Aug 5's LLM-as-judge evaluation shows the answer quality is
# weak, bumping this to gpt-5.6-terra (the balanced tier) is the first
# lever, no other code change needed.
ANSWER_MODEL = "gpt-5.6-luna"

_FETCH_CHUNKS_SQL = """
    SELECT c.id, c.text, c.document_id, c.section_id, d.title, d.source_type, s.section_title
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    LEFT JOIN sections s ON c.section_id = s.id
    WHERE c.id = ANY(%s)
"""

_SYSTEM_PROMPT = (
    "You are Garden Companion, a practical gardening assistant. Answer the "
    "gardener's question using ONLY the numbered context passages provided, "
    "which come from public-domain gardening books and Clemson Cooperative "
    "Extension fact sheets. If the passages don't contain enough to answer, "
    "say so plainly instead of guessing or using outside knowledge. Cite the "
    "passages you rely on with their bracketed numbers, like [1] or [2]. Keep "
    "answers practical, direct, and grounded in what the passages actually say."
)


def retrieve(cur, question: str, question_embedding, strategy: str = DEFAULT_STRATEGY,
             top_k: int = DEFAULT_TOP_K, pool: int = HYBRID_CANDIDATE_POOL) -> list[dict]:
    """Hybrid (RRF) retrieval returning the top_k chunks with their text and
    citation metadata, in fused rank order.

    Shares the exact fusion path with search evaluation (rag.search.rrf_fuse
    over the same candidate helpers), then does one extra query to pull full
    chunk text + document title for just the winning chunk_ids -- cheaper
    than joining text into every candidate row up front.
    """
    keyword = _keyword_candidates(cur, question, strategy, pool)
    vector = _vector_candidates(cur, question_embedding, strategy, pool)
    ranked_chunk_ids = rrf_fuse(keyword, vector, top_k)
    if not ranked_chunk_ids:
        return []

    cur.execute(_FETCH_CHUNKS_SQL, (ranked_chunk_ids,))
    by_id = {
        row[0]: {
            "chunk_id": row[0],
            "text": row[1],
            "document_id": row[2],
            "section_id": row[3],
            "document_title": row[4],
            "source_type": row[5],
            "section_title": row[6],
        }
        for row in cur.fetchall()
    }
    # ANY() doesn't preserve order; restore the fused ranking.
    return [by_id[cid] for cid in ranked_chunk_ids if cid in by_id]


def build_messages(question: str, chunks: list[dict]) -> list[dict]:
    """Assemble the chat messages: system instruction + a user turn holding
    the numbered context passages and the question. Passage numbers ([1],
    [2], ...) match the citation scheme the system prompt asks for.
    """
    context_blocks = []
    for i, chunk in enumerate(chunks, start=1):
        section = chunk["section_title"] or "n/a"
        header = f"[{i}] (Source: {chunk['document_title']} — {section})"
        context_blocks.append(f"{header}\n{chunk['text']}")
    context = "\n\n".join(context_blocks)

    user_content = f"Question: {question}\n\nContext passages:\n{context}\n\nAnswer:"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def rag(question: str, strategy: str = DEFAULT_STRATEGY, top_k: int = DEFAULT_TOP_K,
        model: str = ANSWER_MODEL) -> dict:
    """End-to-end: embed the question, hybrid-retrieve, prompt the LLM,
    return a structured result. Opens and closes its own DB connection so
    callers (CLI, Streamlit) don't have to manage one.

    Returns a dict with the answer, the passages used (for citation/display
    and logging), token usage, latency, and the config used -- everything
    the Aug 6 monitoring tables need.
    """
    client = get_openai_client()
    started = time.time()

    # embed_batch returns a plain Python list, which psycopg adapts as a
    # double precision[] -- and there is no `vector <=> double precision[]`
    # operator, so the vector search raises UndefinedFunction. Converting to
    # a float32 numpy array makes pgvector's registered adapter send it as a
    # real `vector` instead. This is the same type search evaluation fed
    # these functions (its question vectors came back from the DB as numpy
    # arrays), which is why eval worked and the first live rag() call did
    # not. Caught on the first real run 8/2/26.
    question_embedding = np.asarray(embed_batch(client, [question])[0], dtype=np.float32)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            chunks = retrieve(cur, question, question_embedding, strategy, top_k)
    finally:
        conn.close()

    if not chunks:
        return {
            "question": question,
            "answer": "I couldn't find anything relevant in the gardening sources for that question.",
            "sources": [],
            "retrieved": [],
            "model": model,
            "instructions": _SYSTEM_PROMPT,
            "prompt": "",  # no LLM call was made on the no-retrieval path
            "search_strategy": strategy,
            "search_method": "hybrid",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "latency_seconds": time.time() - started,
            "strategy": strategy,
        }

    messages = build_messages(question, chunks)
    response = client.chat.completions.create(model=model, messages=messages)
    answer = response.choices[0].message.content

    # De-duplicated source titles, preserving retrieval order, for a compact
    # "Sources:" line in the UI.
    seen, sources = set(), []
    for chunk in chunks:
        title = chunk["document_title"]
        if title not in seen:
            seen.add(title)
            sources.append(title)

    usage = response.usage
    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "retrieved": chunks,
        "model": model,
        # instructions + prompt are the exact system/user text sent to the
        # model, so the conversations table can store what was actually asked
        # (the monitoring schema has columns for both). search_method is
        # constant here -- hybrid is the winning config the pipeline is built
        # on -- but logged explicitly so the dashboard doesn't have to assume.
        "instructions": _SYSTEM_PROMPT,
        "prompt": messages[1]["content"],
        "search_strategy": strategy,
        "search_method": "hybrid",
        "usage": {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
        "latency_seconds": time.time() - started,
        "strategy": strategy,
    }


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    question = " ".join(sys.argv[1:]) or "How do I care for tomato plants?"
    result = rag(question)

    print(f"\nQ: {result['question']}\n")
    print(result["answer"])
    print(f"\nSources: {', '.join(result['sources']) if result['sources'] else 'none'}")
    print(
        f"\n[{result['model']} | {result['usage']['total_tokens']} tokens "
        f"| {result['latency_seconds']:.1f}s | strategy={result['strategy']}]"
    )
