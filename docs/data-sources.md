# Data Sources

Two tiers, chosen deliberately: large public-domain books (the "big document"
chunking problem) and small structured fact sheets (clean, FAQ-adjacent
ground truth). Neither is committed to the repo — both are fetched at
ingestion time, same pattern the course uses for the DTC FAQ dataset. This
keeps the repo small and keeps "the dataset is accessible" true for a
reviewer who clones and runs the ingestion job.

## Tier 1: Books (Project Gutenberg)

Public domain, no licensing concerns, plain-text download at a predictable
URL: `https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt`

Picked for being practical/reference material rather than memoir or poetry —
these actually answer gardening questions. The authoritative list of 8
titles is in [`ingestion/assets/config.py`](../ingestion/assets/config.py)
(`GUTENBERG_BOOKS`) — code is the source of truth so it can't drift from
what the pipeline actually fetches; this doc explains the reasoning.

More can be added later from the [Gardening](https://www.gutenberg.org/ebooks/subject/1242)
and [Horticulture](https://www.gutenberg.org/ebooks/bookshelf/43) shelves.

Note: `gutendex.com` (the usual JSON API for querying Gutenberg metadata) was
blocked by my sandbox's network allowlist when I tried to verify it, so the
book list was picked by hand-browsing `gutenberg.org`'s subject/bookshelf
pages instead, and the fetch asset hits `gutenberg.org` directly (also
verified reachable) rather than going through gutendex. Fine either way —
gutendex would only matter if you want to script the discovery step instead
of a fixed ID list.

## Tier 2: Fact sheets (Clemson HGIC)

[Clemson Cooperative Extension's Home & Garden Information Center](https://hgic.clemson.edu/all-factsheets/)
publishes 850+ fact sheets. Better than that: they're a registered WordPress
custom post type with a working REST API —
`https://hgic.clemson.edu/wp-json/wp/v2/factsheet?slug={slug}` returns clean
JSON with `content.rendered` holding just the article HTML, no site chrome
(no nav, no related-posts widget, no footer). Confirmed by fetching the
`tomato-basics` factsheet directly. This is what the fetch asset uses
instead of scraping rendered HTML pages — much less fragile.

The curated list of 20 slugs (spanning vegetables, fruit, pests & diseases,
soil/fertility) is in
[`ingestion/assets/config.py`](../ingestion/assets/config.py)
(`FACTSHEET_SLUGS`), verified real before being added — not the full 850.
Widening later is mechanical: page through the `/wp-json/wp/v2/factsheet`
collection endpoint instead of a fixed slug list.

Licensing: Clemson HGIC is a public state extension service. Content isn't
under an explicit open license like UF/IFAS EDIS (CC BY-NC-ND), so treat
this as fair-use / non-commercial educational use — fetch at runtime, don't
redistribute the scraped text in the repo, and cite the source in the app's
answers where practical.

## Considered, not used (for now)

- **UF/IFAS EDIS** (`edis.ifas.ufl.edu`) — 6,500+ publications, explicitly
  CC BY-NC-ND licensed as of 2024, which is actually cleaner licensing than
  Clemson. Good candidate to add as a second fact-sheet source if there's
  time after the core pipeline works — same asset shape, different scraper.
- **Whole-book gardening content beyond Gutenberg** — anything still under
  copyright is out; it would break reproducibility (can't redistribute) and
  isn't worth the legal ambiguity for a course project.
