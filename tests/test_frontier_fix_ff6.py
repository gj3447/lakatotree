"""FF6 guard (frontier-fix 2026-06-26): dogfood 하네스가 FG-2(채점 연극)를 *판별*로 닫았음을 증명.

결함(deep-dive FG-2): 선행 design_audit_20260625_programme.py run() 은 improved 와 novel 을 *같은* pytest
비트 하나에서 유도해 judge() 가 progressive/pending 만 가능했다(채점력 0 — 우회만 막은 패치도 progressive).
수정: frontier_fix_20260626_programme 은 발견당 *독립 두 가드*로 improved(개선축=guard_defect)과
novel(novel축=guard_mechanism)을 서로 다른 측정에서 받아 judge() 가 partial/equivalent 도 낸다.

두 가드 green 으로 착륙하면 examples/frontier_fix_20260626_programme.py 가 FF6 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF6_dogfood_discriminates
"""
from __future__ import annotations

from examples.frontier_fix_20260626_programme import AUDIT_NODES, _score


def _probe():
    """루트가 아닌 대표 scoring 노드(prediction 보유)."""
    return next(n for n in AUDIT_NODES if n.prediction is not None)


def test_dogfood_patch_without_mechanism_scores_partial_not_progressive():
    """음성 오라클: 결함은 닫혔으나(defect) 서버 메커니즘이 없으면(¬mechanism) progressive 가 *아니라* partial.

    선행 단일비트 하네스에선 불가능했던 판결(partial)이 나와야 한다 = FG-2 가 닫혔다는 증거.
    우회만 막은 ad-hoc 패치는 결코 progressive 천장을 못 넘는다(라카토스).
    """
    n = _probe()
    v = _score(n, defect_closed=True, mech_present=False)
    assert v["verdict"] == "partial", v
    assert v["improved"] is True and v["novel"] is False, v
    assert v["verdict"] != "progressive"


def test_dogfood_improved_and_novel_read_from_distinct_guards():
    """양성: improved 와 novel 이 독립 두 축에서 와 judge() 가 3개 이상 distinct 판결을 낸다.

    한 비트로는 {progressive, pending} 만 가능 — {progressive, partial, equivalent} 가 모두 나오면
    두 축이 독립이라는 by-construction 증거. 또 두 가드 이름이 서로 달라야 한다(같은 비트 재사용 아님).
    """
    n = _probe()
    verdicts = {_score(n, dc, mp)["verdict"] for dc in (True, False) for mp in (True, False)}
    assert {"progressive", "partial", "equivalent"} <= verdicts, verdicts
    assert n.guard_defect and n.guard_mechanism and n.guard_defect != n.guard_mechanism
    # 모든 scoring 노드가 improve!=novel metric 을 가진다(FG-2 재발 방지 by-construction)
    for m in AUDIT_NODES:
        if m.prediction is not None:
            assert m.prediction.metric_name != m.novel_target.metric_name, m.tag
