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
PgFactory = Callable[[], AbstractContextManager[Any]]


class KgTxGuardFailed(RuntimeError):
    """A managed-write guard rejected and rolled back the transaction.

    ``row`` preserves the immutable first-statement readback for callers that
    intentionally treat an exact prior receipt as a successful replay.  The
    row is evidence only: no later statement in the rejected batch ran.
    """

    def __init__(
        self,
        message: str,
        *,
        actual: Any = None,
        row: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.actual = actual
        self.row = row


class WriterFenceLost(KgTxGuardFailed):
    """The process no longer owns the cross-store runtime writer authority."""


class HistoryEventConflict(RuntimeError):
    """A stable history event id already names a different immutable row."""


class HistoryAppend(Protocol):
    def __call__(
        self,
        tree: str,
        op: str,
        node_tag: str | None = None,
        payload: dict | None = None,
        *,
        event_id: str | None = None,
    ) -> bool | None:
        ...


class GuardedKgOps(list[tuple[str, dict]]):
    """Managed batch with an in-callback first-result/value barrier.

    ``guard_expected`` may be a set/frozenset when more than one explicit
    terminal state is safe to commit (for example proceed or exact replay).
    """

    require_first_result = True

    def __init__(
        self,
        iterable: Iterable[tuple[str, dict]] = (),
        *,
        guard_field: str | None = None,
        guard_expected: Any = True,
    ) -> None:
        super().__init__(iterable)
        self.guard_field = guard_field
        self.guard_expected = guard_expected


class KgStore(Protocol):
    def query(self, cypher: str, **params: Any) -> list[dict]:
        ...

    def tx(self, ops: Iterable[tuple[str, dict]]) -> list:
        ...


class HistoryStore(Protocol):
    def append(
        self,
        tree: str,
        op: str,
        node_tag: str | None = None,
        payload: dict | None = None,
        *,
        event_id: str | None = None,
    ) -> None:
        ...


class ArtifactStore(Protocol):
    def insert_artifact(self, tree: str, node_tag: str, kind: str, data: dict) -> None:
        ...
