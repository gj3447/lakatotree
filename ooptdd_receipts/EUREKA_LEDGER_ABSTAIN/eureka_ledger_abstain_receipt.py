"""OOPTDD emit-adapter — LakatoTree 판정엔진 감사 finding B(eureka ledger-absent ABSTAIN)를
*구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 lakatos/eureka.py 는 불변).
verify 가 실제 lakatos.eureka.classify / eureka_over_tree 를 *구동*해:
  ① 확증+substantial-BF 인데 문제장부 부재(0,0)인 felt → INCONCLUSIVE(hallucinated 아님) abstain
  ② 장부 PRESENT + net-negative → 여전히 veto(hallucinated) — 과잉완화 회귀가드(양성 대조)
  ③ eureka_over_tree 의 hallucination_rate 는 assessable(felt−inconclusive) 위 계산(1.0 아티팩트 해소)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 옛 결함(`balance <= 0` veto — 장부부재를 hallucinated 로 뭉갬)이
살아있었다면 ①의 v.inconclusive 가 False + v.hallucinated 가 True 라 첫 assert 가 깨진다. 즉 이
영수증은 결함이 살아있으면 *틀린다*. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

참고 테스트: lakatotree/tests/test_eureka.py::test_ledger_absent_node_is_inconclusive_not_hallucinated 외.
# KG: lakatotree-judge-engine-audit finding B / eureka-ledger-absent-abstain-2026-07-12
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.eureka import (  # noqa: E402
    _node_to_eureka_input,
    classify,
    eureka_over_tree,
)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.eureka.finding_B", "event": name, **attrs}


# 확증 novel + 강한 효과(delta 10) + 문제장부 부재(pred_closes 없음, questions 없음) = closed 0, opened 0.
_LEDGER_ABSENT = {
    "tag": "omd", "verdict": "progressive",
    "novel_registered": True, "novel_confirmed": True,
    "metric_value": 12.0, "pred_baseline": 2.0, "pred_noise_band": 0.1,
    "pred_closes": [], "questions": [], "source_trust": 1.0,
}
# 장부 PRESENT + net-negative(닫음 1 < 연 3) — 여전히 veto 되어야 하는 대조군.
_NET_NEGATIVE = {**_LEDGER_ABSENT, "tag": "neg",
                 "pred_closes": ["q_closed"], "questions": ["q1", "q2", "q3"]}


def verify(backend, cid):
    """finding B 구동 — 실제 eureka.classify / eureka_over_tree 로 abstain + veto-보존 + rate-정직 증언."""
    # (1) 음성 오라클: 장부부재 확증 노드는 INCONCLUSIVE(hallucinated 아님).
    #     옛 balance<=0 veto 가 살아있었다면 v.inconclusive=False / v.hallucinated=True 라 여기서 깨진다.
    v = classify(_node_to_eureka_input(_LEDGER_ABSENT), require_promotion=False)
    assert v.felt, "확증 novel 은 felt 여야 한다"
    assert v.inconclusive, "장부부재(0,0) 는 INCONCLUSIVE 로 abstain 해야 한다(옛 veto 아티팩트)"
    assert not v.hallucinated, "장부부재를 hallucinated 로 뭉개면 안 된다"
    assert not v.true, "장부부재는 true 승격도 아니다(Laudan 축 미측정)"
    assert not any(r.startswith("problem_balance") for r in v.reasons)
    backend.ship([_ev(cid, "ledger_absent_abstained",
                      inconclusive=bool(v.inconclusive),
                      hallucinated=bool(v.hallucinated), true=bool(v.true),
                      reasons=list(v.reasons))])

    # (2) 양성 대조(과잉완화 회귀가드): 장부 PRESENT + net-negative 는 여전히 veto → hallucinated.
    vn = classify(_node_to_eureka_input(_NET_NEGATIVE), require_promotion=False)
    assert vn.hallucinated and not vn.inconclusive, "net-negative 장부는 여전히 veto(hallucinated) 되어야 한다"
    assert any(r.startswith("problem_balance") for r in vn.reasons)
    backend.ship([_ev(cid, "net_negative_still_vetoed",
                      hallucinated=bool(vn.hallucinated),
                      inconclusive=bool(vn.inconclusive), reasons=list(vn.reasons))])

    # (3) rate 정직: 장부-없는 felt 2 + 장부-있는 true 1 + hallucination 1 → rate 는 assessable=2 위 계산
    #     (옛 코드는 felt=4 분모로 hallucination_rate 를 부풀렸다 — ledger-less 트리 1.0 고정).
    nodes = [
        _LEDGER_ABSENT,                                                        # inconclusive
        {**_LEDGER_ABSENT, "tag": "omd2"},                                     # inconclusive
        {**_NET_NEGATIVE, "tag": "true1",
         "pred_closes": ["a", "b", "c"], "questions": ["q1"]},                 # true (closed 3 > opened 1)
        {**_NET_NEGATIVE, "tag": "hall1", "novel_confirmed": False},           # hallucinated (unconfirmed)
    ]
    r = eureka_over_tree(nodes)
    assert r["felt"] == 4 and r["inconclusive"] == 2 and r["assessable"] == 2, r
    assert r["true"] == 1 and r["hallucinated"] == 1, r
    assert r["hallucination_rate"] == 0.5, f"rate 가 assessable 위 계산 아님(옛 아티팩트 잔존?): {r}"
    backend.ship([_ev(cid, "rate_over_assessable",
                      felt=r["felt"], inconclusive=r["inconclusive"],
                      assessable=r["assessable"], hallucination_rate=r["hallucination_rate"])])
