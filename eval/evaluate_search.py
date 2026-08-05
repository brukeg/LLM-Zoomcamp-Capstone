"""Search evaluation: Hit Rate and MRR for all 3 chunking strategies x
{keyword, vector, hybrid} = 9 combinations, scored against the LLM-generated
ground truth.

A "hit" for a question = at least one of the top-K retrieved chunks comes
from that question's own source section (section_id match -- see
docs/decisions.md for why section, not exact chunk/document id). MRR uses
the rank of the FIRST such matching chunk.

Prerequisites: the full ingestion pipeline has run (chunks + embeddings),
ground truth is generated, and eval/embed_questions.py has populated
ground_truth.question_embedding. Run as a module from the repo root:

    uv run python -m eval.evaluate_search
"""

import json
import time
from pathlib import Path

from dotenv import load_dotenv

from db.connection import get_db_connection
from rag.search import DEFAULT_TOP_K, hybrid_search, keyword_search, vector_search

STRATEGIES = ["fixed", "structure", "recursive"]
METHODS = ["keyword", "vector", "hybrid"]

# The dashboard's chunking-strategy comparison panel reads this file, so the
# chart survives without re-running the ~90k-query evaluation. Written on
# every run below, so it stays in sync if the eval is ever re-run.
ARTIFACT_PATH = Path(__file__).parent / "search_eval_results.json"


def _reciprocal_rank(retrieved_section_ids: list[str], target_section_id: str) -> float:
    """1 / (1-based rank of the first retrieved chunk from the target
    section), or 0.0 if none of the retrieved chunks match.
    """
    for index, section_id in enumerate(retrieved_section_ids):
        if section_id == target_section_id:
            return 1.0 / (index + 1)
    return 0.0


def _search(cur, method: str, question: str, embedding, strategy: str, top_k: int) -> list[str]:
    if method == "keyword":
        return keyword_search(cur, question, strategy, top_k)
    if method == "vector":
        return vector_search(cur, embedding, strategy, top_k)
    return hybrid_search(cur, question, embedding, strategy, top_k)


def evaluate(top_k: int = DEFAULT_TOP_K) -> list[dict]:
    conn = get_db_connection()
    results = []

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT section_id, question, question_embedding "
                "FROM ground_truth WHERE question_embedding IS NOT NULL"
            )
            ground_truth = cur.fetchall()

        total = len(ground_truth)
        if total == 0:
            raise SystemExit(
                "No embedded ground-truth questions found. "
                "Run `uv run python -m eval.embed_questions` first."
            )

        print(f"Evaluating {len(STRATEGIES) * len(METHODS)} combinations "
              f"against {total} questions (top_k={top_k})...\n")

        with conn.cursor() as cur:
            for strategy in STRATEGIES:
                for method in METHODS:
                    started = time.time()
                    hits = 0
                    rr_sum = 0.0

                    for target_section_id, question, embedding in ground_truth:
                        retrieved = _search(cur, method, question, embedding, strategy, top_k)
                        rr = _reciprocal_rank(retrieved, target_section_id)
                        if rr > 0.0:
                            hits += 1
                        rr_sum += rr

                    results.append(
                        {
                            "strategy": strategy,
                            "method": method,
                            "hit_rate": hits / total,
                            "mrr": rr_sum / total,
                            "seconds": time.time() - started,
                        }
                    )
                    r = results[-1]
                    print(f"  {strategy:10s} {method:8s}  "
                          f"hit_rate={r['hit_rate']:.4f}  mrr={r['mrr']:.4f}  "
                          f"({r['seconds']:.0f}s)")
    finally:
        conn.close()

    return results


def print_summary(results: list[dict]) -> None:
    ranked = sorted(results, key=lambda r: (r["mrr"], r["hit_rate"]), reverse=True)

    print("\n" + "=" * 56)
    print("RESULTS  (ranked by MRR, then Hit Rate)")
    print("=" * 56)
    print(f"{'strategy':12s} {'method':10s} {'hit_rate':>10s} {'mrr':>10s}")
    print("-" * 56)
    for r in ranked:
        print(f"{r['strategy']:12s} {r['method']:10s} {r['hit_rate']:>10.4f} {r['mrr']:>10.4f}")

    winner = ranked[0]
    print("-" * 56)
    print(f"WINNER: {winner['strategy']} + {winner['method']}  "
          f"(hit_rate={winner['hit_rate']:.4f}, mrr={winner['mrr']:.4f})")


def write_artifact(results: list[dict], top_k: int, n_questions: int) -> None:
    payload = {
        "top_k": top_k,
        "n_questions": n_questions,
        "results": [
            {"strategy": r["strategy"], "method": r["method"],
             "hit_rate": round(r["hit_rate"], 4), "mrr": round(r["mrr"], 4)}
            for r in results
        ],
    }
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    load_dotenv()

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ground_truth WHERE question_embedding IS NOT NULL")
            n_questions = cur.fetchone()[0]
    finally:
        conn.close()

    results = evaluate()
    print_summary(results)
    write_artifact(results, DEFAULT_TOP_K, n_questions)
    print(f"\nResults written to {ARTIFACT_PATH.name}")
