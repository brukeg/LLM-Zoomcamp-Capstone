"""Garden Companion chat app.

Run from the repo root:

    streamlit run app/main.py

`streamlit run` executes this file with only its own directory (app/) on
sys.path, not the repo root, so the `from rag...` / `from db...` imports
below would fail -- the sys.path insert at the very top fixes that and has
to come before those imports. Everything else is the standard Streamlit
chat pattern: history lives in st.session_state and is re-rendered on every
rerun, since Streamlit re-executes this whole script top-to-bottom on each
interaction.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.store import log_conversation, save_feedback  # noqa: E402
from db.connection import get_db_connection  # noqa: E402
from ingestion.embedding import get_openai_client  # noqa: E402
from rag.cost import estimate_cost  # noqa: E402
from rag.judge import judge_relevance  # noqa: E402
from rag.pipeline import ANSWER_MODEL, DEFAULT_STRATEGY, rag  # noqa: E402

st.set_page_config(page_title="Garden Companion", page_icon="🌱")


def _metrics_caption(model: str, total_tokens: int, latency: float, cost: float) -> str:
    return f"{model} · {total_tokens} tokens · {latency:.1f}s · ${cost:.4f}"


def _render_feedback_controls(conversation_id) -> None:
    """Thumbs up/down for one answer, tied to its conversation id. st.feedback
    persists its own selection in session_state by key across reruns; the
    separate `saved_feedback` set is what makes the DB write happen exactly
    once (Streamlit reruns return the stored selection on every run, not just
    on the click). No widget is shown if the turn never got a conversation id
    (logging failed) -- there'd be nothing to attach the feedback to.
    """
    if conversation_id is None:
        return

    selection = st.feedback("thumbs", key=f"fb_{conversation_id}")
    if selection is None or conversation_id in st.session_state.saved_feedback:
        return

    score = 1 if selection == 1 else -1
    try:
        conn = get_db_connection()
        try:
            save_feedback(conn, conversation_id, source="user", score=score)
        finally:
            conn.close()
        st.session_state.saved_feedback.add(conversation_id)
        st.toast("Thanks for the feedback!")
    except Exception as exc:
        st.warning(f"Couldn't save feedback: {exc}")


with st.sidebar:
    st.header("🌱 Garden Companion")
    st.caption(
        "Answers are grounded only in public-domain gardening books "
        "(Project Gutenberg) and Clemson Cooperative Extension fact sheets. "
        "If the sources don't cover a question, it will say so rather than guess."
    )
    st.caption(f"Retrieval: {DEFAULT_STRATEGY} chunks + hybrid search")
    st.caption(f"Answer model: {ANSWER_MODEL}")
    st.divider()
    auto_judge = st.checkbox(
        "Auto-evaluate answers (LLM judge)",
        value=True,
        help="After each answer, a separate model rates its relevance and logs "
             "the verdict for the monitoring dashboard. Turn off to skip that "
             "extra call.",
    )

st.title("🌱 Garden Companion")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "saved_feedback" not in st.session_state:
    st.session_state.saved_feedback = set()

# Re-render the full conversation history every run (Streamlit reruns the
# whole script on each interaction; session_state is what persists).
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        meta = message.get("meta")
        if meta:
            if meta["sources"]:
                st.caption("Sources: " + ", ".join(meta["sources"]))
            st.caption(_metrics_caption(meta["model"], meta["total_tokens"], meta["latency"], meta["cost"]))
            if meta.get("judge_relevance"):
                st.caption(f"🤖 auto-judge: {meta['judge_relevance']}")
            _render_feedback_controls(meta.get("conversation_id"))

question = st.chat_input("e.g. How often should I water tomato seedlings?")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Searching the gardening sources..."):
            try:
                result = rag(question)
            except Exception as exc:
                st.error(f"Something went wrong answering that: {exc}")
                st.stop()

            cost = estimate_cost(
                result["model"],
                result["usage"]["prompt_tokens"],
                result["usage"]["completion_tokens"],
            )

            # Logging failure shouldn't cost the user their answer -- warn and
            # keep going rather than dropping the response on the floor.
            conversation_id = None
            try:
                conn = get_db_connection()
                try:
                    conversation_id = log_conversation(conn, result)
                finally:
                    conn.close()
            except Exception as exc:
                st.warning(f"Answer generated, but logging it failed: {exc}")

        st.markdown(result["answer"])
        if result["sources"]:
            st.caption("Sources: " + ", ".join(result["sources"]))
        st.caption(
            _metrics_caption(
                result["model"], result["usage"]["total_tokens"], result["latency_seconds"], cost
            )
        )

        # Online relevance judge: rate the answer we just gave and log it as
        # 'judge' feedback for the dashboard. Only runs if the turn was logged
        # (needs a conversation_id to attach to) and the sidebar toggle is on.
        # Wrapped so a judge/API failure never breaks the answer the user
        # already sees.
        judge_relevance_label = None
        if auto_judge and conversation_id is not None:
            with st.spinner("Auto-evaluating…"):
                try:
                    judgment = judge_relevance(get_openai_client(), question, result["answer"])
                    conn = get_db_connection()
                    try:
                        save_feedback(
                            conn,
                            conversation_id,
                            source="judge",
                            relevance=judgment["relevance"],
                            explanation=judgment["explanation"],
                        )
                    finally:
                        conn.close()
                    judge_relevance_label = judgment["relevance"]
                except Exception as exc:
                    st.warning(f"Auto-evaluation failed (answer still saved): {exc}")
            if judge_relevance_label:
                st.caption(f"🤖 auto-judge: {judge_relevance_label}")

        _render_feedback_controls(conversation_id)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": result["answer"],
            "meta": {
                "sources": result["sources"],
                "model": result["model"],
                "total_tokens": result["usage"]["total_tokens"],
                "latency": result["latency_seconds"],
                "cost": cost,
                "conversation_id": conversation_id,
                "judge_relevance": judge_relevance_label,
            },
        }
    )
