"""엔진 spine — 단일 판결 권위 (나생문 F-ARCH-1: 두 엔진 분리 해소).

문제: judge.py(메트릭 판결)와 engine.LakatosGate(질적 판결)가 따로 놀았다.
  서버는 judge 만 부르고 LakatosGate/FoundationGate/CredibilityPromotionGate 는 고아.
해법: 이 spine 이 모든 게이트를 합성해 단일 결정을 낸다. 서버는 spine 만 부른다.
  reconcile_verdict  = judge(메트릭) + LakatosGate(질적) → 둘 다 진보여야 진보
  promotion_decision = promotion_gate + FoundationGate(준비도) + 재현성 + CredibilityPromotionGate
# KG: span_lakatotree_spine / q-lkt-engine-unify
"""
from .promote import promotion_gate
from .engine import FoundationGate, CredibilityPromotionGate, CredibilityTier
from .pnr import PnRAppraisal
from .grounding import GROUNDED   # P6-3: credibility tier 문턱 단일 정본(engine 과 공유)

_CRED_EXT = GROUNDED['credibility_extracted_trust']['value']   # 0.70
_CRED_INF = GROUNDED['credibility_inferred_trust']['value']    # 0.35


def credibility_from_trust(source_trust: float, *, novel_confirmed: bool = False,
                           has_human_verdict: bool = False) -> dict:
    """노드의 source_trust(상계 인터넷 증거 신뢰) → CredibilityPromotionGate 입력.

    CANONICAL 승격 = EXTRACTED 등급 승격으로 본다. 현재 등급은 trust 로 도출:
      trust>=0.70 → EXTRACTED(이미 최강, 게이트 자명 통과 — bash 지반·고신뢰는 막지 않음)
      0.35<=trust<0.70 → INFERRED, trust<0.35 → AMBIGUOUS.
    즉 게이트는 source_trust<0.70 인 진짜 저신뢰 인터넷 영향 노드만 직접출처/인간판정 없이 차단.
    엔진 SourceCredibilityScore.tier 의 trust 임계와 동형 (provenance 미상이라 trust-only 보수 매핑).
    """
    if source_trust >= _CRED_EXT:
        current = CredibilityTier.EXTRACTED
    elif source_trust >= _CRED_INF:
        current = CredibilityTier.INFERRED
    else:
        current = CredibilityTier.AMBIGUOUS
    return {
        'current': current,
        'target': CredibilityTier.EXTRACTED,   # CANONICAL = 최강 주장
        'has_direct_source': source_trust >= _CRED_EXT,
        'has_independent_corroboration': bool(novel_confirmed),
        'has_human_verdict': bool(has_human_verdict),
    }


def reconcile_verdict(metric_verdict: str, lakatos_result=None) -> dict:
    """judge 메트릭 판결 + LakatosGate 질적 판결 합의.

    메트릭이 비진보면 그대로(개선 없으면 진보 아님). 메트릭이 진보면 질적 게이트가 최종 판정
    (hard_core 위반·excess content 부재 = degenerating, 미완 = conditional). 증거 없으면 unverified.
    """
    if metric_verdict != 'progressive':
        # 메트릭 비진보면 metric 이 verdict 를 결정(개선 없으면 진보 아님). 단 질적 진단을 *버리지 않는다*
        # (audit qual-fidelity bug fix 2026-06-18): 전엔 lakatos='n/a' 로 단락해 partial/equivalent/rejected
        # 노드의 hard_core 위반·퇴행 belt 신호가 조용히 사라졌다. verdict 는 안 바꾸고 질적 진단을 동봉.
        out = {'verdict': metric_verdict, 'lakatos': 'n/a', 'status': 'metric_decided', 'reasons': ()}
        if lakatos_result is not None:
            out['lakatos'] = lakatos_result.verdict.value
            out['qualitative_reasons'] = tuple(lakatos_result.reasons)
        return out
    if lakatos_result is None:
        return {'verdict': 'progressive', 'lakatos': 'unverified', 'status': 'qualitative_unverified',
                'reasons': ('lakatos_evidence_missing',)}
    return {'verdict': lakatos_result.verdict.value, 'lakatos': lakatos_result.verdict.value,
            'status': 'reconciled', 'reasons': tuple(lakatos_result.reasons),
            'requires_human': bool(getattr(lakatos_result, 'requires_human_verdict', False))}


