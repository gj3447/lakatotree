"""delete_tree 를 REST/MCP/CLI 에 대칭 노출 — create_tree 의 짝(create/delete 비대칭 해소).

안전 설계(파괴적 op): missing-tree=fail-loud 404 · empty-guard(노드 있으면 409, cascade=true 로만 전체삭제).
# KG: span_lakatotree_create_tree_surface
"""
from __future__ import annotations

import lakatos.cli as cli
import lakatos.mcp_server as mcp
import pytest
from fastapi import HTTPException

from server.contexts.tree.service import TreeService
from server.contexts.tree.writer import (
    TreeHistoryProtected,
    TreeIdempotencyConflict,
    TreeIncarnationConflict,
    TreeKgWriter,
    TreeNotFound,
    TreeNotEmpty,
)
from server.ports import KgTxGuardFailed


def _svc(*, exists: bool, nodes: list, deleted: list):
    def kg(query, **p):
        if "RETURN t.title AS title" in query:        # load_tree_data 메타 — 미존재면 []→404
            return [{"title": "T", "hard_core": [], "frontier_rule": "", "doc": "",
                     "coverage_backlog": [], "coverage_statement": ""}] if exists else []
        if "ORDER BY tag" in query:                   # 노드 목록
            return nodes
        return []                                     # frontier 등

    def kg_tx(ops):
        if not exists:
            return [[], [{"nodes_locked": 0}], [{"questions_locked": 0}], []]
        cascade = bool(ops[-1][1]["cascade"])
        state = "nonempty" if nodes and not cascade else "deleted"
        if state == "deleted":
            deleted.append(ops)
        return [
            [{"tree": "T"}],
            [{"nodes_locked": len(nodes)}],
            [{"questions_locked": 0}],
            [{"state": state, "node_count": len(nodes)}],
        ]

    return TreeService(
        kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None, pg=lambda: None
    )


def test_delete_missing_tree_is_404():
    with pytest.raises(HTTPException) as e:
        _svc(exists=False, nodes=[], deleted=[]).delete_tree(
            "__missing__", idempotency_key="delete-missing"
        )
    assert e.value.status_code == 404


def test_delete_requires_valid_idempotency_key_before_writer():
    service = _svc(exists=True, nodes=[], deleted=[])
    with pytest.raises(HTTPException) as missing:
        service.delete_tree("T")
    with pytest.raises(HTTPException) as malformed:
        service.delete_tree("T", idempotency_key="bad\nkey")
    assert missing.value.status_code == malformed.value.status_code == 422


def test_delete_empty_tree_ok():
    deleted: list = []
    out = _svc(exists=True, nodes=[], deleted=deleted).delete_tree(
        "T", idempotency_key="delete-empty"
    )
    assert out["ok"] is True and out["tree"] == "T" and out["deleted_nodes"] == 0
    assert deleted, "DETACH DELETE 실행됨"


def test_delete_nonempty_without_cascade_is_409_and_no_write():
    deleted: list = []
    with pytest.raises(HTTPException) as e:
        _svc(exists=True, nodes=[{"tag": "a"}], deleted=deleted).delete_tree(
            "T", idempotency_key="delete-nonempty"
        )
    assert e.value.status_code == 409
    assert deleted == []   # 가드: 삭제 미실행 (typo 로 진짜 연구트리 날리기 방지)


def test_delete_nonempty_with_cascade_ok():
    deleted: list = []
    out = _svc(exists=True, nodes=[{"tag": "a"}, {"tag": "b"}], deleted=deleted).delete_tree(
        "T", cascade=True, idempotency_key="delete-cascade"
    )
    assert out["ok"] is True and out["deleted_nodes"] == 2 and out["cascade"] is True
    assert deleted


def test_writer_delete_tree_missing_raises():
    def kg_tx(ops):
        return [[] for _ in ops]   # op1 RETURN t = 0행 = 미존재
    with pytest.raises(TreeNotFound):
        TreeKgWriter(kg_tx).delete_tree(
            "__missing__", idempotency_key="delete-missing"
        )


