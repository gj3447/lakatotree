"""P1 lifecycle 종료판정 — 수확/발산/소멸/활성 4분기 + regret 검증."""
from lakatos.lifecycle import (
    ACTIVE, DIVERGING, EXTINCT, HARVESTING,
    lifecycle_state, regret_nodes,
)
from lakatos.stack import evaluate_stack

PROG = {'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}
REJ = {'verdict': 'rejected', 'delta': 0.5, 'noise_band': 0.05}
PART = {'verdict': 'partial', 'delta': -0.1, 'noise_band': 0.05}


def _stack(verdicts, cnp, hits, pb):
    return evaluate_stack(verdicts, consecutive_nonprogressive=cnp,
                          nodes_spent=len(verdicts), prediction_hits=hits,
                          problem_balance_windowed=pb)


def test_extinct_only_via_stack_quorum():
    vs = [REJ, REJ, REJ, REJ, REJ]
    st = _stack(vs, cnp=5, hits=0, pb=-3)
    s = lifecycle_state(vs, st, novel_registered_recent=0,
                        problem_balance_windowed=-3, canonical_improved_recent=False)
    assert s.state == EXTINCT


def test_diverging_questions_outpace_answers():
    vs = [PROG, PART, PART]
    st = _stack(vs, cnp=2, hits=1, pb=-1)
    s = lifecycle_state(vs, st, novel_registered_recent=1,
                        problem_balance_windowed=-1, canonical_improved_recent=False)
    assert s.state == DIVERGING


def test_harvesting_mature_programme_is_not_abandoned():
    # novel 등록 고갈 + 정본 안정 + 문제수지 흑자 = 성숙 (폐기 아님)
    vs = [PROG, PROG, PART]
    st = _stack(vs, cnp=1, hits=2, pb=1)
    s = lifecycle_state(vs, st, novel_registered_recent=0,
                        problem_balance_windowed=1, canonical_improved_recent=False)
    assert s.state == HARVESTING
    assert '폐기 아님' in s.reason


def test_active_default():
    vs = [PROG, PART]
    st = _stack(vs, cnp=1, hits=1, pb=0)
    s = lifecycle_state(vs, st, novel_registered_recent=2,
                        problem_balance_windowed=0, canonical_improved_recent=True)
    assert s.state == ACTIVE


def test_severity_order_extinct_beats_diverging():
    vs = [REJ, REJ, REJ, REJ, REJ]
    st = _stack(vs, cnp=5, hits=0, pb=-5)
    s = lifecycle_state(vs, st, novel_registered_recent=0,
                        problem_balance_windowed=-5, canonical_improved_recent=False)
    assert s.state == EXTINCT   # diverging 조건도 참이지만 extinct 우선


def test_regret_counts_since_last_progressive():
    assert regret_nodes([PROG, PART, REJ]) == 2
    assert regret_nodes([PART, REJ]) == 2          # progressive 전무 → 전체
    assert regret_nodes([PART, PROG]) == 0
