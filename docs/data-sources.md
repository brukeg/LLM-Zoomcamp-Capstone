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
these actually answer gardening questions:

| ID    | Title                                                          | Author(s)                  |
|-------|-----------------------------------------------------------------|-----------------------------|
| 9550  | Manual of Gardening (Second Edition)                             | L. H. Bailey                |
| 34602 | The Practical Garden-Book                                        | L. H. Bailey & C. E. Hunn   |
| 22484 | Gardening Indoors and Under Glass                                 | F. F. Rockwell              |
| 21414 | Culinary Herbs: Their Cultivation, Harvesting, Curing and Uses    | M. G. Kains                 |
| 16232 | The Culture of Vegetables and Flowers From Seeds and Roots        | Sutton & Sons Ltd.           |
| 21682 | The Field and Garden Vegetables of America                        | Fearing Burr                |
| 6117  | Success with Small Fruits                                         | Edward Payson Roe           |
| 10852 | Hardy Ornamental Flowering Trees and Shrubs                       | Angus D. Webster            |

More can be added later from the [Gardening](https://www.gutenberg.org/ebooks/subject/1242)
and [Horticulture](https://www.gutenberg.org/ebooks/bookshelf/43) shelves —
the fetch asset takes a list of IDs, so this table is the single place to
extend the corpus.

Note: `gutendex.com` (the usual JSON API for querying Gutenberg metadata) was
blocked by my sandbox's network allowlist when I tried to verify it, so this
list was built by hand-browsing `gutenberg.org`'s subject/bookshelf pages
instead — that part worked fine. Your environment (Codespace or local)
shouldn't have this restriction; worth double checking `gutendex.com` is
reachable if you want to script the discovery step instead of using a fixed
ID list.

## Tier 2: Fact sheets (Clemson HGIC)

[Clemson Cooperative Extension's Home & Garden Information Center](https://hgic.clemson.edu/all-factsheets/)
publishes 850+ fact sheets as individual HTML pages under one consistent
site structure — one source instead of stitching together several
university extension sites with different templates. Topics span
vegetables, fruit, ornamentals, pests/diseases, soils, and trees/shrubs.

For the initial pipeline, scope to a handful of categories (vegetables,
fruit, pests & diseases, soils & fertility) rather than all 850 — enough
for solid ground truth without a scraping job that takes all day. Easy to
widen later since it's the same asset with a different category filter.

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
