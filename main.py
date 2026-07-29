"""Quick environment sanity check.

Run after `uv sync` and setting up `.env` to confirm the basics work
before touching the ingestion pipeline:

    uv run python main.py
"""

import os

from dotenv import load_dotenv


def main():
    load_dotenv()

    checks = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "POSTGRES_HOST": os.getenv("POSTGRES_HOST", "(not set, defaults to localhost)"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB", "(not set, defaults to garden_companion)"),
    }

    print("Environment check:")
    for key, value in checks.items():
        print(f"  {key}: {value}")

    if not checks["OPENAI_API_KEY"]:
        print("\nMissing OPENAI_API_KEY -- copy .env.example to .env and fill it in.")


if __name__ == "__main__":
    main()
