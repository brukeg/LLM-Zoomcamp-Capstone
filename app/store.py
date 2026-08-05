"""Persistence for the chat app: write each answered question to the
`conversations` monitoring table (module 5 pattern). Feedback writes (Aug 7)
will land here too; kept separate from rag/ so the pipeline stays a pure
answer-producer and the app owns what gets logged.
"""

from datetime import datetime

from db.connection import DB_TIMEZONE
from rag.cost import estimate_cost

_INSERT_CONVERSATION_SQL = """
    INSERT INTO conversations (
        question, answer, model, instructions, prompt,
        search_strategy, search_method,
        prompt_tokens, completion_tokens, total_tokens,
        response_time, cost, timestamp
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""

_INSERT_FEEDBACK_SQL = """
    INSERT INTO feedback (conversation_id, source, relevance, explanation, score, timestamp)
    VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id
"""


def log_conversation(conn, result: dict) -> int:
    """Insert one answered turn and return its conversation id (so Aug 7's
    thumbs feedback and the online judge can reference it). Cost is derived
    here from the model + token counts rather than stored on the result, so
    there's one source of truth for pricing (rag/cost.py).

    Caller owns the connection; this commits so a crash later in the same
    request doesn't lose the logged turn.
    """
    usage = result["usage"]
    cost = estimate_cost(result["model"], usage["prompt_tokens"], usage["completion_tokens"])

    with conn.cursor() as cur:
        cur.execute(
            _INSERT_CONVERSATION_SQL,
            (
                result["question"],
                result["answer"],
                result["model"],
                result["instructions"],
                result["prompt"],
                result["search_strategy"],
                result["search_method"],
                usage["prompt_tokens"],
                usage["completion_tokens"],
                usage["total_tokens"],
                result["latency_seconds"],
                cost,
                datetime.now(DB_TIMEZONE),
            ),
        )
        conversation_id = cur.fetchone()[0]
    conn.commit()
    return conversation_id


def save_feedback(conn, conversation_id: int, source: str, relevance: str | None = None,
                  explanation: str | None = None, score: int | None = None) -> int:
    """Insert one feedback row and return its id. Serves both sources the
    feedback table's CHECK allows:

    - 'user': a thumbs click, carrying score (+1 up / -1 down); relevance and
      explanation left NULL.
    - 'judge': the online LLM-as-judge verdict on a live answer, carrying
      relevance + explanation; score left NULL.

    Caller owns the connection; commits so the write survives a later error
    in the same interaction.
    """
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_FEEDBACK_SQL,
            (conversation_id, source, relevance, explanation, score, datetime.now(DB_TIMEZONE)),
        )
        feedback_id = cur.fetchone()[0]
    conn.commit()
    return feedback_id
