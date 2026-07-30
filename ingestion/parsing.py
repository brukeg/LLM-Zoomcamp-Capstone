"""Text cleanup for both source tiers.

Verified against real output before writing this (see docs/data-sources.md):
- Gutenberg plain text has standard START/END boilerplate markers.
- Clemson HGIC's WordPress REST API (`/wp-json/wp/v2/factsheet`) returns
  `content.rendered` as clean article HTML with no site chrome -- no need
  to fight nav bars, related-posts widgets, etc.

Neither of these was tested against a live run (my sandbox blocks both
domains -- see docs/decisions.md). The regex/parsing logic below is built
from real fetched samples, but the first real run is the actual test.
"""

import re

from bs4 import BeautifulSoup

# Modern Gutenberg texts wrap the actual book between these markers.
# Handles both "THE PROJECT GUTENBERG EBOOK" and "THIS PROJECT GUTENBERG
# EBOOK" phrasing, which both show up across the corpus depending on
# when the text was digitized.
_GUTENBERG_START_RE = re.compile(
    r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE,
)
_GUTENBERG_END_RE = re.compile(
    r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*",
    re.IGNORECASE,
)


def strip_gutenberg_boilerplate(raw_text: str) -> str:
    """Cut Project Gutenberg's license header/footer, keep the book.

    Falls back to returning the full text unchanged if the markers aren't
    found -- better to ingest a book with boilerplate attached (obvious
    and fixable once you see it) than to silently drop content or crash
    a batch job over one oddly-formatted title.
    """
    start_match = _GUTENBERG_START_RE.search(raw_text)
    end_match = _GUTENBERG_END_RE.search(raw_text)

    if not start_match or not end_match:
        return raw_text.strip()

    body = raw_text[start_match.end():end_match.start()]
    return body.strip()


# Elements that are noise even inside `content.rendered` -- WordPress image
# caption wrappers and a Divi theme popup trigger span that carries no text
# but is worth explicitly dropping rather than relying on get_text() to
# just skip it.
_STRIP_SELECTORS = ["div.wp-caption", "span.et_bloom_bottom_trigger", "script", "style"]


def html_to_structured_text(html: str) -> str:
    """Convert a Clemson HGIC `content.rendered` HTML blob to plain text.

    Headings are kept as lightweight markdown ('## ', '### ') rather than
    dropped, so tomorrow's structure-aware chunking strategy can still find
    section boundaries after this conversion.
    """
    soup = BeautifulSoup(html, "lxml")

    for selector in _STRIP_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    lines = []
    for el in soup.find_all(["h2", "h3", "h4", "p", "li"]):
        # separator=" " matters: without it, adjacent inline tags like
        # <strong>Method:</strong> To ensure... collapse into "Method:To
        # ensure..." because get_text(strip=True) strips each text node
        # individually before joining them with nothing.
        text = el.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue

        if el.name == "h2":
            lines.append(f"\n## {text}\n")
        elif el.name in ("h3", "h4"):
            lines.append(f"\n### {text}\n")
        elif el.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)

    return "\n".join(lines).strip()
