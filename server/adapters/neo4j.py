"""Lazy Neo4j adapter.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from collections.abc import Callable

from neo4j import GraphDatabase

from server.settings import ServerSettings


class LazyNeo4jDriver:
    """Create the Neo4j driver only when a session is actually needed."""

    def __init__(
        self,
        settings_factory: Callable[[], ServerSettings] = ServerSettings.from_env,
        credential_profile: str = "runtime",
        **driver_config,
    ):
        if credential_profile not in {"runtime", "migration"}:
            raise ValueError("Neo4j credential profile must be runtime or migration")
        self._settings_factory = settings_factory
        self._credential_profile = credential_profile
        self._driver_config = dict(driver_config)
        self._driver = None
        self._database = None

    def _get_driver(self):
        if self._driver is None:
            settings = self._settings_factory()
            if self._credential_profile == "migration":
                uri, user, password = settings.require_neo4j_migration()
            else:
                uri, user, password = settings.require_neo4j()
            self._database = settings.require_neo4j_database()
            self._driver = GraphDatabase.driver(
                uri, auth=(user, password), **self._driver_config
            )
        return self._driver

    def session(self, *args, **kwargs):
        driver = self._get_driver()
        requested = kwargs.get("database")
        if requested is not None and requested != self._database:
            raise RuntimeError("Neo4j session database differs from NEO4J_DATABASE")
        kwargs.setdefault("database", self._database)
        return driver.session(*args, **kwargs)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            self._database = None
