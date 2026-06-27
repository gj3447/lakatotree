"""FIX-HARNESS (deep frontier from #1): PRODUCER REPLAY — 채점 스크립트를 *재실행*해 client metric_value 검증.

배경(나생문 #1): CANONICAL floor 가 judge_receipt(scripted)를 영수증으로 인정하나, judge 는 결정론적이어도
그 입력(metric_value/novel_measured)은 서버가 *재실행하지 않는* client float 다(server/app.py:395 자인 —
"완전 무위조(실제 producer replay 실행)는 ... 미구현"). #1 의 honest-exposure 는 간극을 *노출*만 했고, 근본
봉합은 **producer replay**(스크립트를 재실행해 재생성 metric 이 recorded 와 일치하는지 대조)다.

이 하네스는 *구현 전에* 그 계약을 고정한다(RED-first). 재실행 자체는 lakatos/io/rebuild.py 의 RebuildExecutor
가 이미 하지만(recipe 재실행→regenerated vs recorded→'rebuildable'/'metric_mismatch'), *채점 경로*(submit
→ judge(client metric))엔 연결돼 있지 않다. 목표 API(구현이 제공할 것):

    from lakatos.io.replay import producer_replay, ProducerReplayVerdict
    v = producer_replay(score_cmd=..., recorded_metric=..., run_bash=<port>, tolerance=...)
    # ProducerReplayVerdict(verified: bool|None, regenerated: float|None, recorded: float, reason: str)
    #   verified=True  : 재실행이 recorded 와 일치 → 측정이 외부검증됨(외부앵커 자격)
    #   verified=False : 불일치(위조)·스크립트 크래시·metric 부재 → 신뢰 불가(forge 적발)
    #   verified=None  : 재실행 불가(score_cmd 없음) → 증명 못 함, *차단은 안 함*(현 reproducible=None 동형)

계약(아래 음성/양성 오라클):
  ① 정직: run_bash 가 recorded 와 같은 metric 을 재생성 → verified=True (외부검증).
  ② 위조(핵심 defect): client 가 recorded=0.99 로 보고했으나 스크립트 재실행이 0.50 → verified=False, mismatch.
     ★ 이것이 producer replay 가 닫는 forge — judge 가 신뢰하던 client float 를 현실이 끊는다.
  ③ 재실행 불가(score_cmd 없음): verified=None — 증명 못 하되 차단 안 함(증명노드/외부데이터 보존).
  ④ 크래시(exit≠0): verified=False — 비정상 종료한 채점은 신뢰 못 함(#24 와 정합).

xfail(strict): 목표 함수가 아직 없어 import/behavior 가 RED. 구현되면 green → strict 가 trip(마커 제거 신호).
포트(run_bash) 주입으로 hermetic — 실 bash/네트워크 없음(rebuild/harness 테스트와 동일 패턴).
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
@pytest.mark.xfail(reason="PRODUCER-REPLAY: lakatos.io.replay.producer_replay 미구현 — 정직 측정의 외부검증 경로 부재; RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_verifies_honest_metric():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50"), tolerance=1e-9)
    assert v.verified is True, v
    assert v.regenerated == pytest.approx(0.50)
    assert v.recorded == pytest.approx(0.50)


# ── 결함축 음성 오라클(핵심 forge): 위조된 client metric 은 재실행이 잡는다(verified=False, mismatch). ──
@pytest.mark.xfail(reason="PRODUCER-REPLAY: client 가 보고한 metric_value 를 서버가 재실행으로 검증하지 않아 위조 가능(나생문 #1 근본); RED until lakatos.io.replay.producer_replay 가 mismatch 를 verified=False 로 적발; strict trips when fixed",
                   strict=True)
def test_producer_replay_catches_fabricated_metric():
    from lakatos.io.replay import producer_replay
    # client 는 progressive 를 빚으려 recorded=0.99 를 POST 했으나, 스크립트를 *실제로 돌리면* 0.50 이다.
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.99,
                        run_bash=_bash_returning("metric=0.50"), tolerance=1e-9)
    assert v.verified is False, f"위조 metric 이 외부검증을 통과함(forge 미적발): {v}"
    assert v.regenerated == pytest.approx(0.50)
    assert "mismatch" in (v.reason or "")


# ── 재실행 불가: 증명 못 하되 *차단은 안 함*(verified=None — 현 reproducible=None 동형, 증명노드 보존). ──
@pytest.mark.xfail(reason="PRODUCER-REPLAY: 재실행 불가(score_cmd 없음) → verified=None(증명불가, 비차단) 계약; RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_inconclusive_when_no_rerunnable_scorer():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd=None, recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50"))
    assert v.verified is None, f"재실행 불가가 차단/통과로 처리됨(증명불가여야): {v}"


# ── 크래시: 비정상 종료한 채점은 신뢰 불가(verified=False — #24 종료코드 게이트와 정합). ──
@pytest.mark.xfail(reason="PRODUCER-REPLAY: 스크립트 exit!=0 이면 verified=False(metric 출력해도 수용 금지, #24 정합); RED until 구현; strict trips when fixed",
                   strict=True)
def test_producer_replay_rejects_crashed_scorer():
    from lakatos.io.replay import producer_replay
    v = producer_replay(score_cmd="python score.py", recorded_metric=0.50,
                        run_bash=_bash_returning("metric=0.50", code=1))
    assert v.verified is False, f"크래시한 채점의 metric 이 수용됨: {v}"


# 이중 가드 export (defect=forge 적발 / mechanism=정직 외부검증).
guard_defect = "test_producer_replay_catches_fabricated_metric"
guard_mechanism = "test_producer_replay_verifies_honest_metric"
