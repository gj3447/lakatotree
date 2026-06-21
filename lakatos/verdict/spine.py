"""엔진 spine — 단일 판결 권위 (나생문 F-ARCH-1: 두 엔진 분리 해소).

문제: judge.py(메트릭 판결)와 engine.LakatosGate(질적 판결)가 따로 놀았다.
  서버는 judge 만 부르고 LakatosGate/FoundationGate/CredibilityPromotionGate 는 고아.
해법: 이 spine 이 모든 게이트를 합성해 단일 결정을 낸다. 서버는 spine 만 부른다.
  reconcile_verdict  = judge(메트릭) + LakatosGate(질적) → 둘 다 진보여야 진보
  promotion_decision = promotion_gate + FoundationGate(준비도) + 재현성 + CredibilityPromotionGate
# KG: span_lakatotree_spine / q-lkt-engine-unify
"""
from lakatos.verdict.compose import GateOutcome, compose_gates
from lakatos.verdict.promote import promotion_gate
from lakatos.verdicts import is_scripted_verdict
from lakatos.engine import FoundationGate, CredibilityPromotionGate, CredibilityTier
from lakatos.verdict.pnr import PnRAppraisal
from lakatos.grounding import GROUNDED   # P6-3: credibility tier 문턱 단일 정본(engine 과 공유)

_CRED_EXT = GROUNDED['credibility_extracted_trust']['value']   # 0.70
_CRED_INF = GROUNDED['credibility_inferred_trust']['value']    # 0.35


