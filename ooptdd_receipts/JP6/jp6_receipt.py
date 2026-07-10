"""OOPTDD emit-adapter — jp6 judge() opt-in 독립출처 게이트 영수증 (이벤트 리터럴은 이 파일에만).

verify(backend, cid)가 *실* lakatos.verdict.judge.judge 를 구동(재구현 금지, 순수 커널):
  (A) 양성  : armed relabel 공격(m→m_v2·빈 sha·witness 부재) → partial demote
  (B) 음성#1: distinct-sha·witness 변형은 armed 에서도 progressive (과잉차단이면 RED)
  (C) 음성#2: 게이트 해제(기본) 시 같은 공격이 progressive — 기각이 게이트 소행(non-vacuous)
              + 비파괴 기본 거동 핀 (FF1 잔여의 정직 기록)
  (D) 죽은 장식 금지: flag off + witness → ValueError

# KG: LakatosTree_JudgeProprioception_20260708 / jp6-cross-metric-novelty
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

from lakatos.verdict.judge import NovelTarget, Prediction, judge  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.jp6.cross_metric", "event": name, **attrs}


def verify(backend, cid):
    pred = Prediction(metric_name='m', direction='higher', baseline_value=0.0,
                      novel_prediction='x')
    nt = NovelTarget('m_v2', 'higher', 1.0)   # relabel: 예측 metric 개명, 같은 값, 빈 sha

    # (A) 양성: armed 게이트가 relabel 공격 기각
    a = judge(pred, 1.0, novel_target=nt, novel_measured=1.0,
              require_independent_source=True)
    assert a.verdict == 'partial' and not a.novel and '비독립' in a.reason, a
    backend.ship([_ev(cid, 'cross_metric_relabel_rejected', verdict=a.verdict)])

    # (B) 음성#1: distinct sha / witness 변형은 armed 에서도 진짜 초과내용 (과잉차단 배제)
    b1 = judge(pred, 1.0, novel_target=nt, novel_measured=1.0,
               measured_sha='a', novel_sha='b', require_independent_source=True)
    b2 = judge(pred, 1.0, novel_target=nt, novel_measured=1.0,
               require_independent_source=True, independence_witness='held-out run')
    assert b1.verdict == 'progressive' and b1.novel, b1
    assert b2.verdict == 'progressive' and b2.novel and 'independence_witness' in b2.reason, b2
    backend.ship([_ev(cid, 'independent_cross_metric_licensed',
                      distinct_sha_verdict=b1.verdict, witness_verdict=b2.verdict)])

    # (C) 음성#2: 게이트 해제(기본) 시 같은 공격이 progressive — JP6-1 기각은 게이트 소행
    d = judge(pred, 1.0, novel_target=nt, novel_measured=1.0)
    assert d.verdict == 'progressive' and d.novel, d
    backend.ship([_ev(cid, 'default_permissive_preserved', verdict=d.verdict)])

    # (D) 죽은 장식 금지: flag off + witness → ValueError
    try:
        judge(pred, 1.0, novel_target=nt, novel_measured=1.0, independence_witness='x')
        raise AssertionError('witness without flag must be refused (dead decoration)')
    except ValueError:
        pass
    backend.ship([_ev(cid, 'dead_witness_refused', refused=True)])
