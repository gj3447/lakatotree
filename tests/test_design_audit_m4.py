"""M4 design-audit guard: writer 가 노드의 open_question 을 (e)-[:RAISES_QUESTION]->(q) 로 *실체화*한다.

결함(감사 M4): 읽기측 4곳(repository/read_models/judgement_service/laudan)이 RAISES_QUESTION 엣지를
보는데 writer 는 그 엣지를 한 번도 쓰지 않는다 → opened(n_opened) 가 라이브 KG 에서 항상 0 →
problem_balance(closed-opened) 붕괴(laudan 폐기판정 왜곡). 수정: add_node 가 open_question 이 있으면
OpenQuestion + RAISES_QUESTION(+HAS_FRONTIER) 엣지를 같은 tx 로 쓴다.
이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 M4 를 progressive 로 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import re

from lakatos.quant.laudan import branch_problem_balance_windowed
from server.contexts.tree.schemas import NodeIn
from server.contexts.tree.writer import TreeKgWriter


class _InMemoryRaisesQuestionGraph:
    """writer→KG→reader 진짜 왕복을 위한 *최소* 인메모리 그래프(monkeypatch dict 우회 아님).

    writer 가 실제로 발행하는 Cypher op 를 받아 RAISES_QUESTION 엣지를 *저장*하고(저장은 writer 가
    그 엣지를 써야만 생긴다), reader 가 보는 패턴 그대로(e.tag --RAISES_QUESTION--> q.name) 노드별
    questions 를 *역설계 재현*해 읽는다. open_question 스칼라는 절대 읽지 않는다 — 오직 엣지만.
    그래서 writer 가 엣지를 안 쓰면(수정 전) questions 가 비고 opened=0 (진짜 RED).
    """

    #: (e.tag)-[:RAISES_QUESTION]->(q.name) 로 머지된 엣지를 그대로 보관(라벨·방향·키 = reader 스키마).
    _RAISES = re.compile(
        r"MERGE\s*\(e\)-\[:RAISES_QUESTION\]->\(q\)", re.IGNORECASE)

    def __init__(self) -> None:
        self.tree_exists = True
        self.raises_edges: set[tuple[str, str]] = set()  # {(node_tag, q_name)}

    def __call__(self, ops):
        results = []
        for cypher, params in ops:
            # writer 가 RAISES_QUESTION 엣지를 *실제로* 쓰는 op 만 그래프에 실체화(엣지 저장).
            if self._RAISES.search(cypher):
                self.raises_edges.add((params["tag"], params["qname"]))
            # add_node 첫 op 의 존재확인 행(reader 의 TreeNotFound 백스톱 만족).
            results.append([{"t": 1}] if self.tree_exists else [])
        return results

    def read_node_questions(self, tag: str) -> list[str]:
        """reader 스키마 재현: (e {tag})-[:RAISES_QUESTION]->(q) | collect(DISTINCT q.name).
        스칼라 e.open_question 이 아니라 *저장된 엣지* 에서만 질문을 모은다(엣지 왕복 증명)."""
        return sorted({q for (t, q) in self.raises_edges if t == tag})


def test_raises_question_writer_roundtrip_opened_nonzero():
    """진짜 왕복: writer.add_node → 인메모리 KG(엣지 저장) → reader(엣지 읽기) → laudan.opened>0.

    monkeypatch dict 로 read-model 을 통째 주입(=결함 은폐)하지 않는다. 실제 TreeKgWriter 가 발행한
    RAISES_QUESTION 엣지를 그래프가 저장하고, reader 가 그 엣지에서 questions 를 모아 *진짜* laudan
    엔진의 problem_balance(opened) 계산을 태운다. writer 가 엣지를 안 쓰면 questions=[] → opened=0 → RED.
    """
    g = _InMemoryRaisesQuestionGraph()
    # (1) WRITE: 실제 writer 가 노드 + open_question 을 그래프에 쓴다(엣지 실체화는 writer 책임).
    TreeKgWriter(g).add_node(
        "T", NodeIn(tag="n", algorithm="problem", open_question="q-does-x-hold"), [])

    # (2) READ: reader 스키마(RAISES_QUESTION 엣지)로 노드별 questions 를 그래프에서 모은다.
    chain = [{"tag": "n", "questions": g.read_node_questions("n")}]
    frontier: list = []  # 닫힌 질문 없음 → closed=0; opened 만으로 RED/GREEN 가름.

    # 사전조건: 엣지가 정말 저장됐는지(왕복이 실제로 일어났는지) — 스칼라 우회 아님 증명.
    assert g.raises_edges == {("n", "q-does-x-hold")}, "writer→KG 엣지 미실체화(왕복 끊김)"

    # (3) COMPUTE: 불가침 laudan 엔진이 reader 가 읽은 questions 로 opened 를 센다.
    balance = branch_problem_balance_windowed(chain, frontier)
    opened = sum(len(r["questions"]) for r in chain)
    assert opened > 0, "writer 가 RAISES_QUESTION 엣지를 안 써 opened=0 (problem_balance 붕괴)"
    assert balance == -opened  # closed(0) - opened: 엣지가 살아야 수지가 음으로 내려간다.


def test_node_without_open_question_writes_no_raises_edge():
    """과잉 회귀가드: open_question 없으면 RAISES_QUESTION 엣지를 그래프에 쓰지 않는다(왕복도 빈손)."""
    g = _InMemoryRaisesQuestionGraph()
    TreeKgWriter(g).add_node("T", NodeIn(tag="n", algorithm="problem"), [])
    assert g.raises_edges == set()
    assert g.read_node_questions("n") == []
