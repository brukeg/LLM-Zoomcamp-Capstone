"""Read-only aggregation queries for the monitoring dashboard. Pure
data-in/data-out (each takes a live connection, returns plain Python), so
the dashboard module stays presentation-only and these stay easy to reason
about. Started Aug 7; Aug 8 adds the remaining panels' queries here.
"""


def get_overview(conn) -> dict:
    """Top-line counters across all logged conversations. COALESCE keeps the
    aggregates numeric (0) instead of NULL when the table is still empty, so
    the dashboard never has to special-case None.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(cost), 0),
                COALESCE(AVG(response_time), 0),
                COALESCE(AVG(total_tokens), 0),
                COALESCE(AVG(prompt_tokens), 0),
                COALESCE(AVG(completion_tokens), 0)
            FROM conversations
            """
        )
        row = cur.fetchone()
    return {
        "n_conversations": row[0],
        "total_cost": float(row[1]),
        "avg_latency": float(row[2]),
        "avg_tokens": float(row[3]),
        "avg_prompt_tokens": float(row[4]),
        "avg_completion_tokens": float(row[5]),
    }


def get_timeseries(conn) -> list[dict]:
    """Per-conversation cost / latency / tokens in insertion order, for the
    trend charts.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, timestamp, cost, response_time, total_tokens "
            "FROM conversations ORDER BY id"
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "cost": float(r[2]),
            "response_time": float(r[3]),
            "total_tokens": r[4],
        }
        for r in rows
    ]


def get_judge_distribution(conn) -> dict:
    """Counts of the online judge's relevance verdicts (source='judge'),
    e.g. {"RELEVANT": 12, "PARTLY_RELEVANT": 3, "NON_RELEVANT": 1}.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT relevance, COUNT(*) FROM feedback "
            "WHERE source = 'judge' AND relevance IS NOT NULL "
            "GROUP BY relevance"
        )
        rows = cur.fetchall()
    return {r[0]: r[1] for r in rows}


def get_user_feedback_counts(conn) -> dict:
    """Thumbs tally from user feedback (source='user'), bucketed by score
    sign: {"up": n, "down": n}.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                CASE WHEN score > 0 THEN 'up'
                     WHEN score < 0 THEN 'down'
                     ELSE 'neutral' END AS kind,
                COUNT(*)
            FROM feedback
            WHERE source = 'user'
            GROUP BY kind
            """
        )
        rows = cur.fetchall()
    return {r[0]: r[1] for r in rows}
