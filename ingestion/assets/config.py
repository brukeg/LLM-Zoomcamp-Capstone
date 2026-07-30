"""Source lists for the fetch assets.

Single source of truth for what gets ingested -- docs/data-sources.md
explains the *reasoning* for these picks, this is the literal list the
pipeline runs against. Keep them in sync if you add titles/sheets.

This is a curated sample (8 books, 20 fact sheets across the categories
we care about), not the full catalog -- today's goal is clean raw text
landing for a sample of each, per the day-by-day plan. Widening to more
of Clemson's 850 fact sheets is a later, mechanical step (page through
`/wp-json/wp/v2/factsheet` instead of a fixed slug list).
"""

# (gutenberg_id, title, author)
GUTENBERG_BOOKS = [
    (9550, "Manual of Gardening (Second Edition)", "L. H. Bailey"),
    (34602, "The Practical Garden-Book", "L. H. Bailey and Charles Elias Hunn"),
    (22484, "Gardening Indoors and Under Glass", "F. F. Rockwell"),
    (21414, "Culinary Herbs: Their Cultivation, Harvesting, Curing and Uses", "M. G. Kains"),
    (16232, "The Culture of Vegetables and Flowers From Seeds and Roots", "Sutton & Sons Ltd."),
    (21682, "The Field and Garden Vegetables of America", "Fearing Burr"),
    (6117, "Success with Small Fruits", "Edward Payson Roe"),
    (10852, "Hardy Ornamental Flowering Trees and Shrubs", "Angus D. Webster"),
]

# Clemson HGIC fact sheet slugs, verified real (checked via search + the
# site's own WordPress REST API) before writing the fetch asset --
# spans vegetables, fruit, pests/diseases, and soil/fertility.
FACTSHEET_SLUGS = [
    # vegetables / general
    "tomato-basics",
    "potato",
    "carrot-beet-radish-parsnip",
    "cucumber",
    "container-vegetable-gardening",
    "vegetable-and-herb-crops-ranked-by-difficulty-for-home-gardeners",
    # soil / fertility
    "fertilizing-vegetables",
    "understanding-organic-fertility",
    "choosing-a-fertilizer",
    "cover-crops",
    # pests / diseases
    "tomato-diseases-disorders",
    "tomato-insect-pests",
    "root-knot-nematodes-in-the-vegetable-garden",
    "gardenia-diseases-other-problems",
    "crape-myrtle-diseases-insect-pests",
    # fruit
    "blueberry",
    "growing-strawberries",
    "pruning-trees",
    "pruning-peaches-nectarines",
    "blackberry",
]
