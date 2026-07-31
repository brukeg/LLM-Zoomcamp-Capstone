# Design Decisions

Short log of choices that deviate from the course lessons, with the reasoning,
so the README write-up (and future me) doesn't have to reconstruct it later.

## Embeddings: OpenAI API, not sentence-transformers

The course uses `sentence-transformers` (`all-MiniLM-L6-v2`) run locally.
We're using OpenAI's `text-embedding-3-small` via API instead.

Why: sentence-transformers pulls in PyTorch, and Bruce already hit a
`transformers` v4/v5 incompatibility that needed a manual `transformers<5`
pin to resolve. With a 13-day deadline, avoiding a known dependency headache
is worth more than saving embedding API costs, which are small anyway
(text-embedding-3-small is $0.02 / 1M tokens). Downside: an extra API
dependency and a small ongoing cost per ingestion run. If this becomes
annoying, ONNX (module 2, lesson 9) is the fallback — same interface,
no PyTorch.

## Search backend: Postgres only (pgvector + native full-text search)

The course uses different tools per lesson (minsearch, sqlitesearch,
Elasticsearch, pgvector). We're standardizing on one Postgres instance for
everything: `pgvector` extension for vector search, native `tsvector`/`tsquery`
for keyword search, plus the monitoring tables from module 5. One database
dependency instead of three, and it's the same Postgres the monitoring
module already needs, so it's not even an extra service.

## Non-agentic RAG first, agentic as a stretch goal

Agreed with Bruce: build and fully evaluate a plain RAG pipeline first (it
gets full credit on "Retrieval flow" on its own), and only add function
calling / tool use on top if there's slack in the schedule near the end.
The course's own advice ("avoid agents when you can") backs this up.

## Chunking strategy comparison as the retrieval-evaluation centerpiece

Three strategies, all evaluated against the same ground truth:

1. **Fixed-size token windows** with overlap (`tiktoken` for counting) — the
   naive baseline.
2. **Structure-aware** — split books on chapter/section headers, fact sheets
   on HTML heading tags. Respects the author's own organization.
3. **Recursive/paragraph-based** — `langchain-text-splitters`'
   `RecursiveCharacterTextSplitter`, splits on paragraph/sentence boundaries.

Ground truth methodology note: the course generates one question per FAQ
*document* and checks whether search returns that exact document ID. Books
don't have that granularity — a "document" is a whole book. So ground truth
here is generated per *section* (before chunking), and a retrieval "hit"
means the retrieved chunk overlaps that source section, not an exact
document-ID match. This needs to be spelled out clearly in the eval writeup
since it's a real methodology adaptation, not just a smaller version of the
same thing.

## Clemson fact sheets: WordPress REST API, not HTML scraping

Original plan was BeautifulSoup against the rendered HTML pages. Turns out
`hgic.clemson.edu` runs WordPress with `factsheet` registered as its own
post type, exposed at `/wp-json/wp/v2/factsheet?slug={slug}` — returns
`content.rendered` as clean article HTML with none of the page chrome
(nav, related posts, footer). No selector-guessing against a theme that
could change; the API only returns the actual content.

One thing this API gets wrong: `title.rendered` is HTML-entity-escaped
(`&amp;` not `&`), which slipped through on the first real run and showed
up as literal `&amp;` in stored titles. Fixed with `html.unescape()` in
`ingestion/assets/fetch.py` — worth remembering if any other field from
this API gets pulled in later (author names, category labels), since the
same escaping applies there too.

Matters for later: if Clemson's coverage needs widening past the current
20-slug sample, or if UF/IFAS EDIS gets added as a second fact-sheet
source (see docs/data-sources.md), check for a REST API first rather than
defaulting to HTML scraping. Many WordPress-based extension sites have
one; it's just not always obvious from the rendered pages.
