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

## Search evaluation result: recursive + hybrid, but method >> strategy

Ran Hit Rate and MRR for all 3 chunking strategies x {keyword, vector,
hybrid} against the 7,490-question ground truth, top_k=5
(eval/evaluate_search.py). Full table, ranked by MRR:

| strategy  | method   | hit_rate | mrr    |
|-----------|----------|----------|--------|
| recursive | hybrid   | 0.8051   | 0.6782 |
| structure | hybrid   | 0.7957   | 0.6656 |
| fixed     | hybrid   | 0.7917   | 0.6638 |
| recursive | vector   | 0.7846   | 0.6571 |
| structure | vector   | 0.7733   | 0.6431 |
| fixed     | vector   | 0.7648   | 0.6393 |
| fixed     | keyword  | 0.1928   | 0.1729 |
| structure | keyword  | 0.1853   | 0.1672 |
| recursive | keyword  | 0.1733   | 0.1571 |

Winner, and what we'll use for the RAG pipeline: **recursive + hybrid**.

The honest read, though, is that the retrieval **method** dominates the
chunking **strategy**, not the other way around. Hybrid > vector > keyword
by wide margins everywhere, but within hybrid the three strategies sit
within ~1.3 percentage points of each other (0.8051 / 0.7957 / 0.7917). At
7,490 questions that ordering is probably real, but it's small enough that
"recursive is the best chunking strategy" would be overselling it -- the
practically important result is "use hybrid retrieval," and recursive just
happens to edge the others under it.

On keyword being so weak (~0.18 hit rate): expected, not a bug. The ground
truth questions are LLM paraphrases of section content, not verbatim
quotes, so pure lexical matching loses to vocabulary mismatch -- exactly
the gap dense embeddings close. Hybrid beating pure vector everywhere
(e.g. 0.8051 vs 0.7846 for recursive) confirms keyword still adds a little
signal on top of vectors via RRF, just not enough to stand on its own.

Method notes: keyword = websearch_to_tsquery + ts_rank_cd on the generated
tsvector column; vector = cosine `<=>` on the HNSW index; hybrid =
Reciprocal Rank Fusion (k=60, standard default, not tuned) over a 60-chunk
candidate pool from each ranker. A "hit" = at least one of the top-5
retrieved chunks comes from the question's own source section (see the
ground-truth methodology note above for why correctness is scored by
section, not exact chunk/document id).

## RAG evaluation: 90% relevant, and deliberately NOT tuning the prompt

Offline LLM-as-judge evaluation (eval/evaluate_rag.py) on a fixed-seed
sample of 150 ground-truth questions: answers generated by the real
pipeline (recursive + hybrid, gpt-5.6-luna), judged by a stronger model
(gpt-5.6-terra) into RELEVANT / PARTLY_RELEVANT / NON_RELEVANT.

| class            |   n | share |
|------------------|-----|-------|
| RELEVANT         | 135 | 90.0% |
| PARTLY_RELEVANT  |   9 |  6.0% |
| NON_RELEVANT     |   6 |  4.0% |
| UNPARSEABLE      |   0 |  0.0% |

The plan called for iterating on the prompt "if the bad rate is high." It
isn't (4%), and -- more importantly -- the prompt is not what's causing the
failures, so we deliberately left it alone. Reasoning, because the "don't
touch it" decision is the substantive part here:

All six NON_RELEVANT cases are the same benign pattern: the system said
"the passages don't contain this, so I can't answer," and the judge counted
that as declining an answerable question. None are hallucinations, off-topic
answers, or misreadings of good context -- the system is failing SAFE,
refusing to invent an answer when retrieval didn't surface the right
passage. For a tool that gives gardening advice, that's the failure mode to
want.

And they're retrieval misses, not generation problems: every failed
question is a hyper-specific entity lookup (the leaves of *Menispermum
canadense*, the Alabama Snow Wreath, Red Castelnaudary beets) whose source
section exists in the corpus but didn't land in the top 5. This lines up
with the Aug 3 search result -- recursive + hybrid hit rate ~0.80, i.e.
~20% retrieval miss. Notably the RAG bad rate is only 4%, far below that
20%, which means on most retrieval misses a *related* chunk still carried
enough for a relevant answer -- the system is more robust than the raw hit
rate implied.

So tuning the system prompt would be optimizing against the wrong metric.
Nudging the model to answer anyway would trade safe refusals for
hallucinations -- strictly worse here. The one lever that would actually
help these cases is retrieval recall (higher top_k, or a reranker), which
is a search change, not a prompt change, and a 4% bad rate doesn't justify
it now. Noted as an optional future lever, explicitly not done.

Caveat we're accepting: this is a single judge model over 150 samples, so
there's some judge noise in the exact percentages -- but 90% is high enough
that the conclusion (prompt is fine, failures are safe retrieval misses)
holds well within that noise.