def test_writer_delete_tree_recovers_ambiguous_commit_from_exact_intent():
    captured = []

    def kg_tx(ops):
        captured.extend(ops)
        return [
            [{
                "tree": None,
                "guard_status": "already_committed",
                "prior_event_id": ops[0][1]["event_id"],
                "prior_deleted_nodes": 3,
                "prior_event_ts": "2026-08-02T00:00:00+00:00",
                "prior_superseded": False,
            }],
            [{"nodes_locked": 0}],
            [{"questions_locked": 0}],
            [],
        ]

    out = TreeKgWriter(kg_tx).delete_tree(
        "T", cascade=True, idempotency_key="ambiguous-delete"
    )

    assert out["deleted_nodes"] == 3
    assert out["event_id"] == captured[0][1]["event_id"]
    assert all("$event_id" in query for query, _ in captured)
    assert "deleted_nodes:size(nodes)" in captured[3][0]


class _DeleteAtomicTx:
    """Durable delete stand-in with incarnation-aware replay semantics."""

    def __init__(self):
        self.trees = {"T": {"tree_incarnation_id": "inc-old", "nodes": 2}}
        self.outboxes = {}

    def __call__(self, ops):
        batch = list(ops)
        params = batch[0][1]
        tree = params["tree"]
        event_id = params["event_id"]
        current = self.trees.get(tree)
        prior = self.outboxes.get(event_id)
        if prior is not None:
            exact = (
                prior["payload"] == params["payload"]
                and prior["request_sha256"] == params["request_sha256"]
                and prior["idempotency_key_sha256"]
                    == params["idempotency_key_sha256"]
            )
            if exact and (
                current is None
                or current["tree_incarnation_id"] != prior["tree_incarnation_id"]
            ):
                return [[{
                    "tree": None if current is None else tree,
                    "guard_status": "already_committed",
                    "prior_event_id": event_id,
                    "prior_deleted_nodes": prior["deleted_nodes"],
                    "prior_event_ts": prior["created_at"],
                    "prior_superseded": current is not None,
                }], [], [], []]
            raise KgTxGuardFailed(
                "guarded first statement rejected: 'intent_conflict'",
                actual="intent_conflict",
            )
        if current is None:
            raise KgTxGuardFailed(
                "guarded first statement rejected: 'not_found'",
                actual="not_found",
            )
        if params.get("require_incarnation_match") and (
            current.get("tree_incarnation_id")
            != params.get("expected_incarnation_id")
        ):
            raise KgTxGuardFailed(
                "guarded first statement rejected: 'incarnation_conflict'",
                actual="incarnation_conflict",
            )
        current.setdefault("tree_incarnation_id", params["incarnation_id"])
        node_count = current["nodes"]
        if node_count and (
            batch[3][1]["require_empty"] or not batch[3][1]["cascade"]
        ):
            return [[{"tree": tree, "guard_status": "proceed"}], [], [], [{
                "state": "nonempty", "node_count": node_count,
            }]]
        final_params = batch[3][1]
        self.outboxes[event_id] = {
            "payload": params["payload"],
            "request_sha256": params["request_sha256"],
            "idempotency_key_sha256": params["idempotency_key_sha256"],
            "tree_incarnation_id": current["tree_incarnation_id"],
            "deleted_nodes": node_count,
            "created_at": final_params["ts"],
        }
        del self.trees[tree]
        return [[{"tree": tree, "guard_status": "proceed"}], [], [], [{
            "state": "deleted", "node_count": node_count,
        }]]


def test_delete_retry_after_recreate_preserves_new_incarnation():
    tx = _DeleteAtomicTx()
    writer = TreeKgWriter(tx)

    first = writer.delete_tree(
        "T", cascade=True, idempotency_key="logical-delete-1"
    )
    tx.trees["T"] = {"tree_incarnation_id": "inc-new", "nodes": 0}
    replay = writer.delete_tree(
        "T", cascade=True, idempotency_key="logical-delete-1"
    )

    assert first["idempotent"] is False
    assert replay["idempotent"] is True and replay["superseded"] is True
    assert tx.trees["T"]["tree_incarnation_id"] == "inc-new"


def test_delete_key_reuse_with_different_cascade_is_conflict():
    tx = _DeleteAtomicTx()
    writer = TreeKgWriter(tx)
    writer.delete_tree("T", cascade=True, idempotency_key="logical-delete-1")

    with pytest.raises(TreeIdempotencyConflict):
        writer.delete_tree(
            "T", cascade=False, idempotency_key="logical-delete-1"
        )

    assert len(tx.outboxes) == 1


