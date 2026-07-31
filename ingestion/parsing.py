"""Text cleanup for both source tiers.

Verified against real output before writing this (see docs/data-sources.md):
- Gutenberg plain text has standard START/END boilerplate markers.
- Clemson HGIC's WordPress REST API (`/wp-json/wp/v2/factsheet`) returns
  `content.rendered` as clean article HTML with no site chrome -- no need
  to fight nav bars, related-posts widgets, etc.

Confirmed working against live data on 7/30 (all 28 documents landed
cleanly) and the section-splitting logic below against the real fetched
corpus on 7/31 -- see docs/decisions.md and chat log for specifics.
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


# ============================================================
# Section splitting -- the pre-chunk unit ground truth is generated from.
# See docs/decisions.md for why books need this at all (a "document" here
# can be a whole book, so we split first).
# ============================================================

# Confirmed against real fetched text (both a narrative book and a
# reference-style one -- see chat log 7/31): chapters are marked
# "CHAPTER <roman-or-arabic>[. optional title]" on their own line. Every
# book checked has this appear TWICE per chapter -- once in the table of
# contents, once at the real chapter break in the body -- which the
# splitting logic below has to account for.
#
# The (?![a-zA-Z]) after the numeral group is load-bearing, not decoration:
# without it, ordinary prose like "...as this chapter contains a brief
# consideration of..." falsely matches when "chapter" lands at the start of
# a hard-wrapped line, because [IVXLC]+ happily matches just the "C" off
# the front of "Contains". A real chapter marker is never immediately
# followed by a lowercase letter -- caught this on gutenberg-9550's real
# output (a phantom "Chapter C" section that ate the back half of the real
# Chapter VII).
_CHAPTER_RE = re.compile(
    r"^[ \t]*chapter[ \t]+([IVXLC]+|[0-9]+)(?![a-zA-Z])\.?[ \t]*([^\r\n]*)",
    re.IGNORECASE | re.MULTILINE,
)

_MIN_FRONT_MATTER_CHARS = 200


def _positions_from_grouped_matches(
    text: str, groups: dict[str, list[re.Match]], title_fn
) -> list[tuple[int, str]]:
    """Shared dedup logic: for each distinct key (chapter number, or header
    text), use the LAST occurrence's position as the real split point. Every
    book checked so far has each real heading appear at least twice (ToC
    entry + real body heading, or for catalog books, an index entry + the
    real entry) -- ToC/index entries always cluster near each other with
    almost nothing between them, so they're never the last occurrence.
    """
    positioned = []
    for key, occurrences in groups.items():
        split_at = occurrences[-1].start()
        positioned.append((split_at, title_fn(key, occurrences)))
    positioned.sort(key=lambda x: x[0])
    return positioned


def _sections_from_positions(text: str, positioned: list[tuple[int, str]]) -> list[tuple[str, str]]:
    sections = []

    front_matter = text[: positioned[0][0]].strip()
    if len(front_matter) >= _MIN_FRONT_MATTER_CHARS:
        sections.append(("Front Matter", front_matter))

    for i, (start, title) in enumerate(positioned):
        end = positioned[i + 1][0] if i + 1 < len(positioned) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((title, body))

    return sections


def _split_on_chapter_matches(text: str, matches: list[re.Match]) -> list[tuple[str, str]]:
    by_number: dict[str, list[re.Match]] = {}
    for m in matches:
        number = m.group(1).upper()
        by_number.setdefault(number, []).append(m)

    def title_fn(number: str, occurrences: list[re.Match]) -> str:
        title_text = ""
        for occ in occurrences:
            candidate = occ.group(2).strip(" .\r\t")
            if candidate:
                title_text = candidate
                break
        return f"Chapter {number}" + (f": {title_text}" if title_text else "")

    positioned = _positions_from_grouped_matches(text, by_number, title_fn)
    return _sections_from_positions(text, positioned)


# Second-tier fallback for catalog/reference-style books that don't use
# "CHAPTER" markers at all -- confirmed on real data 7/31 via
# regexp_matches() against three different books:
#   - gutenberg-16232 (Culture of Vegetables): vegetable names as entries
#     (ASPARAGUS, BROAD BEAN, CABBAGE, ...)
#   - gutenberg-21414 (Culinary Herbs): topic headers (PREFACE, HISTORY,
#     PROPAGATION, COMPOSITAE, ...)
#   - gutenberg-10852 (Hardy Ornamental Flowering Trees and Shrubs): genus
#     names (ABELIA., AESCULUS., AILANTHUS., ...)
# All three show the same signal: a short, isolated, all-caps line with a
# blank line on both sides. gutenberg-34602 is the confirmed NEGATIVE case
# -- it only produces a handful of matches, and inspecting them shows
# they're a publisher's back-of-book ad listing other titles in the same
# series ("THE RURAL SCIENCE SERIES", "WORKS BY PROFESSOR BAILEY"), not
# real section headers; a body sample checked by hand ~20k characters in
# is ordinary flowing prose with no header line anywhere nearby. The
# thresholds below exist specifically to reject that case rather than
# accept a few front-matter matches as if they were real structure.
_GENERIC_HEADER_RE = re.compile(r"\r\n\r\n([A-Z][A-Z ,.'-]{2,40})\r\n\r\n")
_MIN_GENERIC_HEADERS = 5


def _split_on_generic_headers(text: str) -> list[tuple[str, str]] | None:
    """Returns None (not an empty list) when the pattern doesn't look like
    real, evenly-distributed structure, so the caller falls through to the
    fixed-size pseudo-section tier instead of accepting false positives.
    """
    matches = list(_GENERIC_HEADER_RE.finditer(text))
    if len(matches) < _MIN_GENERIC_HEADERS:
        return None
    # Real structure spans the book; front-matter-only noise (the 34602
    # case) clusters near the start. Require the last match to fall past
    # the halfway point as a cheap way to tell the two apart.
    if matches[-1].start() < len(text) / 2:
        return None

    by_title: dict[str, list[re.Match]] = {}
    for m in matches:
        title = m.group(1).strip(" .")
        by_title.setdefault(title, []).append(m)

    positioned = _positions_from_grouped_matches(text, by_title, lambda key, _occ: key)
    return _sections_from_positions(text, positioned)


_PSEUDO_SECTION_CHARS = 4000


def _split_fixed_pseudo_sections(text: str) -> list[tuple[str, str]]:
    """Last-resort fallback for books with no detectable header structure at
    all (confirmed case: gutenberg-34602), and also used by
    _cap_section_sizes to re-split any section that's still oversized after
    tier 1 or tier 2. Groups paragraphs into ~4000-char pseudo-sections
    rather than pretending we found real structure, or leaving the whole
    book/section as one giant blob. This is a known coarser fallback --
    ground truth quality for whichever books land here will be weaker than
    for books with real chapter/entry structure, and that's an accepted,
    documented trade-off given the project timeline, not an oversight.

    A single paragraph bigger than the cap on its own (no blank line to
    split on -- e.g. one long unbroken catalog entry) is hard-split on
    whitespace instead of being left whole. Caught by a synthetic test, not
    guessed: without this, _cap_section_sizes silently failed to cap a
    61,629-character section down to the 20,000-character limit because
    it was one single paragraph with no internal blank lines.
    """
    paragraphs = re.split(r"(?:\r\n){2,}|\n{2,}", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    groups: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        if current:
            groups.append("\n\n".join(current))
            current.clear()

    for para in paragraphs:
        if len(para) > _PSEUDO_SECTION_CHARS:
            flush()
            current_len = 0
            words = para.split(" ")
            piece: list[str] = []
            piece_len = 0
            for word in words:
                piece.append(word)
                piece_len += len(word) + 1
                if piece_len >= _PSEUDO_SECTION_CHARS:
                    groups.append(" ".join(piece))
                    piece = []
                    piece_len = 0
            if piece:
                groups.append(" ".join(piece))
            continue

        current.append(para)
        current_len += len(para)
        if current_len >= _PSEUDO_SECTION_CHARS:
            flush()
            current_len = 0
    flush()

    return [(f"Part {i + 1}", body) for i, body in enumerate(groups)]


# Applied after any tier, not just tier 3: confirmed necessary on real data
# 7/31 -- a full 8-book section-count/size check turned up at least one
# section over 100K characters in gutenberg-16232, -21414, and -34602 even
# where tier 1 or tier 2 otherwise worked. Root cause is the same either
# way -- a real entry/chapter the pattern didn't match (most likely a Latin
# binomial name in mixed case, breaking the all-caps character class)
# swallows everything up to the next match. Rather than chase down each
# book's exact formatting quirk one at a time, cap every section's size
# uniformly and recursively re-split anything still oversized.
_MAX_SECTION_CHARS = 20000


def _cap_section_sizes(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    capped = []
    for title, body in sections:
        if len(body) <= _MAX_SECTION_CHARS:
            capped.append((title, body))
            continue
        pieces = _split_fixed_pseudo_sections(body)
        for i, (_, piece_body) in enumerate(pieces):
            capped.append((f"{title} (part {i + 1})", piece_body))
    return capped


def split_book_sections(text: str) -> list[tuple[str, str]]:
    """Split book raw_text into (title, body) sections.

    Three tiers, tried in order, each falling through to the next only when
    the previous one finds nothing (or nothing convincing):

    1. "CHAPTER <roman-or-arabic>" markers -- narrative books. Every chapter
       number showing up twice (ToC entry + real body heading) is the key
       wrinkle there; see _split_on_chapter_matches.
    2. Isolated all-caps lines -- catalog/reference-style books organized by
       entry (vegetable name, genus, topic) rather than narrative chapters.
       See _split_on_generic_headers for the real books this was confirmed
       against, and the negative case it's guarding against.
    3. Fixed-size pseudo-sections -- books with no detectable structure via
       either pattern. Coarser, but still section-granular rather than
       "whole book as one section."

    Not guessing at a fourth pattern beyond this; three real structural
    variants were confirmed across the 8-book corpus on 7/31, and this
    covers all of them. Whatever tier is used, the result still passes
    through _cap_section_sizes -- no single strategy is trusted to cover
    100% of a book's structure, since real data showed all of them can
    leave gaps (see _cap_section_sizes docstring above).
    """
    if not text.strip():
        return []

    matches = list(_CHAPTER_RE.finditer(text))
    if matches:
        sections = _split_on_chapter_matches(text, matches)
    else:
        generic = _split_on_generic_headers(text)
        sections = generic if generic is not None else _split_fixed_pseudo_sections(text)

    return _cap_section_sizes(sections)


_FACTSHEET_HEADER_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def split_factsheet_sections(text: str, fallback_title: str) -> list[tuple[str, str]]:
    """Split factsheet text on the '## ' markers html_to_structured_text
    inserted. Every factsheet checked so far has at least one -- but this
    still falls back to a single section (using the document's own title)
    for the rare one that doesn't, rather than dropping it.
    """
    matches = list(_FACTSHEET_HEADER_RE.finditer(text))
    if not matches:
        return [(fallback_title, text.strip())] if text.strip() else []

    sections = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("Introduction", preamble))

    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((title, body))

    return sections
