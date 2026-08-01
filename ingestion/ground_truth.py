"""LLM-generated ground truth questions, one batch of questions per section
(see docs/decisions.md for why ground truth is generated per section rather
than per whole document, the way the course's FAQ-based approach does it).

Kept separate from the Dagster asset in ingestion/assets/ground_truth.py the
same way parsing.py/chunking.py/embedding.py are separate from their asset
wrappers -- plain functions here, Dagster/Postgres plumbing there.
"""

import json
import os
import time

from openai import OpenAI, RateLimitError

# Confirmed against platform.openai.com/docs/models on 8/2/26: OpenAI's
# current cheapest general-purpose model, built for exactly this kind of
# high-volume, low-complexity workload ($0.20 / $1.20 per 1M input/output
# tokens). Not gpt-4o-mini -- that's the older, more expensive option now.
GENERATION_MODEL = "gpt-5.6-luna"

QUESTIONS_PER_SECTION = 5

# Bounds cost/latency per call. The front portion of a section is
# representative enough for question generation -- we don't need the full
# text (sections can run up to 20,000 characters; see ingestion/parsing.py).
MAX_SECTION_CHARS_FOR_PROMPT = 3000

# Confirmed necessary on a real run 8/2/26: the org's rate limit is 200,000
# tokens/minute, and running enough concurrent requests to exceed that is a
# SUSTAINED throughput problem, not a brief burst -- the openai client's
# default built-in retries got exhausted and those sections were silently
# dropped rather than actually recovering. This explicit retry (growing
# backoff, several attempts) handles that properly instead of relying on
# the default being enough.
MAX_RATE_LIMIT_RETRIES = 5
RATE_LIMIT_BACKOFF_SECONDS = 2.0

_PROMPT_TEMPLATE = """You are generating search-evaluation questions for a home-gardening Q&A system.

Given the section below, write {n} distinct questions that a home gardener might realistically type into a search box, each answerable using ONLY the information in this section. Do not reference "this section" or "the text" -- phrase them the way a real user would type them.

Section title: {title}
Section text:
\"\"\"
{text}
\"\"\"

Return a JSON object of the form {{"questions": ["...", ...]}} with exactly {n} strings."""


def get_openai_client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def generate_questions(client: OpenAI, title: str, text: str, n: int = QUESTIONS_PER_SECTION) -> list[str]:
    """One API call, one section, JSON-mode output. Parses defensively --
    trusts the requested schema loosely, not blindly: a model can return the
    wrong count, non-string entries, or blank padding, so results are
    filtered and truncated to `n` rather than assumed correct.

    Retries on RateLimitError with growing backoff rather than letting one
    section silently drop out of the ground truth set -- see
    MAX_RATE_LIMIT_RETRIES above for why this is needed beyond whatever the
    openai client already does on its own.
    """
    truncated = text[:MAX_SECTION_CHARS_FOR_PROMPT]
    prompt = _PROMPT_TEMPLATE.format(n=n, title=title or "Untitled", text=truncated)

    last_error: RateLimitError | None = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            response = client.chat.completions.create(
                model=GENERATION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            payload = json.loads(response.choices[0].message.content)
            questions = payload.get("questions", [])
            questions = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
            return questions[:n]
        except RateLimitError as exc:
            last_error = exc
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))

    raise last_error
