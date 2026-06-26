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
from server.contexts.tree.writer import TreeKgWriter, TreeNotFound


def _svc(*, exists: bool, nodes: list, deleted: list):
    def kg(query, **p):
        if "RETURN t.title AS title" in query:        # load_tree_data 메타 — 미존재면 []→404
            return [{"title": "T", "hard_core": [], "frontier_rule": "", "doc": "",
                     "coverage_backlog": [], "coverage_statement": ""}] if exists else []
        if "ORDER BY tag" in query:                   # 노드 목록
            return nodes
        return []                                     # frontier 등

    def kg_tx(ops):
        deleted.append(ops)
        return [[{"t": 1}] for _ in ops]              # op1 RETURN t = 존재

    return TreeService(kg=kg, kg_tx=kg_tx, hist=lambda *a: None, pg=lambda: None)


def test_delete_missing_tree_is_404():
    with pytest.raises(HTTPException) as e:
        _svc(exists=False, nodes=[], deleted=[]).delete_tree("__missing__")
    assert e.value.status_code == 404


def test_delete_empty_tree_ok():
    deleted: list = []
    out = _svc(exists=True, nodes=[], deleted=deleted).delete_tree("T")
    assert out["ok"] is True and out["tree"] == "T" and out["deleted_nodes"] == 0
    assert deleted, "DETACH DELETE 실행됨"


def test_delete_nonempty_without_cascade_is_409_and_no_write():
    deleted: list = []
    with pytest.raises(HTTPException) as e:
        _svc(exists=True, nodes=[{"tag": "a"}], deleted=deleted).delete_tree("T")
    assert e.value.status_code == 409
    assert deleted == []   # 가드: 삭제 미실행 (typo 로 진짜 연구트리 날리기 방지)


def test_delete_nonempty_with_cascade_ok():
    deleted: list = []
    out = _svc(exists=True, nodes=[{"tag": "a"}, {"tag": "b"}], deleted=deleted).delete_tree("T", cascade=True)
    assert out["ok"] is True and out["deleted_nodes"] == 2 and out["cascade"] is True
    assert deleted


def test_writer_delete_tree_missing_raises():
    def kg_tx(ops):
        return [[] for _ in ops]   # op1 RETURN t = 0행 = 미존재
    with pytest.raises(TreeNotFound):
        TreeKgWriter(kg_tx).delete_tree("__missing__")


def test_mcp_delete_tree_tool(monkeypatch):
    seen: list = []
    monkeypatch.setattr(mcp, "_delete", lambda p: (seen.append(p), {"ok": True})[1])
    mcp.delete_tree("T", cascade=True)
    assert seen[0] == "/api/tree/T?cascade=true"


def test_cli_tree_delete(monkeypatch):
    calls: list = []
    monkeypatch.setattr(cli, "call", lambda m, p, b=None: (calls.append((m, p)), {"ok": True})[1])
    cli.main(["tree-delete", "T", "--cascade"])
    assert calls[0] == ("DELETE", "/api/tree/T?cascade=true")
    cli.main(["tree-delete", "T2"])
    assert calls[1] == ("DELETE", "/api/tree/T2")
