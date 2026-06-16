"""Dependency bundle for application services.

# KG: span_lakatotree_server_architecture
"""

from __future__ import annotations

from dataclasses import dataclass

from server.ports import HistoryAppend, KgQuery, KgTx, PgFactory


@dataclass(frozen=True)
class AppDeps:
    kg: KgQuery
    kg_tx: KgTx
    hist: HistoryAppend
    pg: PgFactory
