"""승격 게이트 TDD — CANONICAL 승격 전 헌법 강제 (나생문 F-CON-1/2/5).
# KG: span_lakatotree_promote / q-lkt-writepath-enforce
"""
from lakatos.promote import promotion_gate

def test_progressive_stands_promotable():
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=True)
    assert ok and reasons == ()

def test_rejected_blocked():   # F-CON-5: 퇴행 가지 CANONICAL 금지
    ok, reasons = promotion_gate(scripted_verdict='rejected', stands=True)
    assert not ok and 'verdict_is_rejected' in reasons

def test_unresolved_doubt_blocks():   # F-CON-2: 막지못한 의문
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=False)
    assert not ok and 'unresolved_doubt' in reasons

def test_not_reproducible_blocks():   # F-CON-1: 재현 불가 final
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=True, reproducible=False)
    assert not ok and 'not_reproducible' in reasons

def test_reproducible_none_skips_check():  # 비-final 노드는 재현 체크 생략
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=True, reproducible=None)
    assert ok

def test_blocking_reasons_passthrough():   # claim standing 의 blocking_reasons 병합
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=True,
                                 blocking_reasons=('foundation_gap',))
    assert not ok and 'foundation_gap' in reasons

def test_admin_proof_promotable():   # proof/canonical_stage 등 비-rejected 행정상태는 OK
    ok, _ = promotion_gate(scripted_verdict='proof', stands=True)
    assert ok
