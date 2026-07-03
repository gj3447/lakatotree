"""[FIXED 2026-06-28] PRODUCER REPLAY (deep frontier from #1) — green regression.

배경(나생문 #1): CANONICAL floor 가 judge_receipt(scripted)를 영수증으로 인정하나, judge 는 결정론적이어도
그 입력(metric_value)은 서버가 *재실행하지 않는* client float 다(server/app.py:395 자인). #1 의 honest-exposure
는 간극을 *노출*만 했고, 근본 봉합 = **producer replay**(채점 스크립트를 재실행해 재생성 metric 이 recorded 와
일치하는지 대조 — 위조 적발).

구현: lakatos/io/replay.py 의 producer_replay() + ProducerReplayVerdict. io/rebuild.RebuildExecutor 가
recipe 전체를 재실행하는 것의 *채점경로 한정* 판. 포트(run_bash) 주입이라 hermetic.

    v = producer_replay(score_cmd=..., recorded_metric=..., run_bash=<port>, tolerance=...)
    #   verified=True  : 재실행이 recorded 와 일치 → 측정 외부검증(외부앵커 자격)
    #   verified=False : 불일치(위조)·exit≠0(크래시)·metric 부재 → 신뢰 불가(forge 적발)
    #   verified=None  : score_cmd 없음 → 재실행 불가(증명불가, 비차단; reproducible=None 동형)

wiring: producer_replay verified=True 면 synthesize_promotion floor 의 measurement_externally_anchored 가
True — reproducible/human 과 나란히 *세 번째 외부앵커*(#1 honest-exposure → 근본 봉합 진척). live HTTP 서버가
client 스크립트를 직접 실행하는 것은 보안상 별도 gated 통합(미연결).
# KG: span_lakatotree_rebuild / span_lakatotree_engine
"""
from __future__ import annotations

import pytest


def _bash_returning(metric_line: str, code: int = 0):
    """채점 스크립트 재실행 포트 모킹 — (stdout, exit_code) 반환(rebuild/harness 테스트 패턴)."""
    def _run(cmd):   # noqa: ARG001
        return (metric_line, code)
    return _run


# ── 양성/메커니즘 오라클: 정직한 측정은 재실행이 일치 → 외부검증(verified=True). ──
def test_producer_replay_verifies_honest_metric():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50"), tolerance=1e-9)
    assert v.verified is True, v
    assert v.regenerated == pytest.approx(0.50)
    assert v.recorded == pytest.approx(0.50)


# ── 결함축 음성 오라클(핵심 forge): 위조된 client metric 은 재실행이 잡는다(verified=False, mismatch). ──
def test_producer_replay_catches_fabricated_metric():
    from lakatos.io.replay import producer_replay
    # client 는 progressive 를 빚으려 recorded=0.99 를 POST 했으나, 스크립트를 *실제로 돌리면* 0.50 이다.
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.99,
                        run_bash=_bash_returning("metric=0.50"), tolerance=1e-9)
    assert v.verified is False, f"위조 metric 이 외부검증을 통과함(forge 미적발): {v}"
    assert v.regenerated == pytest.approx(0.50)
    assert "mismatch" in (v.reason or "")


# ── 재실행 불가: 증명 못 하되 *차단은 안 함*(verified=None — 현 reproducible=None 동형, 증명노드 보존). ──
def test_producer_replay_inconclusive_when_no_rerunnable_scorer():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd=None, recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50"))
    assert v.verified is None, f"재실행 불가가 차단/통과로 처리됨(증명불가여야): {v}"


# ── 크래시: 비정상 종료한 채점은 신뢰 불가(verified=False — #24 종료코드 게이트와 정합). ──
def test_producer_replay_rejects_crashed_scorer():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50", code=1))
    assert v.verified is False, f"크래시한 채점의 metric 이 수용됨: {v}"


# ── wiring(엔드투엔드): replay 검증 → synthesize_promotion 의 *세 번째 외부앵커*. 위조면 anchored 아님. ──
def test_producer_replay_verified_is_a_third_external_anchor():
    from lakatos.io.replay import producer_replay
    from lakatos.verdict.spine import synthesize_promotion

    honest = producer_replay(score_cmd="python score.py", recorded_metric=0.50,
                             run_bash=_bash_returning("metric=0.50"))
    out = synthesize_promotion(scripted_verdict='progressive', stands=True, reproducible=None,
                               verdict_source='scripted', producer_replay_verified=honest.verified)
    # 재실행으로 측정이 확증됨 → reproducible/human 없이도 외부앵커 True(#1 honest-exposure → 근본 봉합).
    assert out['gates']['floor']['measurement_externally_anchored'] is True

    forged = producer_replay(score_cmd="python score.py", recorded_metric=0.99,
                             run_bash=_bash_returning("metric=0.50"))
    out2 = synthesize_promotion(scripted_verdict='progressive', stands=True, reproducible=None,
                                verdict_source='scripted', producer_replay_verified=forged.verified)
    # 위조(verified False)는 외부앵커 아님 — judge_receipt 단독 = anchored False(#1 그대로).
    assert out2['gates']['floor']['measurement_externally_anchored'] is False


# 이중 가드 export (defect=forge 적발 / mechanism=정직 외부검증).
guard_defect = "test_producer_replay_catches_fabricated_metric"
guard_mechanism = "test_producer_replay_verifies_honest_metric"
