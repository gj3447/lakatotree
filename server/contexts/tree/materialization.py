"""Dry-run planning for tree KG materialization.

# KG: seed-lkt-engine-materialization-dryrun-20260616
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from server.contexts.tree.schemas import NodeIn, ParentEdgeIn


@dataclass(frozen=True)
class MaterializationPlan:
    tree: str
    node_chunks: list[int]
    edge_chunks: list[int]
    question_chunks: list[int]
    node_count: int
    edge_count: int
    question_count: int

    @property
    def tx_count(self) -> int:
        return 1 + len(self.node_chunks) + len(self.edge_chunks) + len(self.question_chunks)

    @property
    def op_count(self) -> int:
        return self.tx_count

    @property
    def rows(self) -> int:
        return 1 + self.node_count + self.edge_count + self.question_count

    def to_dict(self) -> dict:
        return {
            "dry_run": True,
            "tree": self.tree,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "question_count": self.question_count,
            "node_chunks": self.node_chunks,
            "edge_chunks": self.edge_chunks,
            "question_chunks": self.question_chunks,
            "tx_count": self.tx_count,
            "op_count": self.op_count,
            "rows": self.rows,
        }


class TreeMaterializationPlanner:
    """Predict write chunks and row counts before KG mutation."""

    # KG: seed-lkt-engine-materialization-dryrun-20260616

    def __init__(self, *, chunk_size: int = 100):
        self.chunk_size = max(1, chunk_size)

    def plan(
        self,
        spec,
        *,
        parent_edges_by_tag: Mapping[str, Sequence[ParentEdgeIn]] | None = None,
    ) -> MaterializationPlan:
        nodes = tuple(spec.nodes)
        questions = tuple(spec.questions)
        parent_edges = parent_edges_by_tag or _parent_edges_from_nodes(nodes)
        edge_count = sum(len(edges) for edges in parent_edges.values())
        return MaterializationPlan(
            tree=spec.name,
            node_chunks=_chunk_lengths(len(nodes), self.chunk_size),
            edge_chunks=_chunk_lengths(edge_count, self.chunk_size),
            question_chunks=_chunk_lengths(len(questions), self.chunk_size),
            node_count=len(nodes),
            edge_count=edge_count,
            question_count=len(questions),
        )


def _chunk_lengths(count: int, chunk_size: int) -> list[int]:
    return [min(chunk_size, count - start) for start in range(0, count, chunk_size)]


def _parent_edges_from_nodes(nodes: Sequence[NodeIn]) -> dict[str, list[ParentEdgeIn]]:
    out: dict[str, list[ParentEdgeIn]] = {}
    for node in nodes:
        edges: dict[str, ParentEdgeIn] = {}
        if node.parent:
            edges[node.parent] = ParentEdgeIn(tag=node.parent)
        for parent in node.parents:
            edges.setdefault(parent, ParentEdgeIn(tag=parent))
        for edge in node.parent_edges:
            edges[edge.tag] = edge
        out[node.tag] = list(edges.values())
    return out
