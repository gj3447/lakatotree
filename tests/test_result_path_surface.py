"""result_path 를 MCP 표면에 노출 — reproducible 게이트(F-CON-1)의 MCP-only 도달성 수정.

갭(SelfDev q-mcp-result-path-reproducible-gate, OmdEngine PROM 당김서 실측 2026-07-03):
REST NodeIn/ResultIn 은 result_path 를 받고 judgement 는 비파괴 병합(coalesce)까지 하는데,
MCP add_node/submit_result 래퍼가 이를 전달하지 않아 — 노드에 result_path 를 못 박음 →
_reproducible_for_node 가 영구 None → certificate 가 MCP-only 워크플로에서 4/5 상한.

이 테스트는 두 MCP 래퍼의 전달을 강제한다(표면 패리티, test_create_tree_surface 관례).
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / q-mcp-result-path-reproducible-gate
"""
from __future__ import annotations

import lakatos.mcp_server as mcp


def test_mcp_add_node_forwards_result_path(monkeypatch):
    seen: list = []
    monkeypatch.setattr(mcp, "_post", lambda p, b: (seen.append((p, b)), {"ok": True})[1])
    mcp.add_node("T", "n1", comment="c", result_path="results/receipt.json")
    path, body = seen[0]
    assert path == "/api/tree/T/node"
    assert body["result_path"] == "results/receipt.json"


def test_mcp_add_node_omits_empty_result_path_nondestructive(monkeypatch):
    """미지정 시 빈 문자열을 보내지 않는다 — NodeIn 기본값에 맡겨 기존 노드 upsert 시
    의도치 않은 초기화(빈값 덮어쓰기) 여지를 줄인다."""
    seen: list = []
    monkeypatch.setattr(mcp, "_post", lambda p, b: (seen.append((p, b)), {"ok": True})[1])
    mcp.add_node("T", "n1")
    assert "result_path" not in seen[0][1]


def test_mcp_submit_result_forwards_result_path(monkeypatch):
    seen: list = []
    monkeypatch.setattr(mcp, "_post", lambda p, b: (seen.append((p, b)), {"ok": True})[1])
    mcp.submit_result("T", "n1", 0.0, "pytest tests/x.py", result_path="results/receipt.json")
    path, body = seen[0]
    assert path == "/api/tree/T/node/n1/test_result"
    assert body["result_path"] == "results/receipt.json"
    assert body["metric_value"] == 0.0


def test_mcp_submit_result_omits_empty_result_path(monkeypatch):
    """미지정 시 미전송 — judgement 의 coalesce(nullif($rp,'')) 비파괴 병합과 합치."""
    seen: list = []
    monkeypatch.setattr(mcp, "_post", lambda p, b: (seen.append((p, b)), {"ok": True})[1])
    mcp.submit_result("T", "n1", 1.0, "pytest tests/x.py")
    assert "result_path" not in seen[0][1]
