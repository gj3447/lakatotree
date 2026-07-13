"""[FIXED 2026-07-13] REPLAY CLI 계약 비호환 ≠ 값반증 — E16/E17 사건 봉합.

배경(consumer_b FalseOK 트리 실사 2026-07-13에서 발견): 서버 producer replay 는 재현명령을
'python <script> <result_path>'(positional) 로 조립하는데, argparse-only 채점 하네스
(E16 anomaly_correctedmap / E17 anomaly_seamfield — --selftest 플래그만 정의)는 positional 을
거부한다 → 어떤 env 에서도 argparse usage-error(exit 2, stderr 'unrecognized arguments')
→ 종전 분류로는 scorer_nonzero_exit → verified=False → replay_status='mismatch'
→ fsck MEASUREMENT_REFUTED_BUT_STANDING **오발화**. 실제로는 스코어러가 측정을 시작조차
못 한 것이며, 올바른 env full 재실행 실측으로 두 노드의 값(9/0.223)은 완전 재현됐다
(3DLAB docs/falseok_20260709/replay_20260713/ 영수증).

봉합 3층(전부 dead-σ '검증 불가 ≠ 반증' 원칙의 적용):
  ① lakatos/io/replay.py producer_replay — exit 2 ∧ argparse usage-error 시그니처
     ('unrecognized arguments' | 'the following arguments are required') → verified=None,
     reason='cli_contract_incompatible' (no_rerunnable_scorer 동형). 좁은 시그니처만 —
     bare exit 2·일반 크래시는 여전히 False(#24 정합 보존).
  ② server/app.py _replay_run — 실패 경로만 stderr 동봉(argparse 메시지는 stderr 로 감).
     성공 경로 stdout 순수 유지(metric 파싱 불변).
  ③ judgement_policy.resolve_measurement — verdict 존재 ∧ verified None → 신설 status
     'not_replayable' (종전엔 falsy 로 'mismatch' 에 합쳐짐). fsck 는 'mismatch' 만 물므로
     오발화 소멸, 진짜 반증(값 불일치·크래시)은 그대로 발화.
# KG: span_lakatotree_rebuild / span_lakatotree_engine
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _bash_returning(out: str, code: int = 0):
    """채점 재실행 포트 모킹 — (stdout, exit_code) (test_fix_producer_replay 패턴)."""
    def _run(cmd):   # noqa: ARG001
        return (out, code)
    return _run


# ── 결함축(사건 재현, 순수): argparse positional 거부는 '재실행 불가'지 반증이 아니다. ──────────
def test_cli_contract_rejection_is_not_refutation():
    from lakatos.io.replay import producer_replay
    v = producer_replay(
        score_cmd="python harness.py result.json", recorded_metric=9.0,
        run_bash=_bash_returning(
            "usage: harness.py [-h] [--selftest]\n"
            "harness.py: error: unrecognized arguments: result.json", code=2))
    assert v.verified is None, f"CLI 계약 비호환이 반증(False)으로 오분류: {v}"
    assert v.reason == "cli_contract_incompatible", v
    assert v.regenerated is None


def test_missing_required_positional_is_not_refutation():
    from lakatos.io.replay import producer_replay
    v = producer_replay(
        score_cmd="python harness.py", recorded_metric=0.5,
        run_bash=_bash_returning(
            "usage: harness.py out\nharness.py: error: the following arguments are required: out",
            code=2))
    assert v.verified is None and v.reason == "cli_contract_incompatible", v


# ── 협소성 가드(음성): 시그니처 없는 exit 2·일반 크래시·exit≠2 + 유사문구는 여전히 False. ──────
def test_bare_exit2_and_crashes_stay_refuted():
    from lakatos.io.replay import producer_replay
    cases = [
        ("Traceback (most recent call last): ...", 2),           # exit 2 지만 argparse 아님
        ("metric=0.50", 1),                                      # 일반 크래시(#24 정합, 기존 계약)
        ("unrecognized arguments: x", 1),                        # 문구 있어도 exit≠2 면 면제 없음
    ]
    for out, code in cases:
        v = producer_replay(score_cmd="python s.py r.json", recorded_metric=0.5,
                            run_bash=_bash_returning(out, code))
        assert v.verified is False, f"협소성 붕괴 — ({out!r}, {code}) 가 면제됨: {v}"


# ── seam: resolve_measurement 는 verified None 을 'not_replayable' 로 — mismatch 합류 금지. ──────
def test_resolve_measurement_not_replayable_status():
    from lakatos.io.replay import ProducerReplayVerdict
    from server.contexts.tree.judgement_policy import resolve_measurement
    nr = ProducerReplayVerdict(verified=None, regenerated=None, recorded=9.0,
                               reason="cli_contract_incompatible")
    assert resolve_measurement(nr, 9.0) == (9.0, "client_asserted", "not_replayable")
    # 등급 사다리 불변(AG5/jp5): attested/authored 는 서명 있을 때만 — status 와 직교.
    assert resolve_measurement(nr, 9.0, attested=True) == (9.0, "attested", "not_replayable")
    # 기존 3상태 회귀 보존(test_r8 계약).
    ok = ProducerReplayVerdict(verified=True, regenerated=9.0, recorded=9.0, reason="externally_verified")
    bad = ProducerReplayVerdict(verified=False, regenerated=1.0, recorded=9.0, reason="metric_mismatch")
    assert resolve_measurement(None, 9.0)[2] == "not_attempted"
    assert resolve_measurement(ok, 9.0)[2] == "verified"
    assert resolve_measurement(bad, 9.0)[2] == "mismatch"


# ── fsck: not_replayable 무발화(dead-σ), 진짜 mismatch 는 계속 발화(가드 보존). ─────────────────
def test_fsck_silent_on_not_replayable_loud_on_mismatch():
    from server.contexts.audit.fsck import _check_measurement_refuted
    assert _check_measurement_refuted(
        {"replay_status": "not_replayable", "verdict": "progressive"}) is None, \
        "재실행 불가가 값무결 경고로 오발화(E16/E17 사건 회귀)"
    f = _check_measurement_refuted({"replay_status": "mismatch", "verdict": "progressive"})
    assert f is not None and f.check_id == "MEASUREMENT_REFUTED_BUT_STANDING", \
        "진짜 반증 발화가 사라짐(가드 붕괴)"


# ── e2e(사건 복제, revert-민감): 실 argparse-only 스코어러 + 실 _replay_run 배선. ────────────────
#    ②(stderr 동봉) 또는 ①(분류)를 떼면 verified 가 False 로 떨어져 RED.
def test_e2e_argparse_only_scorer_incident_replica():
    import importlib
    app = importlib.import_module("server.app")
    from lakatos.io.replay import producer_replay

    scorer = os.path.join(tempfile.gettempdir(), "cli_contract_scorer_20260713.py")
    with open(scorer, "w") as f:
        f.write("import argparse\n"
                "ap = argparse.ArgumentParser()\n"
                "ap.add_argument('--selftest', action='store_true')\n"
                "ap.parse_args()\n"
                "print('metric=9.0')\n")
    v = producer_replay(score_cmd=f"python {scorer} result.json", recorded_metric=9.0,
                        run_bash=app._replay_run)
    assert v.verified is None, f"사건 복제가 여전히 반증으로 분류됨: {v}"
    assert v.reason == "cli_contract_incompatible", v
    # 같은 스코어러를 계약에 맞게(위치인자 없이) 부르면 정상 검증 — 하드닝이 정직 경로를 안 깬다.
    v2 = producer_replay(score_cmd=f"python {scorer}", recorded_metric=9.0,
                         run_bash=app._replay_run)
    assert v2.verified is True, f"정직 경로 회귀: {v2}"


# 이중 가드 export
guard_defect = "test_cli_contract_rejection_is_not_refutation"
guard_mechanism = "test_e2e_argparse_only_scorer_incident_replica"
