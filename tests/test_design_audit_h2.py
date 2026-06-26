"""H2 design-audit guard: CANONICAL floor 의 human 은 *KG 에 영속된 실제 human Argument* 를 요구.

결함(감사 H2): set_verdict 가 has_human_verdict 를 client 1비트(v.human_verdict)로 도출하고,
spine floor(synthesize_promotion)가 그 비트를 영수증으로 믿어 — 인터넷관측 0·재현성 None 인 internal
proof 노드가 client 가 보낸 human_verdict=True 한 줄로 CANONICAL 이 된다(영수증 0).
수정: set_verdict 의 pre-query 가 (cur)-[:HAS_ARGUMENT]->(a:Argument) 의 a.by/a.kind 를 collect 해
  *실제 human attestation Argument 존재*(kind∈{evaluation,verdict} AND a.by 사람 actor)로 has_human 도출.
  v.human_verdict(client bool)는 그 Argument 를 찾으라는 *요청* 으로만 쓰고 단독으로 floor 를 못 연다.

이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 H2 를 progressive 로 자동 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import VerdictIn as _VerdictIn  # noqa: N814 (pytest collection 회피)


def _svc(*, args):
    """internal proof 노드(인터넷관측 0 → credibility None, reproducible None).
    pre-query 는 verdict='proof'/source=None + 주어진 Argument 목록(args)을 돌려준다.
    promotion SET/최종 read 는 통과(노드 존재)."""
    def kg(q, **kw):
        if "HAS_RESEARCH_EVENT" in q:        # 인터넷 관측 없음 → internal 노드
            return []
        if "OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]" in q:   # set_verdict pre-query
            return [dict(verdict="proof", verdict_source=None, source_trust=None,
                         novel_confirmed=False, args=args)]
        if "RETURN e.tag AS tag" in q:       # promotion 후 최종 read (노드 존재)
            return [dict(tag="n")]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                            foundation=lambda n: None,          # foundation 게이트 생략
                            reproducible_for_node=lambda n, t: None)   # 재현성 영수증 없음


def _canon():
    return _VerdictIn(verdict="CANONICAL", human_verdict=True, valid_until_rebutted=True)


def test_human_verdict_floor_requires_real_kg_argument():
    """client human_verdict=True 지만 KG 에 human Argument *없음* → floor 차단(409 no_receipt_for_canonical)."""
    # ★행동적(우회 봉쇄): 영수증 0(internal·재현성 None·human Argument 없음) + client bit True → 409
    with pytest.raises(HTTPException) as e:
        _svc(args=[]).set_verdict("T", "n", _canon())
    assert e.value.status_code == 409
    assert "no_receipt_for_canonical" in str(e.value.detail)


def test_client_human_bit_alone_does_not_open_floor_even_with_nonhuman_arg():
    """비-human Argument(doubt 등)만 있으면 client bit 가 True 여도 floor 안 열린다(human kind 아님)."""
    args = [dict(id="T/doubt1", attacks=None, by="agent:x", kind="doubt")]
    with pytest.raises(HTTPException) as e:
        _svc(args=args).set_verdict("T", "n", _canon())
    assert e.value.status_code == 409
    assert "no_receipt_for_canonical" in str(e.value.detail)


def test_real_human_argument_in_kg_opens_floor():
    """KG 에 실제 human attestation Argument(kind=evaluation, by=사람)가 있으면 floor 통과 → CANONICAL 승격."""
    args = [dict(id="T/eval1", attacks=None, by="human:gira", kind="evaluation")]
    out = _svc(args=args).set_verdict("T", "n", _canon())
    assert out["ok"] is True
