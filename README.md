# Garden Companion

A RAG chatbot for gardening questions, built as the capstone project for
[DataTalksClub's LLM Zoomcamp](https://github.com/DataTalksClub/llm-zoomcamp)
(2026 cohort).

> Status: early build. This README will be filled in as each piece lands —
> see the checklist below for what's done.

## Problem

*(to be written once the RAG pipeline exists — the short version: gardening
advice is scattered across books and university extension fact sheets, and
neither is easy to search when you have a specific "why is this plant doing
that" question in the moment.)*

## Data

Two tiers, both fetched at ingestion time rather than committed to the repo:

- **Public-domain gardening books** from Project Gutenberg — the "large
  document" source, driving a chunking-strategy comparison.
- **University extension fact sheets** from Clemson HGIC — smaller,
  structured, FAQ-adjacent content.

Full source list and reasoning: [docs/data-sources.md](docs/data-sources.md).

## Design decisions

Places this project deviates from the course lessons, and why:
[docs/decisions.md](docs/decisions.md).

## Evaluation

*(to be written once search and RAG evaluation are done — will map results
directly to the course's evaluation criteria so a reviewer can find them
quickly.)*

## Running it

*(setup instructions land once the ingestion pipeline and app are working
end to end.)*

## Project checklist

Tracking against the [LLM Zoomcamp evaluation criteria](https://github.com/DataTalksClub/llm-zoomcamp/blob/main/project.md#evaluation-criteria):

- [ ] Problem description
- [ ] Retrieval flow (knowledge base + LLM)
- [ ] Retrieval evaluation (multiple approaches compared)
- [ ] LLM evaluation (multiple approaches compared)
- [ ] Interface (Streamlit)
- [ ] Ingestion pipeline (Dagster, automated)
- [ ] Monitoring (feedback + dashboard, 5+ charts)
- [ ] Containerization (docker-compose)
- [ ] Reproducibility (clear setup, accessible data, pinned versions)
- [ ] Best practices: hybrid search, reranking, query rewriting
- [ ] Stretch: agentic tool use
- [ ] Stretch: cloud deployment
