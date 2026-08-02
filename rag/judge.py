"""LLM-as-judge relevance scoring, used both by offline RAG evaluation
(eval/evaluate_rag.py, Aug 5) and the online relevance judge on live
conversations (Aug 7). Kept here in rag/ rather than eval/ precisely because
it's reused online, not just for the one offline pass.

Judges with a stronger model than the one that writes the answers
(gpt-5.6-terra vs the pipeline's gpt-5.6-luna) so the evaluator isn't just
rubber-stamping output from its own tier -- a cheap guard against
self-preference bias.
"""

import json

# The three relevance buckets, matching the LLM Zoomcamp module 4 offline
# evaluation scheme. Kept as a set so parsing can validate against it rather
# than trusting the model to always return one of them.
RELEVANCE_CLASSES = {"RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT"}

# Distinct sentinel for a judgment we couldn't parse into a real class --
# surfaced separately in the summary instead of being silently folded into
# one of the real buckets, so a flaky judge response can't quietly skew the
# bad rate in either direction.
UNPARSEABLE = "UNPARSEABLE"

JUDGE_MODEL = "gpt-5.6-terra"

_JUDGE_PROMPT = """You are an expert evaluator for a home-gardening question-answering system.

Given a user's Question and the system's Answer, classify how well the Answer addresses the Question:

- RELEVANT: the answer directly and adequately addresses the question.
- PARTLY_RELEVANT: the answer is on-topic but incomplete, partially off-target, or hedged to the point of only weakly answering.
- NON_RELEVANT: the answer does not address the question, is evasive, is off-topic, or declines to answer a question that clearly should be answerable about gardening.

Question:
{question}

Answer:
{answer}

Return a JSON object of the form {{"relevance": "RELEVANT|PARTLY_RELEVANT|NON_RELEVANT", "explanation": "one short sentence"}}."""


def judge_relevance(client, question: str, answer: str, model: str = JUDGE_MODEL) -> dict:
    """Return {"relevance": <class>, "explanation": str}. `relevance` is
    always one of RELEVANCE_CLASSES or UNPARSEABLE -- never raw model text,
    so callers can aggregate on it safely.
    """
    prompt = _JUDGE_PROMPT.format(question=question, answer=answer)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )

    try:
        payload = json.loads(response.choices[0].message.content)
        relevance = str(payload.get("relevance", "")).strip().upper()
        explanation = str(payload.get("explanation", "")).strip()
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"relevance": UNPARSEABLE, "explanation": "judge returned unparseable output"}

    if relevance not in RELEVANCE_CLASSES:
        return {"relevance": UNPARSEABLE, "explanation": f"unexpected class: {relevance!r}"}

    return {"relevance": relevance, "explanation": explanation}
