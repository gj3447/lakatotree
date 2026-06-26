"""OOPTDD emit-adapter — LakatoTree 설계감사 M3 fix 를 *구조화 이벤트 trace*(R02)로 영수증화.

결함 M3: 라우든 폐기규칙②(예산 소진 ∧ 적중 0)와 bandit reward 가 *적중*(prediction_hit)을 묻는데,
넓은 PROGRESS_VERDICTS(progressive_conditional/former_canonical 포함)로 세면 *미확증* conditional 이
적중 1로 세져 degenerating 가지가 무기한 산다. fix: prediction_hits 는 confirmed-novel 진보
(verdicts.CONFIRMED_NOVEL_PROGRESS == {"progressive"})만 센다.

규율(ooptdd): 이벤트 리터럴은 엔진(lakatos/*)이 아니라 이 adapter(verify)에만. verify 가 실제
lakatos.verdicts / lakatos.quant.metrics(tree_metrics, 수정된 prediction_hits 경로)를 *구동*하고
관측 사실을 구조화 이벤트로 ship. Longinus 바인딩(R10): 이 emit site 가 must_emit 이벤트를 낸다.
재구현 금지 — tests/test_design_audit_m3.py 의 픽스처/호출을 그대로 차용한다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.verdicts import CONFIRMED_NOVEL_PROGRESS, PROGRESS_VERDICTS  # noqa: E402
from lakatos.quant.laudan import ABANDON_BUDGET, should_abandon          # noqa: E402
from lakatos.quant.metrics import tree_metrics                            # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M3", "event": name, **attrs}


# ── tests/test_design_audit_m3.py 의 픽스처를 그대로 차용(_node / _unconfirmed_conditional_branch) ──
def _node(tag, verdict, parent, **kw):
    base = dict(tag=tag, verdict=verdict, parent=parent, parents=[parent] if parent else [],
                metric_value=None, pred_baseline=None, pred_noise_band=None,
                novel_registered=False, novel_confirmed=False, questions=[])
    base.update(kw)
    return base


def _unconfirmed_conditional_branch():
    """정본 root + 5×partial(비진보 ad-hoc) → 미확증 progressive_conditional leaf(예산 소진 가지)."""
    nodes = [_node('root', 'CANONICAL', None)]
    prev = 'root'
    for i in range(ABANDON_BUDGET):
        tag = f'patch{i}'
        nodes.append(_node(tag, 'partial', prev))
        prev = tag
    nodes.append(_node('leaf', 'progressive_conditional', prev, verdict_source='engine'))
    return nodes, []


def verify(backend, cid):
    """M3 fix 를 실모듈로 구동 — confirmed-only 적중 셈법 + 미확증 conditional 가지 폐기."""

    # ── (1) confirmed_only_progress: CONFIRMED_NOVEL_PROGRESS 가 confirmed 'progressive' 뿐이고
    #        넓은 PROGRESS_VERDICTS 의 미확증 어휘(progressive_conditional/former_canonical)를 *제외* ──
    assert CONFIRMED_NOVEL_PROGRESS == {"progressive"}, CONFIRMED_NOVEL_PROGRESS
    excluded = {"progressive_conditional", "former_canonical"}
    # 음성 오라클: 제외돼야 할 어휘가 confirmed 셈법에 새면(=결함 회귀) 즉시 raise → 가짜 green 차단.
    leaked = excluded & CONFIRMED_NOVEL_PROGRESS
    assert not leaked, f"미확증 어휘가 confirmed 적중에 누수(M3 회귀): {leaked}"
    # 양성 대조: 그 어휘들은 *넓은* PROGRESS_VERDICTS 의 다른 용처엔 그대로 남아야 한다.
    assert excluded <= PROGRESS_VERDICTS, excluded
    backend.ship([_ev(cid, "confirmed_only_progress",
                      confirmed=sorted(CONFIRMED_NOVEL_PROGRESS),
                      excluded_from_hit=sorted(excluded),
                      still_in_progress_axis=sorted(excluded & PROGRESS_VERDICTS))])

    # ── (2) unconfirmed_chain_abandons: tree_metrics 의 laudan.abandon_candidates 가 미확증 가지를
    #        폐기 후보로 잡는다(수정 후 hits=0 → 규칙② 발동). 실 metrics 엔진을 구동. ──
    nodes, frontier = _unconfirmed_conditional_branch()
    branch_len = ABANDON_BUDGET + 1
    assert branch_len > ABANDON_BUDGET

    # 반사실(음성 오라클): hits=0 이면 예산 소진 가지는 폐기돼야(규칙②) — should_abandon 직접 구동.
    ok_unconfirmed_not_hit, reason = should_abandon(
        consecutive_nonprogressive=0, nodes_spent=branch_len,
        prediction_hits=0, problem_balance_windowed=0)
    assert ok_unconfirmed_not_hit and '예산' in reason, \
        f"반사실 sanity: hits=0 이면 예산 소진 가지는 폐기돼야(규칙②); reason={reason!r}"
    # 결함 재현 대조: 미확증을 적중 1로 세면 같은 가지가 부당히 면제된다(음성 케이스).
    ok_unconfirmed_counted, _ = should_abandon(
        consecutive_nonprogressive=0, nodes_spent=branch_len,
        prediction_hits=1, problem_balance_windowed=0)
    assert not ok_unconfirmed_counted, "미확증을 적중으로 세면(결함) 가지가 부당히 산다"

    # 본 판정: 수정된 tree_metrics(confirmed-only prediction_hits)가 leaf 를 폐기 후보로.
    m = tree_metrics(nodes, frontier)
    abandon_leaves = {c['leaf'] for c in m['laudan']['abandon_candidates']}
    assert 'leaf' in abandon_leaves, (
        '미확증 progressive_conditional leaf 의 예산 소진 가지가 폐기 후보가 아님 — '
        f'미확증을 prediction_hit 으로 세서 규칙② 면제(결함 M3); candidates={abandon_leaves}')
    backend.ship([_ev(cid, "unconfirmed_chain_abandons",
                      branch_len=branch_len, abandon_budget=ABANDON_BUDGET,
                      abandon_candidate_leaves=sorted(abandon_leaves),
                      counterfactual_hits0_abandons=bool(ok_unconfirmed_not_hit),
                      counterfactual_hits1_survives=bool(not ok_unconfirmed_counted))])
