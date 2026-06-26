"""H4 design-audit guard: demote_canonical 이 hard_core 를 allow_hard_core 없이 강등 못한다(HardCoreProtected).

결함(감사 H4): demote_canonical 이 expansion/contraction 의 hard-core 가드를 우회해 hard_core belief 의
credence 를 제자리 강등. 수정: old.kind=='hard_core' 면 allow_hard_core 없이는 HardCoreProtected.
이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 의 receipt() 가 집어
H4_demote_hardcore_unguarded 노드를 judge() 가 *스스로* progressive 로 채점한다(재귀 dogfood).
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest

from lakatos.programme.agm import Belief, HardCoreProtected, demote_canonical


def test_demote_canonical_protects_hard_core():
    hc = Belief("hc", "하드코어 추측", kind="hard_core", credence=0.95)
    new = Belief("rival", "경쟁 정본", kind="protective_belt", credence=0.8)
    with pytest.raises(HardCoreProtected):
        demote_canonical([hc], "hc", new)                          # 동의 없이 hard_core 강등 → 차단
    r = demote_canonical([hc], "hc", new, allow_hard_core=True)    # 명시 동의 → 허용
    assert any(b.belief_id == "hc" for b in r.base)


def test_demote_protective_belt_still_works():
    """회귀 가드: 보호대 belief 강등은 게이트 없이 그대로 동작."""
    pb = Belief("pb", "보호대", kind="protective_belt", credence=0.9)
    new = Belief("rival", "새 정본", kind="protective_belt", credence=0.8)
    r = demote_canonical([pb], "pb", new)
    assert any(b.belief_id == "pb" for b in r.base)
