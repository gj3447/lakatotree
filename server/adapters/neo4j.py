"""Lazy Neo4j adapter.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from collections.abc import Callable

from neo4j import GraphDatabase

from server.settings import ServerSettings


class LazyNeo4jDriver:
    """Create the Neo4j driver only when a session is actually needed."""

    def __init__(self, settings_factory: Callable[[], ServerSettings] = ServerSettings.from_env):
        self._settings_factory = settings_factory
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            uri, user, password = self._settings_factory().require_neo4j()
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
        return self._driver

    def session(self, *args, **kwargs):
        return self._get_driver().session(*args, **kwargs)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
