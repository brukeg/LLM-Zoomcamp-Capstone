"""Garden Companion monitoring dashboard.

Run from the repo root:

    streamlit run app/dashboard.py

Same sys.path shim as app/main.py (streamlit run only puts app/ on the
path). Started Aug 7 with overview counters, cost/latency trends, the online
judge's relevance distribution, and the user thumbs tally. Aug 8 adds the
token-breakdown panel and the chunking-strategy comparison chart (from the
Aug 3 search evaluation) to reach the planned six views, plus polish.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.metrics import (  # noqa: E402
    get_judge_distribution,
    get_overview,
    get_timeseries,
    get_user_feedback_counts,
)
from db.connection import get_db_connection  # noqa: E402

st.set_page_config(page_title="Garden Companion · Monitoring", page_icon="📊", layout="wide")
st.title("📊 Garden Companion — Monitoring")

conn = get_db_connection()
try:
    overview = get_overview(conn)
    timeseries = get_timeseries(conn)
    judge_dist = get_judge_distribution(conn)
    user_feedback = get_user_feedback_counts(conn)
finally:
    conn.close()

if overview["n_conversations"] == 0:
    st.info("No conversations logged yet. Ask a few questions in the chat app first "
            "(`streamlit run app/main.py`), then reload this page.")
    st.stop()

# --- Panel 1: overview counters ---------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Conversations", overview["n_conversations"])
c2.metric("Total cost", f"${overview['total_cost']:.4f}")
c3.metric("Avg latency", f"{overview['avg_latency']:.1f}s")
c4.metric("Avg tokens", f"{overview['avg_tokens']:.0f}")

st.divider()
df = pd.DataFrame(timeseries)

# --- Panel 2: cost trend ----------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("Cost per conversation")
    st.line_chart(df, x="id", y="cost", height=240)
# --- Panel 3: latency trend -------------------------------------------------
with right:
    st.subheader("Latency per conversation")
    st.line_chart(df, x="id", y="response_time", height=240)

st.divider()

# --- Panel 4: online judge relevance distribution ---------------------------
left, right = st.columns(2)
with left:
    st.subheader("Online judge: relevance")
    if judge_dist:
        # Fixed class order so the chart reads best->worst regardless of which
        # classes have appeared yet.
        order = ["RELEVANT", "PARTLY_RELEVANT", "NON_RELEVANT"]
        judge_df = pd.DataFrame(
            {"relevance": order, "count": [judge_dist.get(c, 0) for c in order]}
        )
        st.bar_chart(judge_df, x="relevance", y="count", height=240)
    else:
        st.caption("No judge verdicts yet (enable auto-evaluate in the chat app).")

# --- Panel 5: user thumbs feedback ------------------------------------------
with right:
    st.subheader("User feedback")
    up = user_feedback.get("up", 0)
    down = user_feedback.get("down", 0)
    if up or down:
        fb1, fb2 = st.columns(2)
        fb1.metric("👍 Up", up)
        fb2.metric("👎 Down", down)
    else:
        st.caption("No thumbs feedback yet.")

st.caption("Panels shown: overview, cost, latency, judge relevance, user feedback. "
           "Token breakdown + chunking-strategy comparison land Aug 8.")
