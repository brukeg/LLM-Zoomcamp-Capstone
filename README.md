# 🌱 Garden Companion

A retrieval-augmented (RAG) chatbot that answers home-gardening questions,
grounded in public-domain gardening books and university extension fact
sheets. Built as the capstone for
[DataTalksClub's LLM Zoomcamp](https://github.com/DataTalksClub/llm-zoomcamp).

Ask a real question — *"How often should I water tomato seedlings?"*, *"What
soil is best for strawberries?"* — and get a practical answer assembled only
from trustworthy gardening sources, with citations back to the book or fact
sheet each claim came from.

<!-- SCREENSHOT: chat app answering a question, with sources + metrics.
     Save to docs/images/chat.png and it renders below. -->
<!-- ![Chat app](docs/images/chat.png) -->

<!-- DEMO VIDEO: record from the Streamlit app menu (top-right → Record a
     screencast), then drag the file into this README on GitHub to embed. -->

---

## The problem

Good gardening advice exists, but it's badly searchable when you have a
specific question in the moment. Classic references (Bailey's *Manual of
Gardening*, extension fact sheets) are authoritative but locked in long-form
prose or scattered across dozens of pages. A general web search returns SEO
content of uncertain quality; a general LLM will confidently make things up.

Garden Companion narrows the world to a curated, trustworthy corpus and
answers **only** from it — citing sources, and saying "I don't know" when the
sources don't cover the question rather than hallucinating. It's a focused
Q&A tool over gardening reference material.

## What it does

```
  question
     │
     ▼
  query rewrite (LLM turns it into a search query)
     │
     ▼
  hybrid retrieval  ──►  Postgres + pgvector
   (keyword tsvector + vector cosine, fused with RRF)
     │
     ▼
  top-k chunks  ──►  prompt  ──►  LLM answer (cited, grounded)
     │
     ▼
  log conversation + online judge  ──►  monitoring dashboard
```

## Data

Two tiers, chosen deliberately — large books (the "big document" chunking
problem) and small structured fact sheets (clean, FAQ-adjacent content).
Neither is committed to the repo; both are **fetched at ingestion time**, so
the dataset stays accessible to anyone who clones and runs the pipeline.

| Tier | Source | Count | Access |
|------|--------|-------|--------|
| Books | [Project Gutenberg](https://www.gutenberg.org/) public-domain gardening/horticulture texts | 8 | Plain-text download by ID |
| Fact sheets | [Clemson HGIC](https://hgic.clemson.edu/) Cooperative Extension | 20 | WordPress REST API |

After ingestion this becomes **28 documents → ~1,500 sections → ~20,600
chunks** (across three chunking strategies) → embedded into pgvector.

Both sources are freely and publicly accessible; nothing is licensed or
private. Details, the exact source list, and licensing notes:
[docs/data-sources.md](docs/data-sources.md).

## Tech stack

| Concern | Choice |
|---------|--------|
| LLM + embeddings | OpenAI (`gpt-5.6-luna` answers/rewrite, `gpt-5.6-terra` judge, `text-embedding-3-small`) |
| Knowledge base | Postgres 17 + [pgvector](https://github.com/pgvector/pgvector) (vector search **and** native full-text search in one DB) |
| Ingestion pipeline | [Dagster](https://dagster.io/) asset-based orchestration |
| Interface | Streamlit chat app |
| Monitoring | Streamlit dashboard reading Postgres |
| Packaging | uv (locked deps), Docker Compose |

Why several of these differ from the course defaults (OpenAI vs.
sentence-transformers, Postgres-only vs. multiple search backends, Dagster
vs. Kestra) is documented in [docs/decisions.md](docs/decisions.md).

## Running it from zero

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), and an OpenAI
API key.

```bash
git clone https://github.com/brukeg/LLM-Zoomcamp-Capstone.git
cd LLM-Zoomcamp-Capstone

cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...

make setup    # postgres + schema + ingest + ground truth + question embeddings
make up       # build & start the chat app and dashboard
```

Then open:

- **Chat app** → http://localhost:8501
- **Monitoring dashboard** → http://localhost:8502

`make setup` runs the full ingestion (fetches the books + fact sheets, chunks
and embeds them, generates evaluation ground truth). It needs internet and
your OpenAI key, takes a few minutes, and costs a few dollars in API calls.
Run `make help` for the individual steps. Dependency versions are pinned in
`uv.lock` (and Python in `.python-version`), so the environment is
reproducible.

To stop without losing data: `make down`. To wipe the database and start
over: `make clean`.

## How it works

**Ingestion** ([`ingestion/`](ingestion/)) is a Dagster job that fetches each
source, strips boilerplate, splits documents into sections, chunks each
section three ways (fixed-size token windows, structure-aware, and recursive),
and embeds every chunk into pgvector. One command materializes the whole
graph: fetch → sections → chunks → embeddings.

**Retrieval** ([`rag/search.py`](rag/search.py)) offers keyword search
(Postgres `tsvector`), vector search (pgvector cosine over an HNSW index), and
a **hybrid** of the two fused with Reciprocal Rank Fusion.

**The RAG pipeline** ([`rag/pipeline.py`](rag/pipeline.py)) rewrites the
question into a search query, retrieves the top chunks with hybrid search,
and prompts the LLM to answer using only those passages, with inline
citations. It returns the answer plus token/cost/latency for logging.

## Evaluation

### Retrieval evaluation — multiple approaches compared

All **3 chunking strategies × {keyword, vector, hybrid} = 9 combinations**
were scored against 7,490 LLM-generated ground-truth questions (Hit Rate and
MRR @5). A "hit" means a retrieved chunk came from the question's own source
section. Full harness: [`eval/evaluate_search.py`](eval/evaluate_search.py).

| strategy | method | hit_rate | mrr |
|----------|--------|----------|-----|
| **recursive** | **hybrid** | **0.8051** | **0.6782** |
| structure | hybrid | 0.7957 | 0.6656 |
| fixed | hybrid | 0.7917 | 0.6638 |
| recursive | vector | 0.7846 | 0.6571 |
| … | keyword | ~0.18 | ~0.17 |

**Winner: recursive chunks + hybrid retrieval**, which the pipeline uses. The
headline finding is that retrieval *method* matters far more than chunking
*strategy* — hybrid beats keyword-only by ~0.62 hit rate, while the three
chunking strategies sit within ~1.3 points of each other. Full analysis in
[docs/decisions.md](docs/decisions.md).

### RAG / LLM evaluation — multiple prompts compared

Answers were A/B-tested on a fixed-seed 150-question sample, with a
**stronger model as LLM-as-judge** (`gpt-5.6-terra` judging `gpt-5.6-luna`
answers, to avoid self-preference) classifying each answer RELEVANT /
PARTLY_RELEVANT / NON_RELEVANT. Harness:
[`eval/evaluate_rag.py`](eval/evaluate_rag.py).

**Prompt A/B** (two answer prompts, both with query rewriting on):

| prompt | relevant | partly | bad |
|--------|----------|--------|-----|
| v1_grounded | 81.3% | 10.0% | 8.7% |
| **v2_direct** | **83.3%** | 8.0% | 8.7% |

**Query-rewriting ablation** (v2_direct prompt, rewriting on vs off):

| config | relevant | partly | bad |
|--------|----------|--------|-----|
| rewrite on | 85.3% | 8.0% | 6.7% |
| **rewrite off** | **88.7%** | 8.0% | **3.3%** |

**Final config the pipeline uses: `v2_direct` prompt + query rewriting off**
(88.7% relevant, 3.3% bad). The notable result is that **query rewriting
*hurt*** — it was implemented and evaluated (a course "best practice"), found
to reduce relevance on this paraphrase-heavy corpus (it strips phrasing the
keyword half of hybrid search relies on), and so left off by default. The few
failures are overwhelmingly *safe refusals* on retrieval misses rather than
hallucinations — the system fails safe. Full analysis, including the
~2-point run-to-run judge variance, is in [docs/decisions.md](docs/decisions.md).

## Monitoring

Every answered question is logged to Postgres (question, answer, model,
tokens, cost, latency). Two feedback channels feed the dashboard: **user
thumbs** 👍/👎 and an **online LLM-as-judge** that rates each live answer's
relevance automatically.

The **dashboard** ([`app/dashboard.py`](app/dashboard.py), port 8502) shows
six charts: cost, latency, token breakdown, online-judge relevance
distribution, user feedback, and (bonus) the offline chunking-strategy
comparison.

<!-- SCREENSHOT: dashboard. Save to docs/images/dashboard.png -->
<!-- ![Dashboard](docs/images/dashboard.png) -->

## Containerization

`docker-compose.yaml` runs the whole application stack — Postgres, the chat
app, and the dashboard — with `make up`. The app image is built from the
[`Dockerfile`](Dockerfile). Postgres data persists in a named volume.

## Where each evaluation criterion is met

| Criterion | Where |
|-----------|-------|
| Problem description | This README, top |
| Retrieval flow (KB + LLM) | [`rag/pipeline.py`](rag/pipeline.py) |
| Retrieval evaluation (multiple approaches) | [`eval/evaluate_search.py`](eval/evaluate_search.py), table above |
| LLM evaluation (multiple approaches) | [`eval/evaluate_rag.py`](eval/evaluate_rag.py), A/B above |
| Interface | Streamlit chat app ([`app/main.py`](app/main.py)) |
| Ingestion pipeline (automated) | Dagster ([`ingestion/`](ingestion/)) |
| Monitoring (feedback + 6-chart dashboard) | [`app/dashboard.py`](app/dashboard.py) |
| Containerization (all in compose) | [`docker-compose.yaml`](docker-compose.yaml) |
| Reproducibility (pinned deps, accessible data) | `make setup`, `uv.lock` |
| Best practice: hybrid search | [`rag/search.py`](rag/search.py), evaluated above |
| Best practice: query rewriting | [`rag/pipeline.py`](rag/pipeline.py) `rewrite_query` |

## Repository layout

```
ingestion/   Dagster assets: fetch, section-split, chunk, embed, ground truth
rag/         search (keyword/vector/hybrid), pipeline, query rewrite, judge, cost
eval/        retrieval evaluation, RAG A/B evaluation, question embedding
app/         Streamlit chat app, monitoring dashboard, persistence, metrics
db/          schema, connection, init
docs/        data sources, design decisions
```

## Design decisions

Every place this project deviates from the course lessons — and why — is
logged in [docs/decisions.md](docs/decisions.md).
