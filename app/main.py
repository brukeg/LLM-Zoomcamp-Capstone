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

from app.store import log_conversation  # noqa: E402
from db.connection import get_db_connection  # noqa: E402
from rag.cost import estimate_cost  # noqa: E402
from rag.pipeline import ANSWER_MODEL, DEFAULT_STRATEGY, rag  # noqa: E402

st.set_page_config(page_title="Garden Companion", page_icon="🌱")


def _metrics_caption(model: str, total_tokens: int, latency: float, cost: float) -> str:
    return f"{model} · {total_tokens} tokens · {latency:.1f}s · ${cost:.4f}"


with st.sidebar:
    st.header("🌱 Garden Companion")
    st.caption(
        "Answers are grounded only in public-domain gardening books "
        "(Project Gutenberg) and Clemson Cooperative Extension fact sheets. "
        "If the sources don't cover a question, it will say so rather than guess."
    )
    st.caption(f"Retrieval: {DEFAULT_STRATEGY} chunks + hybrid search")
    st.caption(f"Answer model: {ANSWER_MODEL}")

st.title("🌱 Garden Companion")

if "messages" not in st.session_state:
    st.session_state.messages = []

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
                # Stored for Aug 7: thumbs feedback will reference this id.
                "conversation_id": conversation_id,
            },
        }
    )
