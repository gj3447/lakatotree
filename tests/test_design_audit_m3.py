"""설계감사 M3 guard — Laudan 퇴행규칙이 *미확증* progressive_conditional 을 prediction_hit 으로
세서 degenerating 가지의 폐기(should_abandon 규칙②)를 무기한 면제하는 결함의 박제 테스트.

결함 위치: metrics.py:71,223 의 `prediction_hits = sum(... verdict in PROGRESS_VERDICTS)`.
verdicts.PROGRESS_VERDICTS 가 confirmed 'progressive' 뿐 아니라 미확증 progressive_conditional·
former_canonical 까지 한 frozenset 에 뭉쳐(verdicts.py:65-70) → engine.py:676-685 가 구현미완/replay
미증명(=미확증)으로 내는 progressive_conditional 이 적중 1로 세져서, 예산 소진 가지가 영원히 산다.
bandit realized_reward(heuristic.py:215)까지 오염된다.

처방(같은 repo 의 fertility.py:22 novel_confirmed 게이트를 승격): prediction_hits 는
*confirmed-novel 진보*(verdicts.CONFIRMED_NOVEL_PROGRESS — confirmed 'progressive' 만)로만 센다.
미확증 progressive_conditional/former_canonical 은 적중 아님 → 예산 소진 가지가 정직히 폐기된다.

피드백 하네스 사전등록명: examples/design_audit_20260625_programme.py M3_unconfirmed_counted_as_hit.
# KG: span_lakatotree_S1_laudan_layer
"""
from lakatos.quant.laudan import ABANDON_BUDGET, should_abandon
from lakatos.quant.metrics import tree_metrics


def _node(tag, verdict, parent, **kw):
    base = dict(tag=tag, verdict=verdict, parent=parent, parents=[parent] if parent else [],
                metric_value=None, pred_baseline=None, pred_noise_band=None,
                novel_registered=False, novel_confirmed=False, questions=[])
    base.update(kw)              # kw 가 기본값 override (confirmed leaf 픽스처용)
    return base


def _unconfirmed_conditional_branch():
    """정본 root + 분기 가지: 5×partial → 미확증 progressive_conditional leaf.

    leaf 가 progressive_conditional(=NONPROGRESSIVE 아님)이라 leaf 쪽부터 세는 consec=0 →
    규칙①(연속 비진보 ≥3) 은 *안* 걸린다(이 결함을 격리). budget(5) 소진 가지이므로 규칙②
    (예산 소진 ∧ 적중 0)만이 폐기를 부른다. 결함: 미확증 conditional 이 적중 1로 세져 규칙② 면제.
    """
    nodes = [_node('root', 'CANONICAL', None)]
    prev = 'root'
    for i in range(ABANDON_BUDGET):              # 5×partial (비진보 ad-hoc 누적)
        tag = f'patch{i}'
        nodes.append(_node(tag, 'partial', prev))
        prev = tag
    # 미확증 leaf: 구현미완/replay미증명으로 엔진이 내는 progressive_conditional (novel_confirmed=False)
    nodes.append(_node('leaf', 'progressive_conditional', prev, verdict_source='engine'))
    frontier = []
    return nodes, frontier


def test_unconfirmed_progressive_conditional_chain_should_abandon():
    nodes, frontier = _unconfirmed_conditional_branch()

    # ── 가지 길이/예산 sanity: root 제외 분기 가지 = 5 partial + 1 conditional leaf = 6 노드, 예산 소진 ──
    branch_len = ABANDON_BUDGET + 1
    assert branch_len > ABANDON_BUDGET

    # ── 반사실(영수증): 미확증 leaf 를 적중으로 세지 *않으면*(hits=0) 규칙②가 가지를 폐기해야 한다.
    #    consec=0(leaf 가 비진보 아님)이라 규칙①은 안 걸리고, 오직 적중 셈법이 폐기를 좌우한다. ──
    ok_if_unconfirmed_not_hit, reason = should_abandon(
        consecutive_nonprogressive=0, nodes_spent=branch_len,
        prediction_hits=0, problem_balance_windowed=0)
    assert ok_if_unconfirmed_not_hit and '예산' in reason, \
        '반사실 sanity: hits=0 이면 예산 소진 가지는 폐기돼야(규칙②)'
    # 결함 재현: 미확증 conditional 을 적중 1로 세면 같은 가지가 폐기를 면제받는다.
    ok_if_unconfirmed_counted, _ = should_abandon(
        consecutive_nonprogressive=0, nodes_spent=branch_len,
        prediction_hits=1, problem_balance_windowed=0)
    assert not ok_if_unconfirmed_counted, \
        '반사실 sanity: 미확증을 적중으로 세면(결함) 가지가 부당히 산다'

    # ── 본 판정: tree_metrics 의 laudan.abandon_candidates 가 이 미확증 가지를 폐기 후보로 잡아야 한다.
    #    수정 전(미확증=적중): hits=1 → 규칙② 면제 → leaf 가 후보에 *없다*(RED).
    #    수정 후(confirmed-only): hits=0 → 규칙② 발동 → leaf 가 후보에 *있다*(GREEN). ──
    m = tree_metrics(nodes, frontier)
    abandon_leaves = {c['leaf'] for c in m['laudan']['abandon_candidates']}
    assert 'leaf' in abandon_leaves, (
        '미확증 progressive_conditional leaf 의 예산 소진 가지가 폐기 후보가 아님 — '
        '미확증을 prediction_hit 으로 세서 규칙② 면제(결함 M3)')


def test_confirmed_progressive_branch_is_not_abandoned():
    """회귀 금지: 같은 budget 소진 가지라도 leaf 가 *confirmed* progressive 면 적중 1 → 살아야 한다.
    fix 가 confirmed-novel 만 세는지(과잉 폐기 아닌지) 검증."""
    nodes = [_node('root', 'CANONICAL', None)]
    prev = 'root'
    for i in range(ABANDON_BUDGET):
        tag = f'patch{i}'
        nodes.append(_node(tag, 'partial', prev))
        prev = tag
    # confirmed progressive leaf — 실 영수증(scripted)으로 채점된 진보 + novel 확증
    nodes.append(_node('leaf', 'progressive', prev,
                       verdict_source='scripted', novel_registered=True, novel_confirmed=True))
    m = tree_metrics(nodes, [])
    abandon_leaves = {c['leaf'] for c in m['laudan']['abandon_candidates']}
    assert 'leaf' not in abandon_leaves, \
        'confirmed progressive 가지가 부당히 폐기됨 — fix 가 과함(정당한 진보 회귀)'
