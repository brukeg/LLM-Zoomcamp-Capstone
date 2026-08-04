"""Per-call cost estimation from token counts, so conversation logging (and
the Aug 7-8 monitoring dashboard) can track spend per answer.

Prices are per 1,000,000 tokens, confirmed against OpenAI's pricing page on
8/2/26. They WILL drift -- if a model is swapped or OpenAI changes pricing,
update this table. Unknown models fall back to $0 with a note rather than
crashing a live chat turn over a missing price (better to under-report cost
than to 500 the user's question).
"""

# (input_per_1m, output_per_1m) in USD.
MODEL_PRICING = {
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "text-embedding-3-small": (0.02, 0.0),
}

_PER_MILLION = 1_000_000


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost for one call. Returns 0.0 for an unknown model (the caller's
    logging still succeeds; the price table just needs updating).
    """
    if model not in MODEL_PRICING:
        return 0.0
    input_price, output_price = MODEL_PRICING[model]
    return (prompt_tokens * input_price + completion_tokens * output_price) / _PER_MILLION
