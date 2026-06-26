"""승격 게이트 TDD — CANONICAL 승격 전 헌법 강제 (나생문 F-CON-1/2/5).
# KG: span_lakatotree_promote / q-lkt-writepath-enforce
"""
import pytest

from lakatos.verdict.promote import promotion_gate
from lakatos.verdicts import SCRIPTED_VERDICTS

def test_progressive_stands_promotable():
    ok, reasons = promotion_gate(scripted_verdict='progressive', stands=True)
    assert ok and reasons == ()

def test_rejected_blocked():   # F-CON-5: 퇴행 가지 CANONICAL 금지 (ENG-CORR-1: allowlist 로 전환, 사유 문구 변경)
    ok, reasons = promotion_gate(scripted_verdict='rejected', stands=True)
    assert not ok and 'verdict_not_promotable:rejected' in reasons

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


# ── 정책: scripted 판결 중 *진보*만 CANONICAL 승격 가능 (라카토스 코어) ──
#   partial(보호대 패치)·equivalent(무진전)은 verdicts.NONPROGRESSIVE 인데 전엔 'rejected'만 막아
#   승격됐다 — 보호대 패치가 정본(CANONICAL)이 되는 theory-impl 괴리. 이제 PROGRESS SSOT 에서 derive.
PROMOTABLE_SCRIPTED = {'progressive'}   # SCRIPTED_VERDICTS & PROGRESS_VERDICTS


@pytest.mark.parametrize('v', sorted(SCRIPTED_VERDICTS))
def test_scripted_verdict_promotable_partition(v):
    """전 SCRIPTED_VERDICTS 파티션 고정(fail-closed): 새 어휘는 명시적으로 진보 분류돼야 승격 가능."""
    ok, reasons = promotion_gate(scripted_verdict=v, stands=True, reproducible=True)
    if v in PROMOTABLE_SCRIPTED:
        assert ok, f'{v} 가 부당하게 차단됨'
    else:
        assert not ok and f'verdict_not_promotable:{v}' in reasons, \
            f'{v} 가 승격됨 (보호대 패치/무진전/퇴행이 CANONICAL 누수)'


def test_partial_and_equivalent_blocked_through_synthesize():
    """헌법 게이트(synthesize_promotion)도 동일 파티션 — partial/equivalent 는 CANONICAL 불가."""
    from lakatos.verdict.spine import synthesize_promotion
    for v in ('partial', 'equivalent'):
        out = synthesize_promotion(scripted_verdict=v, stands=True, reproducible=True)
        assert out['ok'] is False, f'{v} 가 synthesize 승격됨'
        assert not out['gates']['constitution']['passed']
