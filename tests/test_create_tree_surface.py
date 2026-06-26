"""create_tree 를 REST(service) / MCP / CLI 세 표면에 first-class 노출 — 온보딩 갭 수정.

기존엔 트리 생성이 어느 표면에도 없어(POST /api/tree/{name} = 405, MCP/CLI 툴 없음), 신규 트리에
add_node 하면 404("나무 없음")만 받고 트리를 만들 길이 없었다. 이 테스트가 세 표면의 노출을 강제한다.
# KG: span_lakatotree_create_tree_surface
"""
from __future__ import annotations

import lakatos.cli as cli
import lakatos.mcp_server as mcp
from server.contexts.tree.schemas import CreateTreeIn
from server.contexts.tree.service import TreeService


def _svc(captured: list):
    def kg(query, **params):
        return [{"ok": True}]

    def kg_tx(ops):
        captured.append(ops)
        return [[{"ok": True}] for _ in ops]

    return TreeService(kg=kg, kg_tx=kg_tx, hist=lambda *a: None, pg=lambda: None)


def test_service_create_tree_merges_tree_and_returns_ok():
    captured: list = []
    out = _svc(captured).create_tree("T", CreateTreeIn(title="t", hard_core="HC", frontier_rule="FR"))
    assert out["ok"] is True and out["tree"] == "T"
    flat = [(cy, p) for op_list in captured for (cy, p) in op_list]
    assert any("MERGE (t:LakatosTree" in cy for cy, _ in flat), "tree MERGE op 없음"
    assert any(p.get("tree") == "T" and p.get("hard_core") == "HC" for _, p in flat)


def test_mcp_create_tree_tool_posts_to_tree_route(monkeypatch):
    seen: list = []
    monkeypatch.setattr(mcp, "_post", lambda p, b: (seen.append((p, b)), {"ok": True})[1])
    mcp.create_tree("T", hard_core="HC", frontier_rule="FR", coverage_backlog_csv="a, b")
    assert seen[0][0] == "/api/tree/T"
    assert seen[0][1]["hard_core"] == "HC" and seen[0][1]["frontier_rule"] == "FR"
    assert seen[0][1]["coverage_backlog"] == ["a", "b"]   # REST/CLI 와 표면 패리티


def test_cli_tree_create_posts(monkeypatch):
    calls: list = []
    monkeypatch.setattr(cli, "call", lambda m, p, b=None: (calls.append((m, p, b)), {"ok": True})[1])
    cli.main(["tree-create", "T", "--hard-core", "HC", "--frontier-rule", "FR"])
    assert calls[0][0] == "POST" and calls[0][1] == "/api/tree/T"
    assert calls[0][2]["hard_core"] == "HC" and calls[0][2]["frontier_rule"] == "FR"
