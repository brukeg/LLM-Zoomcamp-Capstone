"""Dagster resources shared across ingestion assets."""

import dagster as dg

from db.connection import get_db_connection


class PostgresResource(dg.ConfigurableResource):
    """Thin wrapper so assets get a connection via Dagster's resource system
    instead of importing db.connection directly. Same connection logic
    either way (env vars, defaults matching docker-compose.yaml) -- this
    just makes it swappable/testable the way Dagster expects.
    """

    def get_connection(self):
        return get_db_connection()
