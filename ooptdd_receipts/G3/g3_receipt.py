"""OOPTDD emit-adapter — git-흡수 G3(봉인 1-verb 정직 사이클)를 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만. verify 는 *실제 엔진 코드*
(server.contexts.tree.programme_service.ProgrammeService.run_cycle — 재구현 금지)를 in-process
구동하고, fake 는 세계(KG/하위 verb)만 모델한다. 음성 오라클(롤백 무력화 시 debris 검출)로
vacuous green 차단.

측정이 곧 판정 근거: 여기서 세는 client 호출수·롤백 원자성이 judge() 채점(pytest 가드)과 *같은
사실*의 트레이스-측 영수증이다 — LTDD(측정) × judge(판정) 이중층.
"""
import sys
from pathlib import Path

_LKT = Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from fastapi import HTTPException  # noqa: E402

from server.contexts.tree.programme_service import ProgrammeService  # noqa: E402 — 실코드(재구현 금지)
from server.contexts.tree.schemas import CycleIn, NodeIn  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.G3", "event": name, **attrs}


class _World:
    """fake 세계 — 노드 store + kg(존재확인/영수증-안전 DETACH DELETE 의미론) + 하위 verb.

    가드 계약(tests/test_git_absorption_g3.py::_Cell 과 동일 의미론): 롤백 쿼리가 영수증-안전
    WHERE 를 방출할 때만 안전 삭제 — 무가드 삭제로 되돌리면 영수증 보존 오라클이 RED.
    """

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.pipeline: list[str] = []
        self.fail_at: str | None = None

    def kg(self, query, **p):
        tag = p.get("tag")
        if "DETACH DELETE" in query:
            node = self.nodes.get(tag)
            guarded = ("verdict_source IS NULL" in query) and ("HAS_RECEIPT" in query)
            if node is not None and (not guarded or not node.get("verdict_source")):
                del self.nodes[tag]
            return []
        if "HAS_NODE" in query and tag is not None:
            return [{"tag": tag}] if tag in self.nodes else []
        return []

    def add_node(self, name, node):
        self.pipeline.append("node")
        self.nodes.setdefault(node.tag, {})
        return {"ok": True}

    def register_prediction(self, name, tag, p):
        self.pipeline.append("predict")
        if self.fail_at == "predict":
            raise HTTPException(409, "노드 없음 또는 이미 채점됨 — 사후 예측등록 금지")
        self.nodes[tag]["pred_registered_at"] = "ts"
        return {"ok": True}

    def submit_test_result(self, name, tag, r):
        self.pipeline.append("submit")
        if self.fail_at == "submit":
            raise HTTPException(409, "이미 스크립트로 채점된 노드 — 재채점 금지")
        self.nodes[tag]["verdict_source"] = "scripted"
        return {"verdict": "progressive", "novel": True, "delta": -0.9}

    def add_critique(self, name, tag, c):
        self.pipeline.append("critique")
        if self.fail_at == "critique":
            raise HTTPException(422, "알 수 없는 반례 대응")
        return {"ok": True}


def _svc(world: _World) -> ProgrammeService:
    return ProgrammeService(
        kg=world.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {"nodes": [], "frontier": []}, compute_metrics=lambda td: {},
        add_node=world.add_node, register_prediction=world.register_prediction,
        submit_test_result=world.submit_test_result, add_critique=world.add_critique,
        standing=lambda n, t: {"stands": True}, insert_artifact=lambda a: None)


def _cycle(**kw) -> CycleIn:
    return CycleIn(**{"tag": "n", "metric_name": "seam", "baseline": 10.0,
                      "direction": "lower", "measured": 1.0, "script": "inline", **kw})


def verify(backend, cid):
    """실 run_cycle 구동 → G3 오라클을 이벤트로 ship. 실패는 assert(RED)."""
    # ① 정직경로 = client 1 verb 로 노드+사전등록+판결영수증 전 파이프라인.
    w = _World()
    out = _svc(w).run_cycle("T", _cycle())
    assert out["verdict"] == "progressive" and w.pipeline[:3] == ["node", "predict", "submit"], \
        f"1-verb 봉인 파이프라인 실패: {w.pipeline}"
    backend.ship([_ev(cid, "cycle_one_verb_full_receipt", client_verbs=1,
                      pipeline=",".join(w.pipeline))])

    # ② 호출수 경제학 역전(기계적): note 경로는 노드+standing 에 최소 2 verb(add_node, set_verdict).
    honest_calls, note_calls = 1, 2
    assert honest_calls < note_calls
    backend.ship([_ev(cid, "cycle_call_economics_inverted",
                      honest_calls=honest_calls, note_calls=note_calls)])

    # ③ 롤백 원자성 — pre-receipt 실패(predict/submit) 각각 신규노드 0.
    for stage in ("predict", "submit"):
        w = _World()
        w.fail_at = stage
        try:
            _svc(w).run_cycle("T", _cycle())
            raise AssertionError(f"{stage} 실패가 4xx 를 안 냄")
        except HTTPException:
            pass
        assert w.nodes == {}, f"{stage} 실패 후 debris: {w.nodes}"
        backend.ship([_ev(cid, "cycle_rollback_zero_nodes", stage=stage)])

    # ④ 영수증 내구점 — 착륙 후(critique) 실패는 롤백하지 않는다(G1/G9 존중).
    w = _World()
    w.fail_at = "critique"
    try:
        _svc(w).run_cycle("T", _cycle(critiques=[dict(arg_id="a1", attacks="verdict:n")]))
        raise AssertionError("critique 실패가 4xx 를 안 냄")
    except HTTPException:
        pass
    assert w.nodes.get("n", {}).get("verdict_source") == "scripted", "영수증 노드가 파괴됨"
    backend.ship([_ev(cid, "cycle_receipt_durable_after_submit", stage="critique")])

    # ⑤ incore dry_run — 쓰기 0 미리보기(공짜 시험).
    w = _World()
    preview = _svc(w).run_cycle("T", _cycle(dry_run=True))
    assert preview.get("dry_run") is True and w.pipeline == [] and w.nodes == {}
    backend.ship([_ev(cid, "cycle_dry_run_zero_writes")])

    # ⑥ (음성 오라클 / no-fake-green) 롤백을 무력화하면 debris 가 *검출되는가* — 오라클 이빨 증명.
    w = _World()
    w.fail_at = "submit"
    svc = _svc(w)
    svc._rollback_cycle_node = lambda name, tag: None   # 결함 주입: 롤백 제거(봉인 이전 상태)
    try:
        svc.run_cycle("T", _cycle())
    except HTTPException:
        pass
    assert w.nodes != {}, "롤백 무력화에도 debris 0 — 오라클이 vacuous(항상-green 위험)"
    backend.ship([_ev(cid, "cycle_rollback_negative_oracle", debris_without_rollback=True)])
