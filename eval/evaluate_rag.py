"""Offline RAG evaluation: generate answers for a reproducible sample of the
ground truth and judge each with an LLM-as-judge (relevance).

Runs as an A/B across the answer-prompt variants in rag.pipeline.PROMPT_VARIANTS
-- so the "LLM evaluation" covers multiple approaches and picks the best, not
just a single prompt. Same fixed-seed sample for every variant, so the
comparison is apples-to-apples. Whichever prompt wins is the one set as the
pipeline default.

Writes eval/rag_eval_results.json with per-variant summaries + every
per-question answer and judgment, so failures are readable and the README
writeup has raw evidence.

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
from openai import APITimeoutError, RateLimitError

from db.connection import get_db_connection
from ingestion.embedding import get_openai_client
from rag.judge import RELEVANCE_CLASSES, UNPARSEABLE, judge_relevance
from rag.pipeline import PROMPT_VARIANTS, rag

SAMPLE_SIZE = 150

# Fixed so every config is judged on exactly the same questions -- the A/B is
# only fair if the inputs are identical.
RANDOM_SEED = 42

# What this run compares. The prompt A/B (v1_grounded vs v2_direct) already
# picked v2_direct as the better prompt. This now ablates QUERY REWRITING on
# that winning prompt: comparing the rewrite-on run to the earlier no-rewrite
# baseline suggested rewriting hurt relevance, so we measure it head-to-head,
# same session, same sample, to decide the production default with data. Set
# this list to whatever pair of configs you want to compare.
EVAL_CONFIGS = [
    {"label": "v2_rewrite_on", "system_prompt": PROMPT_VARIANTS["v2_direct"], "rewrite": True},
    {"label": "v2_rewrite_off", "system_prompt": PROMPT_VARIANTS["v2_direct"], "rewrite": False},
]

# 4 concurrent workers keeps this fast without straining the org's TPM limit.
# (The stalls during development turned out to be an exhausted credit balance
# returning 429s, not a real rate-limit ceiling -- see the insufficient_quota
# guard in _answer_and_judge.) The retry below still handles genuine
# transient rate limits.
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


def _answer_and_judge(client, item: dict, system_prompt: str, rewrite: bool) -> dict:
    """Generate an answer with the given prompt + rewrite setting and judge
    it, retrying the whole unit on rate-limit errors with growing backoff
    (simpler than per-call retry, and re-running a cheap embed/rewrite on
    retry is negligible).
    """
    last_error = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            result = rag(item["question"], system_prompt=system_prompt, rewrite=rewrite)
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
        except (RateLimitError, APITimeoutError) as exc:
            # insufficient_quota comes back as a 429 too, but it is NOT
            # transient -- retrying an out-of-credits account just stalls the
            # whole run in backoff (this is exactly what masqueraded as a
            # rate-limit "hang" on 8/5). Fail fast with the real message.
            if getattr(exc, "code", None) == "insufficient_quota":
                raise
            last_error = exc
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
    raise last_error


def _summarize(label: str, records: list[dict]) -> dict:
    total = len(records)
    counts = Counter(r["relevance"] for r in records)
    return {
        "config": label,
        "sample_size": total,
        "counts": {cls: counts.get(cls, 0) for cls in sorted(RELEVANCE_CLASSES) + [UNPARSEABLE]},
        "bad_rate": counts.get("NON_RELEVANT", 0) / total if total else 0.0,
        "relevant_rate": counts.get("RELEVANT", 0) / total if total else 0.0,
        "avg_answer_tokens": round(sum(r["answer_tokens"] for r in records) / total, 1) if total else 0,
        "avg_latency_seconds": round(sum(r["latency_seconds"] for r in records) / total, 2) if total else 0,
    }


def evaluate_config(client, sample: list[dict], label: str, system_prompt: str, rewrite: bool) -> tuple[list[dict], dict]:
    total = len(sample)
    print(f"\n[{label}] evaluating {total} questions...", flush=True)
    records = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(_answer_and_judge, client, item, system_prompt, rewrite) for item in sample]
        for i, future in enumerate(as_completed(futures), start=1):
            records.append(future.result())
            # flush=True so progress actually shows in real time rather than
            # buffering until the end.
            if i % 25 == 0:
                print(f"  [{label}] judged {i}/{total}", flush=True)
    return records, _summarize(label, records)


def run_ab() -> dict:
    client = get_openai_client()
    sample = _sample_ground_truth()
    print(f"A/B over {len(EVAL_CONFIGS)} configs, "
          f"{len(sample)} questions each (seed={RANDOM_SEED}).")

    per_config = {}
    for cfg in EVAL_CONFIGS:
        records, summary = evaluate_config(
            client, sample, cfg["label"], cfg["system_prompt"], cfg["rewrite"]
        )
        per_config[cfg["label"]] = {"summary": summary, "records": records}
    return per_config


def print_comparison(per_config: dict) -> str:
    summaries = [c["summary"] for c in per_config.values()]
    # Winner: highest relevant rate, tie-broken by lowest bad rate.
    winner = max(summaries, key=lambda s: (s["relevant_rate"], -s["bad_rate"]))

    print("\n" + "=" * 60)
    print("RAG EVALUATION A/B  (relevance by prompt variant)")
    print("=" * 60)
    print(f"{'config':14s} {'relevant':>10s} {'partly':>9s} {'bad':>7s} {'avg tok':>9s}")
    print("-" * 60)
    for s in summaries:
        print(f"{s['config']:14s} {s['relevant_rate']:>9.1%} "
              f"{s['counts']['PARTLY_RELEVANT'] / s['sample_size']:>8.1%} "
              f"{s['bad_rate']:>6.1%} {s['avg_answer_tokens']:>9.0f}")
    print("-" * 60)
    print(f"WINNER: {winner['config']}  "
          f"(relevant={winner['relevant_rate']:.1%}, bad={winner['bad_rate']:.1%})")
    return winner["config"]


if __name__ == "__main__":
    load_dotenv()
    per_config = run_ab()
    winner = print_comparison(per_config)

    payload = {
        "seed": RANDOM_SEED,
        "sample_size": SAMPLE_SIZE,
        "winner": winner,
        "configs": {label: data["summary"] for label, data in per_config.items()},
        "records": {label: data["records"] for label, data in per_config.items()},
    }
    ARTIFACT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"\nFull per-question results written to {ARTIFACT_PATH.name}")
