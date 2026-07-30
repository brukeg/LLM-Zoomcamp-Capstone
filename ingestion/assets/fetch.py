"""Fetch assets: land raw, cleaned text for both source tiers into the
`documents` table. No chunking yet -- that's tomorrow, once there's real
output here to design the chunker against.

Untested against the live sites (see docs/decisions.md for why -- my
sandbox blocks both domains). URL patterns and response shapes were
verified by hand before writing this, but the first real `dagster asset
materialize` run is the actual test. Expect to iterate once you see real
output, particularly on the Gutenberg boilerplate regex (older/differently
digitized texts sometimes use non-standard markers) and the Clemson HTML
cleanup (WordPress content is generally consistent but not guaranteed to
be identical across 20 different authors/years of fact sheets).
"""

import html
import time

import dagster as dg
import requests

from ingestion.assets.config import FACTSHEET_SLUGS, GUTENBERG_BOOKS
from ingestion.parsing import html_to_structured_text, strip_gutenberg_boilerplate
from ingestion.resources import PostgresResource

USER_AGENT = "garden-companion-llm-zoomcamp-project/0.1 (educational, non-commercial)"
REQUEST_TIMEOUT = 30
POLITE_DELAY_SECONDS = 1.0

UPSERT_DOCUMENT_SQL = """
    INSERT INTO documents (id, source_type, source_ref, title, author, license_note, raw_text)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE SET
        title = EXCLUDED.title,
        author = EXCLUDED.author,
        raw_text = EXCLUDED.raw_text,
        fetched_at = now()
"""


@dg.asset(group_name="ingestion")
def gutenberg_books(context: dg.AssetExecutionContext, postgres: PostgresResource) -> dg.MaterializeResult:
    """Download the curated Gutenberg book list, strip PG boilerplate,
    land cleaned full text in documents.raw_text.
    """
    conn = postgres.get_connection()
    ok, failed = 0, []

    try:
        with conn.cursor() as cur:
            for pg_id, title, author in GUTENBERG_BOOKS:
                doc_id = f"gutenberg-{pg_id}"
                url = f"https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"

                try:
                    response = requests.get(
                        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
                    )
                    response.raise_for_status()
                    cleaned = strip_gutenberg_boilerplate(response.text)

                    cur.execute(
                        UPSERT_DOCUMENT_SQL,
                        (
                            doc_id,
                            "book",
                            str(pg_id),
                            title,
                            author,
                            "Public domain (Project Gutenberg)",
                            cleaned,
                        ),
                    )
                    conn.commit()
                    context.log.info(f"Fetched {title!r} ({len(cleaned):,} chars)")
                    ok += 1

                except Exception as exc:
                    conn.rollback()
                    context.log.warning(f"Failed to fetch {title!r} ({url}): {exc}")
                    failed.append(title)

                time.sleep(POLITE_DELAY_SECONDS)
    finally:
        conn.close()

    return dg.MaterializeResult(
        metadata={
            "books_fetched": ok,
            "books_failed": len(failed),
            "failed_titles": ", ".join(failed) if failed else "none",
        }
    )


@dg.asset(group_name="ingestion")
def extension_factsheets(
    context: dg.AssetExecutionContext, postgres: PostgresResource
) -> dg.MaterializeResult:
    """Fetch the curated Clemson HGIC fact sheet slugs via the site's
    WordPress REST API, clean the HTML, land as documents.raw_text.
    """
    conn = postgres.get_connection()
    ok, failed = 0, []

    try:
        with conn.cursor() as cur:
            for slug in FACTSHEET_SLUGS:
                doc_id = f"hgic-{slug}"
                url = f"https://hgic.clemson.edu/wp-json/wp/v2/factsheet?slug={slug}"

                try:
                    response = requests.get(
                        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
                    )
                    response.raise_for_status()
                    results = response.json()

                    if not results:
                        raise ValueError(f"no factsheet found for slug {slug!r}")

                    post = results[0]
                    # WP REST API returns titles HTML-entity-escaped
                    # ("&amp;" not "&") -- unescape so what lands in the DB
                    # is what a human (or an embedding model) should read.
                    title = html.unescape(post["title"]["rendered"])
                    cleaned = html_to_structured_text(post["content"]["rendered"])

                    cur.execute(
                        UPSERT_DOCUMENT_SQL,
                        (
                            doc_id,
                            "factsheet",
                            post["link"],
                            title,
                            None,  # author resolution needs a second API call; skip for now
                            "Clemson Cooperative Extension HGIC -- fair use, "
                            "non-commercial educational project (see docs/data-sources.md)",
                            cleaned,
                        ),
                    )
                    conn.commit()
                    context.log.info(f"Fetched {title!r} ({len(cleaned):,} chars)")
                    ok += 1

                except Exception as exc:
                    conn.rollback()
                    context.log.warning(f"Failed to fetch slug {slug!r} ({url}): {exc}")
                    failed.append(slug)

                time.sleep(POLITE_DELAY_SECONDS)
    finally:
        conn.close()

    return dg.MaterializeResult(
        metadata={
            "factsheets_fetched": ok,
            "factsheets_failed": len(failed),
            "failed_slugs": ", ".join(failed) if failed else "none",
        }
    )
