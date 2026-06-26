"""OOPTDD emit-adapter — LakatoTree 설계감사 M4(writer 가 open_question 을 RAISES_QUESTION 엣지로
*실체화*) 를 구조화 이벤트 trace(R02)로 영수증화. Longinus 바인딩(R10): emit site=verify.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 server/contexts/tree/writer.py,
lakatos/quant/laudan.py 는 불변·재구현 금지). verify 가 실제 TreeKgWriter.add_node 를 *구동*해
RAISES_QUESTION 엣지를 그래프에 실체화하고, reader 스키마로 다시 읽어 진짜 laudan 엔진의
problem_balance(opened)를 태운 뒤, 관측 사실을 구조화 이벤트로 ship.

차용: tests/test_design_audit_m4.py 의 _InMemoryRaisesQuestionGraph 왕복(monkeypatch dict 우회 아님)을
그대로 가져와 결함이 있었다면(=writer 가 엣지를 안 쓰면) 음성으로 갈라지는 진짜 케이스를 구동한다.
"""
import re
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

# 실제 고쳐진 모듈을 import(재구현 금지) — fastapi 가 schemas 체인으로 따라온다(ooptdd-loop env 설치됨).
from lakatos.quant.laudan import branch_problem_balance_windowed  # noqa: E402
from server.contexts.tree.schemas import NodeIn                    # noqa: E402
from server.contexts.tree.writer import TreeKgWriter               # noqa: E402


class _InMemoryRaisesQuestionGraph:
    """writer→KG→reader 진짜 왕복(테스트 픽스처 차용). writer 가 실제 발행한
    MERGE (e)-[:RAISES_QUESTION]->(q) op 만 그래프에 엣지로 *저장*하고(엣지는 writer 가 써야만
    생긴다), reader 는 e.open_question 스칼라를 절대 읽지 않고 *저장된 엣지* 에서만 questions 를
    모은다. writer 가 엣지를 안 쓰면(수정 전) questions 가 비고 opened=0 → 음성(진짜 RED)."""

    _RAISES = re.compile(r"MERGE\s*\(e\)-\[:RAISES_QUESTION\]->\(q\)", re.IGNORECASE)

    def __init__(self) -> None:
        self.tree_exists = True
        self.raises_edges: set[tuple[str, str]] = set()  # {(node_tag, q_name)}

    def __call__(self, ops):
        results = []
        for cypher, params in ops:
            if self._RAISES.search(cypher):
                self.raises_edges.add((params["tag"], params["qname"]))
            results.append([{"t": 1}] if self.tree_exists else [])
        return results

    def read_node_questions(self, tag: str) -> list[str]:
        return sorted({q for (t, q) in self.raises_edges if t == tag})


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M4", "event": name, **attrs}


def verify(backend, cid):
    """M4 구동 — open_question 을 가진 노드를 실제 TreeKgWriter 로 쓰면 RAISES_QUESTION 엣지가
    실체화되고, reader 가 그 엣지에서 questions 를 모아 진짜 laudan opened>0 을 본다.
    음성 오라클: open_question 없는 노드는 엣지를 절대 쓰지 않는다(opened=0)."""

    # ── (A) POSITIVE 왕복: 실제 writer → 인메모리 KG(엣지 저장) → reader(엣지 읽기) → laudan opened>0.
    g = _InMemoryRaisesQuestionGraph()
    TreeKgWriter(g).add_node(
        "T", NodeIn(tag="n", algorithm="problem", open_question="q-does-x-hold"), [])

    # 엣지가 정말 실체화됐는지(왕복이 실제로 일어났는지) — 스칼라 우회 아님 증명.
    assert g.raises_edges == {("n", "q-does-x-hold")}, \
        f"writer→KG RAISES_QUESTION 엣지 미실체화(왕복 끊김): {g.raises_edges}"
    chain = [{"tag": "n", "questions": g.read_node_questions("n")}]
    assert chain[0]["questions"] == ["q-does-x-hold"], chain
    backend.ship([_ev(cid, "raises_question_edge_written",
                      tag="n", qname="q-does-x-hold",
                      edge_count=len(g.raises_edges))])

    # 진짜 불가침 laudan 엔진으로 opened 를 센다(reader 가 읽은 questions 로).
    frontier: list = []                       # 닫힌 질문 없음 → closed=0.
    balance = branch_problem_balance_windowed(chain, frontier)
    opened = sum(len(r["questions"]) for r in chain)
    assert opened > 0, "writer 가 RAISES_QUESTION 엣지를 안 써 opened=0 (problem_balance 붕괴)"
    assert balance == -opened, (balance, opened)   # closed(0)-opened: 엣지가 살아야 수지가 음으로.
    backend.ship([_ev(cid, "opened_nonzero_after_roundtrip",
                      opened=opened, balance=balance)])

    # ── (B) NEGATIVE 오라클: open_question 없는 노드는 RAISES_QUESTION 엣지를 쓰지 않는다.
    #     결함이 있었다면(writer 가 무조건 엣지를 쓰거나 스칼라만 보던 reader 라면) 여기서 틀린다.
    g2 = _InMemoryRaisesQuestionGraph()
    TreeKgWriter(g2).add_node("T", NodeIn(tag="m", algorithm="problem"), [])
    assert g2.raises_edges == set(), f"open_question 부재인데 엣지 누수: {g2.raises_edges}"
    assert g2.read_node_questions("m") == [], g2.read_node_questions("m")
    opened_none = sum(len(g2.read_node_questions("m")) for _ in [0])
    assert opened_none == 0
    backend.ship([_ev(cid, "no_question_no_edge",
                      tag="m", edge_count=len(g2.raises_edges), opened=opened_none)])
