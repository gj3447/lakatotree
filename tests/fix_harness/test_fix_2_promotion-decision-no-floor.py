"""FIX-HARNESS #2 (P3 dead-code / latent fail-open): promotion_decision() lacks the CANONICAL floor gate.

finding id: #2 — [CLOSED-BY-DELETION 2026-07-23, engine-unify / q-lkt-engine-unify]
원래 결함(2026-06-27 문서화): spine 에 승격 composer 가 둘(promotion_decision / synthesize_promotion)이고
전자는 CANONICAL floor('no_receipt_for_canonical')가 없어 라우팅되는 순간 receipt-0 CANONICAL fail-open.
2026-06-27 에는 floor 추가로 봉합했으나, 이중 권위 자체가 drift 의 원천이었다(한쪽만 고치면 다른 쪽이 샌다).

최종 처분(engine-unify 2026-07-23): 문서화된 선택지 "delete promotion_decision, OR route it through the
same floor gate" 중 **삭제**를 택했다 — 프로덕션 호출부 0인 사장 composer 를 남기는 것은 다음 drift 의
씨앗이므로. 승격 합성 권위는 synthesize_promotion 단일.

이 파일은 부활 방지 가드로 전환됐다:
  ① 제2 composer 가 부활하지 않는다(hasattr 가드),
  ② 유일 권위 synthesize_promotion 의 floor 계약은 그대로다(긍정 oracle — 회귀 시 RED).
"""
from __future__ import annotations

import lakatos.verdict.spine as spine
from lakatos.verdict.spine import synthesize_promotion

# A PROMOTABLE but NON-scripted-receipt candidate: passes the constitution gate yet carries no
# forgery-proof receipt (not a judge verdict, reproducible=None, no human).
_RECEIPT0_CANONICAL = dict(scripted_verdict='progressive_conditional', stands=True, reproducible=None)


def test_second_promotion_composer_does_not_resurrect():
    """부활 방지: spine 의 승격 composer 는 synthesize_promotion 하나여야 한다."""
    assert not hasattr(spine, 'promotion_decision'), (
        "제2 승격 composer 부활 — 이중 권위는 floor drift 의 원천(2026-06-27 결함 재현 경로). "
        "승격 합성은 synthesize_promotion 단일 권위만.")


def test_synthesize_promotion_floor_blocks_receipt0_canonical():
    """긍정 oracle: 유일 권위의 floor 계약 — receipt-0 candidate 는 절대 통과하지 않는다."""
    out = synthesize_promotion(**_RECEIPT0_CANONICAL)
    assert out['ok'] is False
    assert 'no_receipt_for_canonical' in out['reasons']
    assert out['gates']['floor']['passed'] is False
    # Sanity: a genuine judge receipt (scripted progressive, default source vocabulary) still passes
    # the floor, so the gate is a floor and not a blanket deny.
    assert synthesize_promotion(scripted_verdict='progressive', stands=True, reproducible=None)['ok'] is True
