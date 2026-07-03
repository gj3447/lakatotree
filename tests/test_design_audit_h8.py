"""설계감사 H8(완성-후 로드맵 2026-06-26) — _assemble_af 가 actor(by)를 버려 self-vouch 가능.

결함: 노드 standing 을 좌우하는 Dung AF 조립(_assemble_af)이 Argument 의 by(제기자 actor)를 collect 하고도
버린다. 그래서 한 actor 가 *자기 doubt 를 자기 rebuttal 로* 무력화해 verdict standing 을 유지할 수 있다
(자기방어 엣지가 그대로 AF 에 진입). M8 은 claim_standing 경로의 actor 독립성만 닫았고, set_verdict CANONICAL
floor 와 add_critique 자동강등이 쓰는 AF 조립은 여전히 by 를 무시했다.

수정: argue.assemble_af(tag, arg_rows) — actor-aware AF 조립을 단일 정본으로. 한 argument 가 *다른 argument*
를 공격(=verdict 방어)할 때 두 argument 의 by 가 같으면 그 방어 엣지는 AF 에 진입 못 한다(self-defense/
self-rebuttal 제거). verdict 직접공격(doubt)은 누구나 가능하므로 제외 안 함. (작성자 vs 방어자 독립=노드
author 미식별=Sybil 천장은 by-construction 밖 — irreducible.)
# KG: span_lakatotree_argue
"""
from __future__ import annotations

from lakatos.verdict.argue import assemble_af, grounded_extension


def _stands(tag: str, rows: list) -> bool:
    arguments, attacks = assemble_af(tag, rows)
    return f"verdict:{tag}" in grounded_extension(arguments, attacks)


def test_self_rebuttal_does_not_defend_verdict():
    """같은 actor A 가 외부 doubt 를 자기 rebuttal 로 막아 verdict 를 세우려는 self-vouch → 방어 엣지 무효."""
    rows = [
        {"id": "T/D", "attacks": "n", "by": "A"},   # doubt: verdict(tag=n) 직접 공격
        {"id": "T/R", "attacks": "D", "by": "A"},   # rebuttal: doubt D 공격(verdict 방어), 같은 actor A
    ]
    assert _stands("n", rows) is False, \
        "자기 doubt 를 자기 rebuttal 로 막아 verdict standing 유지됨 → self-vouch 미봉쇄(H8 결함)"


def test_independent_rebuttal_defends_verdict():
    """과잉차단 회귀가드: *독립* actor B 의 정당한 rebuttal 은 그대로 verdict 를 방어한다(standing 유지)."""
    rows = [
        {"id": "T/D", "attacks": "n", "by": "A"},
        {"id": "T/R", "attacks": "D", "by": "B"},   # 독립 actor → 정당 방어
    ]
    assert _stands("n", rows) is True, "독립 actor 의 정당 방어가 차단됨 → 과잉차단"


def test_doubt_on_verdict_is_actor_agnostic():
    """verdict 직접공격(doubt)은 actor 무관하게 항상 유효(누구나 의심 가능) — 방어 엣지만 actor-gate."""
    rows = [{"id": "T/D", "attacks": "n", "by": "A"}]
    assert _stands("n", rows) is False


def test_assemble_af_without_by_is_backward_compatible():
    """by 누락(레거시 행)이면 self-defense 판정 불가 → 엣지 보존(actor 미상은 차단 안 함, 보수적 하위호환)."""
    rows = [
        {"id": "T/D", "attacks": "n"},   # by 없음
        {"id": "T/R", "attacks": "D"},   # by 없음 → 같은-actor 판정 불가 → 방어 보존
    ]
    assert _stands("n", rows) is True
