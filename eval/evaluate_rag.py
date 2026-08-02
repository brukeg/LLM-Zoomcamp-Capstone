"""Offline RAG evaluation (Aug 5): generate answers for a reproducible
sample of the ground truth, judge each with an LLM-as-judge, and report the
relevance distribution + "bad rate" (NON_RELEVANT share). If the bad rate is
high, the lever is the system prompt in rag/pipeline.py (or bumping the
answer model); re-run this to compare -- the sample is fixed-seed, so before
/ after are judged on the same questions.

Writes a JSON artifact (eval/rag_eval_results.json) with every per-question
answer + judgment, so failures can actually be read, not just counted, and
so the Aug 9 evaluation writeup has the raw evidence.

Run from the repo root (needs the full pipeline + ground truth in place):

    uv run python -m eval.evaluate_rag
"""

import json
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from openai import RateLimitError

from db.connection import get_db_connection
from ingestion.embedding import get_openai_client
from rag.judge import RELEVANCE_CLASSES, UNPARSEABLE, judge_relevance
from rag.pipeline import rag

SAMPLE_SIZE = 150

# Fixed so the same questions are evaluated every run -- essential for
# comparing prompt iterations fairly (before/after on identical inputs).
RANDOM_SEED = 42

# Each unit of work is two chat calls (answer + judge) plus one embed, so
# 4 concurrent workers keeps sustained token throughput well under the org's
# 200k-tokens/min cap (the same limit that bit ground-truth generation),
# with the retry below as a safety net for the edges.
MAX_WORKERS = 4
MAX_RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_SECONDS = 2.0

ARTIFACT_PATH = Path(__file__).parent / "rag_eval_results.json"


def _sample_ground_truth() -> list[dict]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # ORDER BY id makes the fetch order deterministic before sampling,
            # so the fixed seed actually yields the same sample each run.
            cur.execute("SELECT id, section_id, question FROM ground_truth ORDER BY id")
            rows = cur.fetchall()
    finally:
        conn.close()

    population = [{"gt_id": r[0], "section_id": r[1], "question": r[2]} for r in rows]
    rng = random.Random(RANDOM_SEED)
    return rng.sample(population, min(SAMPLE_SIZE, len(population)))


def _answer_and_judge(client, item: dict) -> dict:
    """Generate an answer and judge it, retrying the whole unit on rate-limit
    errors with growing backoff (the whole unit rather than each call
    separately -- simpler, and re-running a cheap embed on retry is
    negligible).
    """
    last_error = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            result = rag(item["question"])
            judgment = judge_relevance(client, item["question"], result["answer"])
            return {
                "gt_id": item["gt_id"],
                "section_id": item["section_id"],
                "question": item["question"],
                "answer": result["answer"],
                "relevance": judgment["relevance"],
                "explanation": judgment["explanation"],
                "answer_tokens": result["usage"]["total_tokens"],
                "latency_seconds": round(result["latency_seconds"], 2),
                "n_retrieved": len(result["retrieved"]),
            }
        except RateLimitError as exc:
            last_error = exc
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
    raise last_error


def evaluate() -> tuple[list[dict], dict]:
    client = get_openai_client()
    sample = _sample_ground_truth()
    total = len(sample)
    print(f"Evaluating {total} sampled questions (seed={RANDOM_SEED})...\n")

    records = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_answer_and_judge, client, item) for item in sample]
        for i, future in enumerate(as_completed(futures), start=1):
            records.append(future.result())
            if i % 25 == 0:
                print(f"  judged {i}/{total}")

    counts = Counter(r["relevance"] for r in records)
    bad = counts.get("NON_RELEVANT", 0)
    summary = {
        "sample_size": total,
        "seed": RANDOM_SEED,
        "counts": {cls: counts.get(cls, 0) for cls in sorted(RELEVANCE_CLASSES) + [UNPARSEABLE]},
        "bad_rate": bad / total if total else 0.0,
        "relevant_rate": counts.get("RELEVANT", 0) / total if total else 0.0,
        "avg_answer_tokens": round(sum(r["answer_tokens"] for r in records) / total, 1) if total else 0,
        "avg_latency_seconds": round(sum(r["latency_seconds"] for r in records) / total, 2) if total else 0,
    }
    return records, summary


def print_summary(records: list[dict], summary: dict) -> None:
    print("\n" + "=" * 52)
    print(f"RAG EVALUATION  (n={summary['sample_size']}, seed={summary['seed']})")
    print("=" * 52)
    for cls, n in summary["counts"].items():
        pct = 100 * n / summary["sample_size"] if summary["sample_size"] else 0
        print(f"  {cls:16s} {n:4d}  ({pct:5.1f}%)")
    print("-" * 52)
    print(f"  bad rate (NON_RELEVANT): {summary['bad_rate']:.1%}")
    print(f"  relevant rate:           {summary['relevant_rate']:.1%}")
    print(f"  avg answer tokens: {summary['avg_answer_tokens']}  "
          f"avg latency: {summary['avg_latency_seconds']}s")

    failures = [r for r in records if r["relevance"] in ("NON_RELEVANT", UNPARSEABLE)]
    if failures:
        print("\nExample failures (up to 5):")
        for r in failures[:5]:
            print(f"\n  Q: {r['question']}")
            print(f"  A: {r['answer'][:160].strip()}...")
            print(f"  -> {r['relevance']}: {r['explanation']}")


if __name__ == "__main__":
    load_dotenv()
    records, summary = evaluate()
    ARTIFACT_PATH.write_text(json.dumps({"summary": summary, "records": records}, indent=2))
    print_summary(records, summary)
    print(f"\nFull per-question results written to {ARTIFACT_PATH.name}")