def dialectical_verdict(metric_verdict: str, pnr_appraisal: 'PnRAppraisal | None' = None,
                        lakatos_result=None) -> dict:
    """judge(메트릭) + 증명과반박 변증법 + LakatosGate 합성 — 라카토스의 심장.

    반례 대응(monster-barring 등)이 부적절하면 메트릭이 진보라도 변증법이 퇴행으로 강등한다.
    PnR progressive 면 reconcile 결과 유지 + ad_hoc 등급 부착. 반례 대응 없으면 reconcile 그대로.
    """
    base = reconcile_verdict(metric_verdict, lakatos_result)
    if pnr_appraisal is None:
        return base
    pv = pnr_appraisal.verdict
    if pv in ('degenerating', 'withdrawn', 'different_programme'):   # 변증법 우선 강등 (안 배움/철회/핵이탈)
        return {'verdict': pv, 'lakatos': base.get('lakatos', 'n/a'),
                'status': 'dialectic_overrides', 'pnr': pv,
                'ad_hoc': pnr_appraisal.ad_hoc, 'reasons': tuple(pnr_appraisal.reasons)}
    if pv == 'conditional':   # 배웠으나 미확정 — 메트릭 진보를 조건부로 (라카토스 이론적≠경험적 진보)
        out = {**base, 'pnr': 'conditional', 'ad_hoc': pnr_appraisal.ad_hoc,
               'status': 'dialectic_conditional', 'reasons': tuple(pnr_appraisal.reasons)}
        if base.get('verdict') == 'progressive':
            out['verdict'] = 'progressive_conditional'
        return out
    return {**base, 'pnr': 'progressive', 'ad_hoc': pnr_appraisal.ad_hoc,
            'status': base.get('status', '') + '+pnr_progressive'}


def promotion_decision(*, scripted_verdict: str, stands: bool, reproducible: bool | None = None,
                       foundation_gaps: tuple = (), credibility_reasons: tuple = ()) -> tuple[bool, tuple]:
    """모든 승격 게이트 합성 (F-CON-1/2/5 + Foundation + Credibility) → 단일 결정."""
    _, reasons = promotion_gate(scripted_verdict=scripted_verdict, stands=stands, reproducible=reproducible)
    block = list(reasons)
    if foundation_gaps:
        block.append('foundation_gaps:' + ','.join(foundation_gaps))
    block.extend(credibility_reasons)
    return (not block, tuple(block))


def synthesize_promotion(*, scripted_verdict: str, stands: bool, reproducible: bool | None = None,
                         foundation=None, credibility: dict | None = None) -> dict:
    """완전 합성 승격 게이트 — 헌법(promotion_gate) + FoundationGate(준비도) +
    CredibilityPromotionGate(인터넷 등급). 입력 있는 게이트만 실행, 단일 결정 + per-gate 리포트.

    이게 강건한 엔진의 척추: 서버가 가진 신호를 흘려보내면 모든 게이트가 합의해 차단/통과.
    """
    block: list[str] = []
    gates: dict = {}
    _, pr = promotion_gate(scripted_verdict=scripted_verdict, stands=stands, reproducible=reproducible)
    gates['constitution'] = {'passed': not pr, 'reasons': list(pr)}
    block.extend(pr)
    if foundation is not None:
        fr = FoundationGate.evaluate(foundation)
        gates['foundation'] = {'passed': fr.passed, 'reasons': list(fr.reasons)}
        if not fr.passed:
            block.append('foundation_gaps:' + ','.join(fr.reasons))
    if credibility is not None:
        cr = CredibilityPromotionGate.evaluate(**credibility)
        gates['credibility'] = {'passed': cr.passed, 'reasons': list(cr.reasons)}
        if not cr.passed:
            block.extend(cr.reasons)
    return {'ok': not block, 'reasons': tuple(block), 'gates': gates}
