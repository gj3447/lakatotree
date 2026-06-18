"""P1 lifecycle 종료판정 — 수확/발산/소멸/활성 4분기 + regret 검증."""
from lakatos.programme.lifecycle import (
    ACTIVE, DIVERGING, EXTINCT, HARVESTING,
    lifecycle_state, regret_nodes,
)
from lakatos.programme.stack import evaluate_stack

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


def test_branch_inputs_partial_does_not_mask_diverging():
    """나생문 F1 회귀: recent 윈도우가 전부 partial(NONPROGRESSIVE)이고 progressive 가
    윈도우 밖으로 밀려나면 canonical_improved_recent=False 여야 diverging 조기경보가 산다.
    어댑터(branch_inputs)→소비자(lifecycle_state) 통합 경로를 실제로 관통해 검증."""
    from lakatos.quant.metrics import branch_inputs
    from lakatos.programme.stack import evaluate_stack

    def n(tag, verdict, parent=None, mv=None, base=None, nb=None, qs=None):
        return dict(tag=tag, verdict=verdict, parent=parent,
                    parents=[parent] if parent else [], parent_edges=[],
                    metric_value=mv, pred_baseline=base, pred_noise_band=nb,
                    novel_registered=False, questions=qs or [])

    nodes = [
        n('root', 'progressive', mv=0.40, base=0.50, nb=0.05),
        n('p1', 'partial', parent='root', mv=0.39, base=0.40, nb=0.05, qs=['qa']),
        n('p2', 'partial', parent='p1', mv=0.385, base=0.39, nb=0.05, qs=['qb']),
        n('p3', 'partial', parent='p2', mv=0.384, base=0.385, nb=0.05, qs=['qc']),
    ]
    frontier = [dict(name=q, status='OPEN', body='', closed_by=None) for q in ('qa', 'qb', 'qc')]
    bi = branch_inputs(nodes, frontier, leaf='p3')          # window=3 → progressive 가 윈도우 밖
    assert bi['canonical_improved_recent'] is False
    assert bi['problem_balance_windowed'] < 0
    st = evaluate_stack(bi['verdicts'], bi['consecutive_nonprogressive'], bi['nodes_spent'],
                        bi['prediction_hits'], bi['problem_balance_windowed'])
    assert st.decision != 'abandon'                          # 정족수 미달 → extinct 아님
    ls = lifecycle_state(bi['verdicts'], st, bi['novel_registered_recent'],
                         bi['problem_balance_windowed'], bi['canonical_improved_recent'])
    assert ls.state == DIVERGING
