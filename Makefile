# Garden Companion -- reproducible from-zero setup and common tasks.
# Run `make help` for the list. The full first-time path is `make setup`
# (populate the database) followed by `make up` (start the app + dashboard).

# DAGSTER_HOME must be an absolute path (Dagster requirement); $(CURDIR) is
# make's built-in absolute path to this directory.
DAGSTER_HOME := $(CURDIR)/.dagster_home
DAGSTER_RUN := DAGSTER_HOME=$(DAGSTER_HOME) uv run dagster job execute -f ingestion/definitions.py

.PHONY: help db-up init ingest ground-truth embed-questions setup \
        eval-search eval-rag up down clean

help:
	@echo "Garden Companion -- make targets"
	@echo ""
	@echo "  First-time setup (from an empty database):"
	@echo "    make setup           db up + schema + full ingestion + ground truth + question embeddings"
	@echo "    make up              build & start the chat app (:8501) and dashboard (:8502)"
	@echo ""
	@echo "  Individual steps:"
	@echo "    make db-up           start only the postgres container"
	@echo "    make init            create the database schema"
	@echo "    make ingest          run the full ingestion pipeline (fetch -> chunks -> embeddings)"
	@echo "    make ground-truth    generate LLM ground-truth questions"
	@echo "    make embed-questions embed ground-truth questions for evaluation"
	@echo ""
	@echo "  Evaluation:"
	@echo "    make eval-search     Hit Rate / MRR across strategies x methods"
	@echo "    make eval-rag        RAG answer quality A/B (LLM-as-judge)"
	@echo ""
	@echo "  Teardown:"
	@echo "    make down            stop containers (keeps data)"
	@echo "    make clean           stop containers AND delete the data volume (destructive)"

db-up:
	docker compose up -d postgres

init: db-up
	uv run python -m db.init_db

# Fetch books + fact sheets, split sections, chunk (3 strategies), embed.
# Headless -- no Dagster UI needed. mkdir keeps DAGSTER_HOME present (Dagster
# requires the directory to already exist).
ingest: init
	@mkdir -p $(DAGSTER_HOME)
	$(DAGSTER_RUN) -j full_ingestion_pipeline

ground-truth:
	@mkdir -p $(DAGSTER_HOME)
	$(DAGSTER_RUN) -j generate_ground_truth

embed-questions:
	uv run python -m eval.embed_questions

# The whole from-zero data path in dependency order.
setup: ingest ground-truth embed-questions
	@echo ""
	@echo "Setup complete. Start the app with: make up"

eval-search:
	uv run python -m eval.evaluate_search

eval-rag:
	uv run python -m eval.evaluate_rag

up:
	docker compose up -d --build

down:
	docker compose down

# Destroys the postgres volume -- you'll have to re-run `make setup` after.
clean:
	docker compose down -v
