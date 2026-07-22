"""OOPTDD emit-adapter — EXTAUDIT S5(2026-07-23) Laudan 폐기신호 배선을 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 TreeMutationService.add_node
(스텁 writer/validator/hist 주입 — 신호 계산·기록 경로는 실코드)를 *구동*해:
  ① red 가지(연속 rejected 3) 확장 → abandon_signal + ABANDON_SIGNAL_IGNORED + hist abandon_override
  ② 건강 가지 무발화 / 루트 fail-open
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 옛 거동(should_abandon 서버 호출 0 = 침묵 진격)이 살아있으면 ①이 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_abandon_wire.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v24_extaudit_abandon_wire
"""
import os
import sys
from types import SimpleNamespace

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.abandon_wire", "event": name, **attrs}


def _mut(events):
    from server.contexts.tree.mutations import TreeMutationService
    m = object.__new__(TreeMutationService)
    m.writer = SimpleNamespace(add_node=lambda name, node, pe: None)
    m.validator = SimpleNamespace(validate_node_create_result=lambda n, td, node: SimpleNamespace(
        parent_edges=[], policy_findings=[]))
    m.hist = lambda name, kind, tag, payload: events.append(kind)
    return m


def _n(tag, parent, verdict, **kw):
    base = dict(tag=tag, parent=parent, parents=[parent] if parent else [], verdict=verdict,
                metric_value=None, pred_baseline=None, pred_noise_band=None, verdict_source="scripted")
    base.update(kw)
    return base


def verify(backend, cid):
    """폐기신호 배선 구동 — red 가지 기록·건강 가지 침묵 증언."""
    from server.contexts.tree.schemas import NodeIn

    # (1) red 가지 확장 — 신호+경고+영속 이력. 옛 거동(호출 0)이면 여기서 깨진다.
    ev = []
    m = _mut(ev)
    td = {"nodes": [_n("r", None, "proof"), _n("a", "r", "rejected"),
                    _n("b", "a", "rejected"), _n("c", "b", "rejected")], "frontier": []}
    out = m.add_node("T", NodeIn(tag="d", parent="c"), td)
    sig = out.get("abandon_signal") or {}
    assert sig.get("fired") is True and "연속 비진보" in sig.get("reason", ""), \
        f"red 가지 확장이 침묵(급소 #7 잔존): {out}"
    assert "ABANDON_SIGNAL_IGNORED" in out.get("policy_warnings", []), out
    assert "abandon_override" in ev, f"영속 override 기록 없음: {ev}"
    backend.ship([_ev(cid, "red_branch_extension_recorded", reason=sig["reason"],
                      warnings=out["policy_warnings"], hist_events=ev)])

    # (2) 이중가드 — 건강 가지 무발화 + 루트 fail-open (과잉 경보/차단화 방지).
    ev2 = []
    m2 = _mut(ev2)
    td2 = {"nodes": [_n("r", None, "proof"),
                     _n("a", "r", "progressive", novel_confirmed=True)], "frontier": []}
    ok_healthy = m2.add_node("T", NodeIn(tag="b", parent="a"), td2)
    ok_root = m2.add_node("T", NodeIn(tag="root2"), {"nodes": [], "frontier": []})
    assert "abandon_signal" not in ok_healthy and "abandon_override" not in ev2, ok_healthy
    assert ok_root["ok"] is True and "abandon_signal" not in ok_root
    backend.ship([_ev(cid, "healthy_and_rootless_silent",
                      healthy_keys=sorted(ok_healthy.keys()), root_keys=sorted(ok_root.keys()))])
