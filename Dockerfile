# Image for the Streamlit chat app and the monitoring dashboard (same image,
# different command per compose service). Postgres is a separate service --
# see docker-compose.yaml.
FROM python:3.12-slim

# uv, copied from its official image rather than pip-installed, so the
# container uses the same package manager the project is developed with and
# honors uv.lock exactly.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency manifests first, so `uv sync` is cached and only re-runs when
# deps actually change -- not on every source edit.
COPY pyproject.toml uv.lock ./

# --frozen: fail rather than silently drift from uv.lock.
# --no-dev: skip the jupyter dev dependency.
# --no-install-project: the app runs from source (streamlit puts the repo
#   root on sys.path), and pyproject declares no build-system, so there's
#   nothing to build/install for the root package itself -- just its deps.
RUN uv sync --frozen --no-dev --no-install-project

COPY . .

EXPOSE 8501

# Invoke the venv's streamlit binary directly (uv sync created /app/.venv)
# rather than `uv run`, which would re-check/re-sync the environment at
# startup and can trip over --no-install-project. The app's own sys.path
# shim puts the repo root (/app) on the path, so imports resolve.
# --server.address=0.0.0.0 makes the port reachable from outside the
# container; --headless stops streamlit trying to open a browser.
CMD [".venv/bin/streamlit", "run", "app/main.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