def test_first_delete_rejects_stale_selected_incarnation():
    tx = _DeleteAtomicTx()
    tx.trees["T"] = {"tree_incarnation_id": "inc-new", "nodes": 0}

    with pytest.raises(TreeIncarnationConflict):
        TreeKgWriter(tx).delete_tree(
            "T",
            cascade=True,
            idempotency_key="janitor-selected-old",
            require_incarnation_match=True,
            expected_incarnation_id="inc-old",
        )

    assert tx.trees["T"]["tree_incarnation_id"] == "inc-new"
    assert tx.outboxes == {}


def test_writer_require_empty_rechecks_under_lock_and_preserves_late_node():
    tx = _DeleteAtomicTx()
    writer = TreeKgWriter(tx)

    with pytest.raises(TreeNotEmpty):
        writer.delete_tree(
            "T",
            cascade=True,
            idempotency_key="janitor-late-node",
            require_empty=True,
        )

    assert tx.trees["T"]["nodes"] == 2
    assert tx.outboxes == {}


def test_delete_query_binds_require_empty_into_final_state_and_intent():
    captured = []

    def kg_tx(ops):
        captured.extend(ops)
        return [
            [{"tree": "T", "guard_status": "proceed"}],
            [{"nodes_locked": 1}],
            [{"questions_locked": 0}],
            [{"state": "nonempty", "node_count": 1}],
        ]

    with pytest.raises(TreeNotEmpty):
        TreeKgWriter(kg_tx).delete_tree(
            "T",
            cascade=True,
            idempotency_key="require-empty-contract",
            require_empty=True,
        )
    assert "$require_empty OR NOT $cascade" in captured[3][0]
    assert captured[3][1]["require_empty"] is True
    assert '"require_empty":true' in captured[0][1]["payload"]


@pytest.mark.parametrize(
    "history",
    [
        {"argument_history": 1, "critique_history": 0},
        {"argument_history": 0, "critique_history": 1},
    ],
)
def test_writer_delete_tree_locks_and_blocks_critique_history(history):
    captured = []

    def kg_tx(ops):
        captured.extend(ops)
        return [
            [{"tree": "T"}],
            [{"nodes_locked": 1}],
            [{"questions_locked": 0}],
            [{"state": "history", "node_count": 1}],
        ]

    with pytest.raises(TreeHistoryProtected):
        TreeKgWriter(kg_tx).delete_tree(
            "T", idempotency_key="history-protected"
        )

    assert "t._tree_write_cas=coalesce(t._tree_write_cas,0)+0" in captured[0][0]
    assert "HAS_ARGUMENT" not in captured[0][0], "child guard must follow the t lock"
    assert "Argument" in captured[3][0]
    assert "OutboxEntry {tree:$tree, op:'critique'}" in captured[3][0]
    assert "tree_delete_commit_intent" in captured[3][0]


def test_mcp_delete_tree_tool(monkeypatch):
    seen: list = []
    monkeypatch.setattr(
        mcp,
        "_delete",
        lambda p, **kwargs: (seen.append((p, kwargs)), {"ok": True})[1],
    )
    mcp.delete_tree("T", "mcp-delete", cascade=True)
    assert seen[0] == (
        "/api/tree/T?cascade=true", {"idempotency_key": "mcp-delete"}
    )


def test_cli_tree_delete(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        cli,
        "call",
        lambda m, p, b=None, **kwargs: (
            calls.append((m, p, kwargs)), {"ok": True}
        )[1],
    )
    cli.main(["tree-delete", "T", "--cascade", "--idempotency-key", "cli-1"])
    assert calls[0] == (
        "DELETE",
        "/api/tree/T?cascade=true",
        {"extra_headers": {"Idempotency-Key": "cli-1"}},
    )
    cli.main(["tree-delete", "T2", "--idempotency-key", "cli-2"])
    assert calls[1] == (
        "DELETE",
        "/api/tree/T2",
        {"extra_headers": {"Idempotency-Key": "cli-2"}},
    )
