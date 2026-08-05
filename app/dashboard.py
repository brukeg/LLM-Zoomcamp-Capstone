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

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.metrics import (  # noqa: E402
    get_judge_distribution,
    get_overview,
    get_strategy_comparison,
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

# Not from the DB -- offline search-eval artifact (see get_strategy_comparison).
strategy_comparison = get_strategy_comparison()

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


def _trend_chart(source, y_field: str, y_title: str):
    # Explicit Altair rather than st.line_chart: the native chart auto-pads a
    # small integer x-axis into negatives (id -3..9 with only 9 points), which
    # looks broken. nice=False, zero=False pins the x domain to the real ids.
    return (
        alt.Chart(source)
        .mark_line(point=True)
        .encode(
            x=alt.X("id:Q", scale=alt.Scale(nice=False, zero=False), title="conversation id"),
            y=alt.Y(f"{y_field}:Q", title=y_title),
        )
        .properties(height=240)
    )


# --- Panel 2: cost trend ----------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("Cost per conversation")
    st.altair_chart(_trend_chart(df, "cost", "cost ($)"), use_container_width=True)
# --- Panel 3: latency trend -------------------------------------------------
with right:
    st.subheader("Latency per conversation")
    st.altair_chart(_trend_chart(df, "response_time", "latency (s)"), use_container_width=True)

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

st.divider()

# --- Panel 6: token breakdown (prompt vs completion) ------------------------
left, right = st.columns(2)
with left:
    st.subheader("Tokens per conversation")
    # Long-form frame so color= stacks prompt vs completion in one bar per turn.
    token_rows = []
    for row in timeseries:
        token_rows.append({"id": row["id"], "kind": "prompt", "tokens": row["prompt_tokens"]})
        token_rows.append({"id": row["id"], "kind": "completion", "tokens": row["completion_tokens"]})
    token_df = pd.DataFrame(token_rows)
    st.bar_chart(token_df, x="id", y="tokens", color="kind", height=240)

# --- Panel 7 (bonus analytics): chunking-strategy comparison ----------------
# Offline search-eval, not live traffic -- the "bonus analytics view" from the
# plan. Six live panels above; this is the extra one.
with right:
    st.subheader("Search eval: strategy × method (bonus)")
    if strategy_comparison:
        strat_df = pd.DataFrame(strategy_comparison)
        strat_df["combo"] = strat_df["strategy"] + " · " + strat_df["method"]
        # Altair so the bars actually rank best->worst by hit rate --
        # st.bar_chart ignores the dataframe order and sorts the x-axis
        # alphabetically, which buries the winner mid-chart.
        strat_chart = (
            alt.Chart(strat_df)
            .mark_bar()
            .encode(
                x=alt.X("combo:N", sort=alt.SortField("hit_rate", order="descending"), title=None),
                y=alt.Y("hit_rate:Q", title="Hit Rate @5"),
                color=alt.Color("method:N"),
            )
            .properties(height=240)
        )
        st.altair_chart(strat_chart, use_container_width=True)
        st.caption("Hit Rate @5 from the Aug 3 evaluation (7,490 questions). "
                   "Winner: recursive + hybrid.")
    else:
        st.caption("Run `uv run python -m eval.evaluate_search` to populate this.")

st.caption("Panels: cost, latency, tokens, judge relevance, user feedback, "
           "chunking-strategy comparison (bonus) — plus overview counters up top.")
