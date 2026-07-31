"""Three chunking strategies, compared against the same ground truth (see
docs/decisions.md). All three split WITHIN a single section's text and
never span sections -- ground truth is generated per section, and a
retrieval "hit" is checked by section_id membership, which only works
cleanly if every chunk belongs to exactly one section. This also means the
strategies differ only in *how* they split a section's text, not in what
unit they operate over.
"""

import re

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

# cl100k_base is the encoding text-embedding-3-small uses; tiktoken doesn't
# have a direct encoding_for_model() entry for embedding models, but OpenAI's
# own docs confirm cl100k_base is correct here.
_ENCODING = tiktoken.get_encoding("cl100k_base")

FIXED_CHUNK_TOKENS = 250
FIXED_OVERLAP_TOKENS = 50

STRUCTURE_TARGET_CHARS = 1200

RECURSIVE_CHUNK_CHARS = 1000
RECURSIVE_OVERLAP_CHARS = 100

# Applied to every strategy's output before it's returned. Confirmed
# necessary on real data 7/31 -- across all three strategies, chunks as
# small as 3-19 characters showed up (a sliding token window's trailing
# fragment, or a whole section that was already tiny). A handful of
# characters contributes nothing useful to embedding/retrieval and just
# adds noise, so anything under this floor gets merged into a neighbor
# instead of standing alone.
MIN_CHUNK_CHARS = 50


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def _merge_tiny_chunks(chunks: list[str]) -> list[str]:
    """Merge any chunk under MIN_CHUNK_CHARS into the previous chunk (or the
    next one, if it's the first). Guaranteed to terminate: every merge
    removes one element from the list, and a single remaining chunk is
    always left alone regardless of size (nothing left to merge into).
    """
    if len(chunks) <= 1:
        return chunks

    merged = list(chunks)
    i = 0
    while i < len(merged):
        if len(merged[i]) >= MIN_CHUNK_CHARS or len(merged) == 1:
            i += 1
            continue
        if i > 0:
            merged[i - 1] = merged[i - 1] + "\n\n" + merged[i]
            del merged[i]
            # don't advance -- re-check whatever shifted into index i
        else:
            merged[i + 1] = merged[i] + "\n\n" + merged[i + 1]
            del merged[i]
    return merged


def _hard_split_by_chars(text: str, target_chars: int) -> list[str]:
    """Split text with no usable blank-line boundaries into ~target_chars
    pieces on whitespace, so a single oversized paragraph never slips
    through uncapped. Same fix as ingestion/parsing.py's
    _split_fixed_pseudo_sections applies for the section-splitting layer;
    needed again here for the same reason -- a real 9,302-character
    "structure" chunk (against a 1,200-char target) showed up in production
    on 7/31 because chunk_structure_aware had no equivalent guard.
    """
    words = text.split(" ")
    pieces = []
    piece: list[str] = []
    piece_len = 0
    for word in words:
        piece.append(word)
        piece_len += len(word) + 1
        if piece_len >= target_chars:
            pieces.append(" ".join(piece))
            piece, piece_len = [], 0
    if piece:
        pieces.append(" ".join(piece))
    return pieces


def chunk_fixed_size(text: str) -> list[str]:
    """Naive baseline: sliding token-count window with overlap, no regard
    for paragraph or sentence boundaries at all.
    """
    tokens = _ENCODING.encode(text)
    if not tokens:
        return []

    chunks = []
    step = FIXED_CHUNK_TOKENS - FIXED_OVERLAP_TOKENS
    for start in range(0, len(tokens), step):
        window = tokens[start : start + FIXED_CHUNK_TOKENS]
        if not window:
            break
        chunks.append(_ENCODING.decode(window))
        if start + FIXED_CHUNK_TOKENS >= len(tokens):
            break
    return _merge_tiny_chunks(chunks)


def chunk_structure_aware(text: str) -> list[str]:
    """Respects the section's own paragraph breaks: keeps the section whole
    if it's already a reasonable chunk size, otherwise packs paragraphs
    together up to ~STRUCTURE_TARGET_CHARS without splitting one mid-
    sentence. Deliberately no overlap -- the point of this strategy is
    following the author's own structure, not a sliding window.

    A single paragraph bigger than the target on its own (no blank line to
    split on) is hard-split on whitespace rather than kept whole -- see
    _hard_split_by_chars.
    """
    if not text.strip():
        return []
    if len(text) <= STRUCTURE_TARGET_CHARS:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"(?:\r\n){2,}|\n{2,}", text) if p.strip()]
    chunks = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if len(para) > STRUCTURE_TARGET_CHARS:
            if current:
                chunks.append("\n\n".join(current))
                current, current_len = [], 0
            chunks.extend(_hard_split_by_chars(para, STRUCTURE_TARGET_CHARS))
            continue
        if current and current_len + len(para) > STRUCTURE_TARGET_CHARS:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return _merge_tiny_chunks(chunks)


_recursive_splitter = RecursiveCharacterTextSplitter(
    chunk_size=RECURSIVE_CHUNK_CHARS,
    chunk_overlap=RECURSIVE_OVERLAP_CHARS,
)


def chunk_recursive(text: str) -> list[str]:
    """langchain's RecursiveCharacterTextSplitter: tries separators in order
    (double newline, single newline, sentence, word) to hit a target size,
    without an explicit paragraph-packing rule of our own -- a middle ground
    between the fully naive and fully structure-respecting strategies.
    """
    if not text.strip():
        return []
    return _merge_tiny_chunks(_recursive_splitter.split_text(text))
