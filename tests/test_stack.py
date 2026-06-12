"""gap3 층간 통약불가 메타규칙 — 침묵 OR 제거, 명시 정족수 검증."""
import pytest

from lakatos.stack import (
    ABANDON, RETAIN, UNDECIDED,
    LayerVote, bayes_vote, evaluate_stack, laudan_vote, popper_vote, stack_verdict,
)

PROG = {'verdict': 'progressive', 'delta': -0.5, 'noise_band': 0.05}
REJ = {'verdict': 'rejected', 'delta': 0.5, 'noise_band': 0.05}
PART = {'verdict': 'partial', 'delta': -0.1, 'noise_band': 0.05}


def test_popper_single_rejection_votes_abandon():
    v = popper_vote([PROG, REJ])
    assert v.vote == ABANDON


def test_popper_undecided_without_verdicts():
    assert popper_vote([]).vote == UNDECIDED


def test_bayes_strong_branch_survives_one_counterexample():
    # 자산 많은 가지(진보 3연속) + 반례 1 → 베이즈는 retain
    v = bayes_vote([PROG, PROG, PROG, REJ])
    assert v.vote == RETAIN
    assert v.detail['credence'] > 0.5


def test_lakatos_ocean_of_anomalies_single_rejection_does_not_kill():
    """핵심 시나리오: 포퍼=abandon, 베이즈=retain, 라우든=retain → 메타규칙 retain + conflict 보고.

    옛 침묵 OR 와 결과는 같아 보여도, 이제 '왜 살았는지'(정족수 미달)와
    '누가 죽이려 했는지'(포퍼 표)가 구조적으로 기록된다.
    """
    sv = evaluate_stack([PROG, PROG, PROG, REJ],
                        consecutive_nonprogressive=1, nodes_spent=4,
                        prediction_hits=3, problem_balance_windowed=1)
    assert sv.decision == RETAIN
    assert sv.conflict is True
    votes = {v.layer: v.vote for v in sv.votes}
    assert votes == {'popper': ABANDON, 'bayes': RETAIN, 'laudan': RETAIN}
    assert '관용' in sv.reason


def test_two_layer_agreement_abandons():
    # 반례 연쇄: 포퍼 abandon + 라우든 abandon(연속 비진보 3) → 정족수 2 충족
    sv = evaluate_stack([REJ, REJ, REJ],
                        consecutive_nonprogressive=3, nodes_spent=3,
                        prediction_hits=0, problem_balance_windowed=0)
    assert sv.decision == ABANDON
    abandons = [v.layer for v in sv.votes if v.vote == ABANDON]
    assert len(abandons) >= 2


def test_no_silent_most_lenient_layer():
    # 모든 경로에서 전 층 투표가 노출된다 — 침묵 금지
    sv = evaluate_stack([PART], consecutive_nonprogressive=1, nodes_spent=1,
                        prediction_hits=0, problem_balance_windowed=0)
    assert len(sv.votes) == 3
    assert all(v.reason for v in sv.votes)


def test_quorum_not_met_is_undecided_not_lenient():
    # 투표 가능한 층이 1개뿐이면 관대한 default 가 아니라 undecided (정직)
    laudan_only = laudan_vote(0, 1, 0, 0)
    sv = stack_verdict([LayerVote('popper', UNDECIDED, 'x'),
                        LayerVote('bayes', UNDECIDED, 'x'), laudan_only])
    assert sv.decision == UNDECIDED


def test_unanimous_abandon():
    sv = evaluate_stack([REJ, REJ, REJ, REJ, REJ],
                        consecutive_nonprogressive=5, nodes_spent=5,
                        prediction_hits=0, problem_balance_windowed=-3)
    assert sv.decision == ABANDON
    assert sv.conflict is False


def test_quorum_grounded_constant():
    from lakatos.grounding import provenance
    p = provenance('stack_quorum')
    assert p['value'] == 2
    assert 'Condorcet' in p['citation']
