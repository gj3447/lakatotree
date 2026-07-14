"""OOPTDD emit-adapter — LakatoTree 판정엔진 감사 finding A(Laudan 폐기결정 receipt-gate)를
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/quant/{laudan,metrics}.py 불변).
verify 가 실제 lakatos.quant.metrics.tree_metrics 를 *구동*해:
  ① draft(무채점, verdict_source∉FORCEFUL) closer 로 닫은 close 는 폐기 규칙③서 credit 되지 않아
     그 가지가 abandon_candidate 로 잡힌다(문제수지 -3 ≤ −2) — 손입력 close 로 폐기를 면제받던
     조용한 false-retain 차단.
  ② 동일 트리인데 closer 가 scripted(FORCEFUL) 면 close 가 credit → 문제수지 -1 → 폐기 안 됨(양성 대조).
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): receipt-gate 가 없었다면(옛 동작) draft closer 로도 closed=2 로 집계돼
문제수지 -1 이 되고 가지가 폐기되지 않는다 → ①의 assert(draft_leaf ∈ abandon)가 깨진다. 즉 이
영수증은 결함이 살아있으면 *틀린다*. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

참고 테스트: lakatotree/tests/test_laudan.py::test_windowed_balance_receipt_gated_excludes_unreceipted_closer.
# KG: lakatotree-judge-engine-audit finding A / laudan-receipt-gated-abandon-2026-07-12
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.quant.metrics import tree_metrics  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.laudan.finding_A", "event": name, **attrs}


def _tree(closer_source):
    """root(CANONICAL) → draft_leaf(progressive): 질문 3 열고 2 닫음(closer=draft_leaf).
    closer 의 verdict_source 만 바꿔가며 폐기 결정 차이를 본다. 규칙①(consec)·②(예산) 미발동 구성."""
    nodes = [
        dict(tag="root", verdict="CANONICAL", parent=None, parents=[], verdict_source="scripted"),
        dict(tag="draft_leaf", verdict="progressive", parent="root", parents=["root"],
             verdict_source=closer_source, questions=["q1", "q2", "q3"]),
    ]
    frontier = [
        dict(name="q1", status="CLOSED", closed_by=["draft_leaf"]),
        dict(name="q2", status="CLOSED", closed_by=["draft_leaf"]),
        dict(name="q3", status="OPEN", closed_by=[]),
    ]
    return tree_metrics(nodes, frontier)


def _abandon_leaves(m):
    return {c["leaf"] for c in m["laudan"]["abandon_candidates"]}


def verify(backend, cid):
    """finding A 구동 — 실제 tree_metrics 로 폐기결정 receipt-gate 증언."""
    # (1) 음성 오라클: draft(무채점) closer → close 미credit → 가지 폐기.
    #     receipt-gate 가 없었다면 balance -1 로 폐기 안 돼 이 assert 가 깨진다.
    m_draft = _tree("draft")
    ab = _abandon_leaves(m_draft)
    assert "draft_leaf" in ab, f"무채점 close 가 여전히 credit 됨(폐기 면제): {m_draft['laudan']['abandon_candidates']}"
    reason = next(c["reason"] for c in m_draft["laudan"]["abandon_candidates"] if c["leaf"] == "draft_leaf")
    assert "수지" in reason, f"폐기 사유가 문제수지(규칙③)가 아님: {reason}"
    backend.ship([_ev(cid, "unreceipted_close_not_credited_abandons",
                      abandon_leaves=sorted(ab), reason=reason)])

    # (2) 양성 대조(과잉폐기 회귀가드): scripted(FORCEFUL) closer → close credit → 폐기 안 됨.
    m_scripted = _tree("scripted")
    ab2 = _abandon_leaves(m_scripted)
    assert "draft_leaf" not in ab2, f"영수증 있는 close 인데 폐기됨(과잉폐기): {m_scripted['laudan']['abandon_candidates']}"
    backend.ship([_ev(cid, "receipted_close_credited_retains",
                      abandon_leaves=sorted(ab2))])
