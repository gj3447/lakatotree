"""Application ports for the Lakatos server.

Ports are the explicit test seam: application services depend on these
protocols, while runtime adapters live at the edge.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from typing import Any, Protocol


KgQuery = Callable[..., list[dict]]
KgTx = Callable[[Iterable[tuple[str, dict]]], list]
HistoryAppend = Callable[[str, str, str | None, dict | None], None]
PgFactory = Callable[[], AbstractContextManager[Any]]


class KgTxGuardFailed(RuntimeError):
    """The guarded first statement matched no row; raising inside the adapter rolls back the tx."""


class GuardedKgOps(list[tuple[str, dict]]):
    """Operation batch whose first result must contain a row or the managed transaction aborts."""

    require_first_result = True


class KgStore(Protocol):
    def query(self, cypher: str, **params: Any) -> list[dict]:
        ...

    def tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        ...


class HistoryStore(Protocol):
    def append(self, tree: str, op: str, node_tag: str | None = None, payload: dict | None = None) -> None:
        ...


class ArtifactStore(Protocol):
    def insert_artifact(self, tree: str, node_tag: str, kind: str, data: dict) -> None:
        ...
