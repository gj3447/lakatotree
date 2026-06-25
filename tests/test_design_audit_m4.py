"""M4 design-audit guard: writer 가 노드의 open_question 을 (e)-[:RAISES_QUESTION]->(q) 로 *실체화*한다.

결함(감사 M4): 읽기측 4곳(repository/read_models/judgement_service/laudan)이 RAISES_QUESTION 엣지를
보는데 writer 는 그 엣지를 한 번도 쓰지 않는다 → opened(n_opened) 가 라이브 KG 에서 항상 0 →
problem_balance(closed-opened) 붕괴(laudan 폐기판정 왜곡). 수정: add_node 가 open_question 이 있으면
OpenQuestion + RAISES_QUESTION(+HAS_FRONTIER) 엣지를 같은 tx 로 쓴다.
이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 M4 를 progressive 로 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter


def _flat(captured):
    return [(cy, p) for op_list in captured for (cy, p) in op_list]


def test_raises_question_writer_roundtrip_opened_nonzero():
    captured: list = []
    TreeKgWriter(lambda ops: captured.append(ops) or [[{"t": 1}] for _ in ops]).add_node(
        "T", NodeIn(tag="n", algorithm="problem", open_question="q-does-x-hold"), [])
    flat = _flat(captured)
    # ★구조적(non-vacuous): RAISES_QUESTION 엣지를 *실제로* 쓰는 op 이 있어야(수정 없으면 RED)
    assert any("RAISES_QUESTION" in cy for cy, _ in flat), "writer 가 RAISES_QUESTION 을 미실체화"
    assert any(p.get("qname") == "q-does-x-hold" for _, p in flat)


def test_node_without_open_question_writes_no_raises_edge():
    """과잉 회귀가드: open_question 없으면 RAISES_QUESTION op 를 쓰지 않는다."""
    captured: list = []
    TreeKgWriter(lambda ops: captured.append(ops) or [[{"t": 1}] for _ in ops]).add_node(
        "T", NodeIn(tag="n", algorithm="problem"), [])
    assert not any("RAISES_QUESTION" in cy for cy, _ in _flat(captured))
