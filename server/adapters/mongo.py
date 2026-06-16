"""Lazy Mongo adapter.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from collections.abc import Callable

from pymongo import MongoClient

from server.settings import ServerSettings


class LazyMongoDatabase:
    """Expose a Mongo database-like object without import-time client creation."""

    def __init__(self, settings_factory: Callable[[], ServerSettings] = ServerSettings.from_env, db_name: str = "lakatos"):
        self._settings_factory = settings_factory
        self._db_name = db_name
        self._client = None
        self._db = None

    def _get_db(self):
        if self._db is None:
            self._client = MongoClient(self._settings_factory().mongo_uri)
            self._db = self._client[self._db_name]
        return self._db

    @property
    def client(self):
        if self._client is None:
            self._get_db()
        return self._client

    def command(self, *args, **kwargs):
        return self._get_db().command(*args, **kwargs)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None

    def __getitem__(self, name):
        return self._get_db()[name]

    def __getattr__(self, name):
        return getattr(self._get_db(), name)
