"""Retrieval over the chunks table -- three methods, each scoped to a single
chunking strategy so search evaluation (eval/evaluate_search.py) can compare
all 3 strategies x {keyword, vector, hybrid}.

Every function returns a list of section_ids, one per retrieved chunk, in
rank order (NOT deduped to distinct sections). This keeps "top k" meaning
"k retrieved chunks" identically across all three methods, so Hit Rate@k /
MRR@k stay comparable -- a hit is just "did any of the k retrieved chunks
come from the ground-truth question's own section" (see docs/decisions.md
for why correctness is measured by section, not exact chunk/document id).

Postgres does all the heavy lifting: `search_vector` (a GENERATED tsvector
column) for keyword, the HNSW index on `embedding` for vector. Hybrid fuses
the two rankings in Python via Reciprocal Rank Fusion.
"""

DEFAULT_TOP_K = 5

# Reciprocal Rank Fusion constant. 60 is the value from the original RRF
# paper (Cormack et al. 2009) and the de facto standard default -- large
# enough that top-rank differences don't dominate, small enough that deep
# ranks still contribute little. Not tuned; picking the standard default on
# purpose rather than burning time optimizing it (see the Aug 3 estimate
# discussion -- hybrid fusion tuning is the easiest place to scope-creep).
RRF_K = 60

# How many candidates to pull from each ranker before fusing. Bigger than
# DEFAULT_TOP_K so a chunk ranked, say, 8th by keyword but 2nd by vector can
# still surface in the fused top 5. 60 is plenty at our corpus size.
HYBRID_CANDIDATE_POOL = 60


def keyword_search(cur, query_text: str, strategy: str, limit: int = DEFAULT_TOP_K) -> list[str]:
    """Full-text keyword search via the generated tsvector column.

    websearch_to_tsquery (not plainto_/to_tsquery) because it never raises
    on arbitrary user text -- punctuation, quotes, stray operators in a
    natural-language question all get handled gracefully instead of throwing.
    A question whose terms are all stopwords yields an empty tsquery and
    therefore no rows; that's a legitimate miss, not an error.
    """
    cur.execute(
        """
        SELECT section_id
        FROM chunks
        WHERE strategy = %s
          AND search_vector @@ websearch_to_tsquery('english', %s)
        ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', %s)) DESC
        LIMIT %s
        """,
        (strategy, query_text, query_text, limit),
    )
    return [row[0] for row in cur.fetchall()]


def vector_search(cur, query_embedding, strategy: str, limit: int = DEFAULT_TOP_K) -> list[str]:
    """Cosine-distance vector search via the HNSW index (`<=>` operator,
    which matches the index's vector_cosine_ops). `query_embedding` is
    whatever pgvector's psycopg adapter accepts -- a numpy array read back
    from ground_truth.question_embedding works directly.
    """
    cur.execute(
        """
        SELECT section_id
        FROM chunks
        WHERE strategy = %s
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (strategy, query_embedding, limit),
    )
    return [row[0] for row in cur.fetchall()]


def _keyword_candidates(cur, query_text: str, strategy: str, pool: int) -> list[tuple[int, str]]:
    cur.execute(
        """
        SELECT id, section_id
        FROM chunks
        WHERE strategy = %s
          AND search_vector @@ websearch_to_tsquery('english', %s)
        ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('english', %s)) DESC
        LIMIT %s
        """,
        (strategy, query_text, query_text, pool),
    )
    return cur.fetchall()


def _vector_candidates(cur, query_embedding, strategy: str, pool: int) -> list[tuple[int, str]]:
    cur.execute(
        """
        SELECT id, section_id
        FROM chunks
        WHERE strategy = %s
        ORDER BY embedding <=> %s
        LIMIT %s
        """,
        (strategy, query_embedding, pool),
    )
    return cur.fetchall()


def hybrid_search(
    cur,
    query_text: str,
    query_embedding,
    strategy: str,
    limit: int = DEFAULT_TOP_K,
    pool: int = HYBRID_CANDIDATE_POOL,
    rrf_k: int = RRF_K,
) -> list[str]:
    """Reciprocal Rank Fusion of keyword + vector rankings, returning
    section_ids in fused order (what search evaluation needs).

    Thin wrapper over rrf_fuse() -- see that function for the fusion math.
    Both this (eval) and the RAG pipeline's retrieval share rrf_fuse so
    there's exactly one implementation of the fusion; this one just maps the
    fused chunk_ids back to their section_ids.
    """
    keyword = _keyword_candidates(cur, query_text, strategy, pool)
    vector = _vector_candidates(cur, query_embedding, strategy, pool)

    section_of = {chunk_id: section_id for chunk_id, section_id in keyword + vector}
    ranked_chunk_ids = rrf_fuse(keyword, vector, limit, rrf_k)
    return [section_of[chunk_id] for chunk_id in ranked_chunk_ids]


def rrf_fuse(
    keyword_candidates: list[tuple],
    vector_candidates: list[tuple],
    limit: int,
    rrf_k: int = RRF_K,
) -> list[int]:
    """Reciprocal Rank Fusion over two ranked candidate lists, returning the
    top `limit` chunk_ids in fused order.

    Each list is [(chunk_id, ...), ...] in rank order -- only the first
    element (chunk_id) is used, so both the eval candidates (chunk_id,
    section_id) and any richer row shape work. A chunk's fused score is the
    sum over both rankers of 1 / (rrf_k + rank), rank 1-based; a chunk in
    both lists accumulates from each, which is what lets hybrid beat either
    ranker alone.
    """
    scores: dict[int, float] = {}
    for rank, candidate in enumerate(keyword_candidates):
        chunk_id = candidate[0]
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
    for rank, candidate in enumerate(vector_candidates):
        chunk_id = candidate[0]
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)

    return sorted(scores, key=lambda cid: scores[cid], reverse=True)[:limit]
