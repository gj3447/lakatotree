"""gap3 층간 통약불가 메타규칙 — 침묵 OR 제거, 명시 정족수 검증."""
import pytest

from lakatos.programme.stack import (
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


# ── 층별 verdict-flip 지표 (flip.py) — 외부 리뷰 B-3 ──────────────────────────
from lakatos.programme.flip import vote_pivotal, layer_flips, LAYERS
from lakatos.quant.metrics import branch_inputs


def test_vote_pivotal_two_layer_abandon_each_abandoner_is_pivotal():
    # 포퍼+라우든 abandon, 베이즈 retain → decision ABANDON(2/3). abandon 표 하나를 빼면
    # 정족수 미달 → RETAIN. 따라서 두 abandon 층 각각이 피벗(판결을 뒤집음).
    sv = stack_verdict([LayerVote('popper', ABANDON, 'x'),
                        LayerVote('bayes', RETAIN, 'x'),
                        LayerVote('laudan', ABANDON, 'x')])
    assert sv.decision == ABANDON
    assert vote_pivotal(sv, 'popper') is True
    assert vote_pivotal(sv, 'laudan') is True
    assert vote_pivotal(sv, 'bayes') is False     # retain 을 빼도 여전히 2 abandon → ABANDON


def test_vote_pivotal_minority_dissent_is_not_a_flip():
    # 이상의 바다: 포퍼 단독 abandon, 나머지 retain → decision RETAIN. 포퍼를 빼도 RETAIN.
    # 소수 dissent 는 피벗이 아니다 — 단순 'vote != decision' 휴리스틱이라면 오탐했을 케이스.
    sv = stack_verdict([LayerVote('popper', ABANDON, 'x'),
                        LayerVote('bayes', RETAIN, 'x'),
                        LayerVote('laudan', RETAIN, 'x')])
    assert sv.decision == RETAIN
    assert vote_pivotal(sv, 'popper') is False
    assert vote_pivotal(sv, 'bayes') is False
    assert vote_pivotal(sv, 'laudan') is False


def test_vote_pivotal_unanimous_abandon_has_no_pivot():
    # 만장일치 abandon — 어느 한 층을 빼도 2 abandon 잔존 → 여전히 ABANDON → 피벗 없음(잉여).
    sv = stack_verdict([LayerVote('popper', ABANDON, 'x'),
                        LayerVote('bayes', ABANDON, 'x'),
                        LayerVote('laudan', ABANDON, 'x')])
    assert sv.decision == ABANDON
    assert all(vote_pivotal(sv, layer) is False for layer in LAYERS)


def test_vote_pivotal_layer_that_did_not_vote_is_never_pivotal():
    # 표를 내지 않은 층은 반사실 자체가 없음 → 항상 False.
    sv = stack_verdict([LayerVote('popper', ABANDON, 'x'),
                        LayerVote('laudan', ABANDON, 'x')])
    assert vote_pivotal(sv, 'bayes') is False


def _chain(verdicts):
    """[verdict, ...] (root→leaf) → branch_inputs 가 먹는 단일 사슬 노드 dict 리스트."""
    nodes = []
    for i, v in enumerate(verdicts):
        nodes.append(dict(tag=f'n{i}', verdict=v, parent=(f'n{i-1}' if i else None)))
    return nodes


def test_layer_flips_single_branch_labels_and_matches_pivotality():
    # rejected 3연속 사슬 한 가지: 어느 층이 피벗인지는 credence 내부값에 달려 있으므로
    # 하드코딩하지 않고, 같은 가지의 vote_pivotal 독립 재계산과 정확히 일치하는지 + 가지 라벨이
    # 맞는지 검증한다(오케스트레이션 + 라벨링의 견고한 정합성).
    nodes = _chain(['rejected', 'rejected', 'rejected'])
    out = layer_flips(nodes, frontier=[])
    assert out['branches_evaluated'] == 1
    bi = branch_inputs(nodes, [], leaf='n2')
    sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                        bi['prediction_hits'], bi['problem_balance_windowed'])
    for layer in LAYERS:
        assert out[layer]['flips'] == (1 if vote_pivotal(sv, layer) else 0)
        assert out[layer]['branches'] == (['n2'] if vote_pivotal(sv, layer) else [])


def test_layer_flips_shape_and_orchestration_matches_per_leaf_pivotality():
    # 여러 가지 트리: layer_flips 의 집계가 가지별 vote_pivotal 독립 재계산과 정확히 일치하는지
    # (credence 내부값에 의존하지 않는 견고한 정합성 검사 — 오케스트레이션 자체를 검증).
    nodes = [
        dict(tag='root', verdict='progressive', parent=None),
        dict(tag='a1', verdict='progressive', parent='root'),
        dict(tag='a2', verdict='rejected', parent='a1'),      # leaf 1
        dict(tag='b1', verdict='rejected', parent='root'),
        dict(tag='b2', verdict='rejected', parent='b1'),      # leaf 2
    ]
    frontier = []
    out = layer_flips(nodes, frontier)
    assert out['branches_evaluated'] == 2                     # a2, b2 가 leaf
    assert set(LAYERS) <= set(out)
    for layer in LAYERS:
        assert isinstance(out[layer]['flips'], int)
        assert out[layer]['flips'] == len(out[layer]['branches'])
    # 독립 재계산: 각 leaf 의 stack 판결에서 층별 피벗을 직접 세어 일치 확인.
    expected = {layer: 0 for layer in LAYERS}
    for leaf in ('a2', 'b2'):
        bi = branch_inputs(nodes, frontier, leaf=leaf)
        sv = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                            bi['prediction_hits'], bi['problem_balance_windowed'])
        for layer in LAYERS:
            if vote_pivotal(sv, layer):
                expected[layer] += 1
    assert {layer: out[layer]['flips'] for layer in LAYERS} == expected