def credibility_from_trust(source_trust: float, *, novel_confirmed: bool = False,
                           has_human_verdict: bool = False, trust_backed: bool = False) -> dict:
    """노드의 source_trust(상계 인터넷 증거 신뢰) → CredibilityPromotionGate 입력.

    CANONICAL 승격 = EXTRACTED 등급 승격으로 본다. 현재 등급은 trust 로 도출:
      trust>=0.70 → EXTRACTED(이미 최강, 게이트 자명 통과 — bash 지반·고신뢰는 막지 않음)
      0.35<=trust<0.70 → INFERRED, trust<0.35 → AMBIGUOUS.
    즉 게이트는 source_trust<0.70 인 진짜 저신뢰 인터넷 영향 노드만 직접출처/인간판정 없이 차단.
    엔진 SourceCredibilityScore.tier 의 trust 임계와 동형 (provenance 미상이라 trust-only 보수 매핑).
    """
    # prom-honesty/credibility (정본 prom 2026-06-21): trust 는 *eigentrust 로 뒷받침될 때만*(trust_backed=True)
    #   credibility 영수증으로 인정한다. raw client source_trust(TestResultIn 기본 1.0=self-report)는 inconclusive
    #   → 직접출처 없음·현재등급 AMBIGUOUS 로 강등해 EXTRACTED(CANONICAL)는 has_human_verdict 를 요구한다.
    #   게이트 *의도*(고신뢰 grounded 통과)는 보존하되 '고신뢰'를 self-report 가 아니라 네트워크 eigentrust 로
    #   판정한다 — set_verdict 가 노드의 인터넷 관측 그래프 eigentrust 로 backed/value 를 결정해 넘긴다.
    #   (3치 논리: 뒷받침 없는 trust = inconclusive ≠ pass.) internal 노드는 set_verdict 가 credibility=None 으로
    #   아예 생략(constitution+reproducible 가 영수증) — fake source-trust 로 통과시키지 않는다.
    if trust_backed and source_trust >= _CRED_EXT:
        current = CredibilityTier.EXTRACTED
    elif trust_backed and source_trust >= _CRED_INF:
        current = CredibilityTier.INFERRED
    else:
        current = CredibilityTier.AMBIGUOUS   # unbacked(self-report) 또는 저신뢰 → inconclusive
    return {
        'current': current,
        'target': CredibilityTier.EXTRACTED,   # CANONICAL = 최강 주장
        'has_direct_source': bool(trust_backed and source_trust >= _CRED_EXT),   # eigentrust-backed 만 직접출처
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


def reconcile_standing(verdict: str, *, stands: bool, valid_until_rebutted: bool = True) -> dict:
    """새 반박이 grounded standing 을 깼을 때의 *대칭* 판결 — certify.py:13 의 '자동 철회' 이행.

    승격이 stands 를 *요구*했듯(synthesize_promotion), 비판 등재 후 stands=False 가 되면 CANONICAL 의
    '현재 최선' 자격을 철회한다(→ former_canonical). 결정론 grounded_extension 사실에만 근거(스코어
    게이트 승격 아님). 강등은 verdict_source='engine' 으로 인간 행정판결과 구분하며, 반박이 해소돼
    stands 가 회복되면 별도 인간/승격 경로로 되돌릴 수 있다(영구 기각 아님).

    인간경계 존중(DON'T): `valid_until_rebutted`(승격 시 인간이 설정, schema default True)가
    - True  → '반박되면 무효'에 *동의*한 노드 → 자동 강등 대상.
    - False → 인간이 반박-자동무효를 *끈* 노드(더 강한 잠금) → 자동 강등 제외(human_locked).
    CANONICAL 이 아닌 노드는 자동 강등 대상이 아니다(현재최선 철회만 자동; 일반 노드 stands=False 는
    standing 진단으로만 노출 — judgement 은 순수 agent/인간 몫).

    반환: {verdict, demoted, reason, [current_best_pointer, verdict_source, standing_broken]}.
    """
    if stands:
        return {'verdict': verdict, 'demoted': False, 'reason': 'stands'}
    if verdict != 'CANONICAL':
        return {'verdict': verdict, 'demoted': False, 'reason': 'not_canonical',
                'standing_broken': True}
    if not valid_until_rebutted:
        return {'verdict': verdict, 'demoted': False, 'standing_broken': True,
                'reason': 'human_locked_not_valid_until_rebutted'}
    return {'verdict': 'former_canonical', 'demoted': True, 'current_best_pointer': False,
            'verdict_source': 'engine', 'standing_broken': True,
            'reason': 'unanswered_rebuttal_breaks_grounded_standing'}


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
    out = compose_gates(
        GateOutcome('constitution', tuple(reasons)),
        GateOutcome('foundation', ('foundation_gaps:' + ','.join(foundation_gaps),))
        if foundation_gaps else None,
        GateOutcome('credibility', tuple(credibility_reasons)),
    )
    return (out.passed, out.reasons)


def synthesize_promotion(*, scripted_verdict: str, stands: bool, reproducible: bool | None = None,
                         foundation=None, credibility: dict | None = None) -> dict:
    """완전 합성 승격 게이트 — 헌법(promotion_gate) + FoundationGate(준비도) +
    CredibilityPromotionGate(인터넷 등급). 입력 있는 게이트만 실행, 단일 결정 + per-gate 리포트.

    이게 강건한 엔진의 척추: 서버가 가진 신호를 흘려보내면 모든 게이트가 합의해 차단/통과.
    """
    gates: dict = {}
    _, pr = promotion_gate(scripted_verdict=scripted_verdict, stands=stands, reproducible=reproducible)
    gates['constitution'] = {'passed': not pr, 'reasons': list(pr)}
    outcomes = [GateOutcome('constitution', tuple(pr))]
    if foundation is not None:
        fr = FoundationGate.evaluate(foundation)
        gates['foundation'] = {'passed': fr.passed, 'reasons': list(fr.reasons)}
        outcomes.append(GateOutcome(
            'foundation', () if fr.passed else ('foundation_gaps:' + ','.join(fr.reasons),)))
    if credibility is not None:
        cr = CredibilityPromotionGate.evaluate(**credibility)
        gates['credibility'] = {'passed': cr.passed, 'reasons': list(cr.reasons)}
        outcomes.append(GateOutcome('credibility', () if cr.passed else tuple(cr.reasons)))
    # prom-honesty/provenance (정본 prom 2026-06-21): CANONICAL FLOOR — *위조불가 영수증* ≥1 요구.
    #   R3 발견: skip-on-omission 으로 게이트가 constitution-only("기각아님+무critique")로 붕괴하면 내부 proof
    #   노드가 영수증 0으로 CANONICAL 이 된다. 하드코어("영수증은 현실이 끊어준다")·3치(무영수증=inconclusive≠
    #   pass)·Lakatos(CANONICAL=최강주장→최강영수증). 위조불가 영수증 = judge-scored 판결(scripted; PROM-A 가
    #   노드 self-report 봉쇄) | reproducible=True(실 lineage replay) | human verdict. credibility/foundation 은
    #   아직 self-report 우회(source_type/evidence)가 남아 floor 영수증으로 *안* 센다(보수적; 그 가닥은 후속 prom).
    has_human = bool(credibility and credibility.get('has_human_verdict'))
    if is_scripted_verdict(scripted_verdict) or reproducible is True or has_human:
        gates['floor'] = {'passed': True, 'reasons': []}
    else:
        gates['floor'] = {'passed': False, 'reasons': ['no_receipt_for_canonical']}
        outcomes.append(GateOutcome('floor', ('no_receipt_for_canonical',)))
    out = compose_gates(*outcomes)
    return {'ok': out.passed, 'reasons': out.reasons, 'gates': gates}
