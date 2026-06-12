"""증명과 반박 변증법 TDD — 라카토스 정전 예제(Euler V−E+F=2)로 검증.

이 테스트의 ground truth = Lakatos(1976) 『Proofs and Refutations』 본문의 실제 판정.
엔진이 그의 반례들을 *그가 분류한 대로* 판정하면, 어휘만이 아니라 변증법을 구현한 것.
# KG: span_lakatotree_pnr / q-lkt-lakatos-dialectic-heart
"""
import pytest

from lakatos.pnr import (
    Response, CounterexampleType, ad_hoc_class, appraise_response,
    PositiveHeuristic, ProofGeneratedConcept, AD_HOC_CLASSES,
)

# Euler 다면체 공식 정전 반례: 속빈 정육면체(cube-in-cube) → V−E+F=4 (global counterexample)
HOLLOW_CUBE = '속빈 정육면체 V−E+F=4'
SIMPLY_CONNECTED = ProofGeneratedConcept(
    name='단순연결 다면체(simply-connected polyhedron)',
    born_from_counterexample=HOLLOW_CUBE,
    incorporated_lemma='다면체는 한 점에서 평면으로 펼쳐진다(단순연결)',
)


# ── ad hoc 3분류 (Lakatos-Zahar) ──────────────────────────────────────
def test_ad_hoc_typology():
    assert ad_hoc_class(excess_content=False, novel_corroborated=False, in_heuristic_spirit=True) == 'ad_hoc1'
    assert ad_hoc_class(excess_content=True, novel_corroborated=False, in_heuristic_spirit=True) == 'ad_hoc2'
    assert ad_hoc_class(excess_content=True, novel_corroborated=True, in_heuristic_spirit=False) == 'ad_hoc3'
    assert ad_hoc_class(excess_content=True, novel_corroborated=True, in_heuristic_spirit=True) == 'progressive'


def test_ad_hoc_order_ad_hoc1_takes_precedence():
    # 초과내용 없으면 확증/휴리스틱 무관하게 ad_hoc1
    assert ad_hoc_class(False, True, True) == 'ad_hoc1'


# ── 반례 대응: 안 배우는 3법 = 퇴행 (Lakatos 본문 판정) ────────────────
def test_monster_barring_is_degenerating():
    # "속빈 정육면체는 다면체가 아니다" — 개념 재정의로 배제, 안 배움
    a = appraise_response(Response.MONSTER_BARRING, excess_content=True, novel_corroborated=True)
    assert a.verdict == 'degenerating' and a.learned is False
    assert any('monster_barring' in r for r in a.reasons)


def test_exception_barring_is_degenerating_content_decrease():
    # "볼록 다면체만 Eulerian" — 도메인 축소, content 감소
    a = appraise_response(Response.EXCEPTION_BARRING, excess_content=True, novel_corroborated=True)
    assert a.verdict == 'degenerating' and a.learned is False
    assert a.content_direction == 'decrease'


def test_monster_adjustment_is_degenerating():
    a = appraise_response(Response.MONSTER_ADJUSTMENT)
    assert a.verdict == 'degenerating' and a.learned is False


# ── 보조정리 통합 = 진보 (단 ad hoc 아닐 때) ──────────────────────────
def test_lemma_incorporation_progressive_with_proof_generated_concept():
    # 숨은 보조정리 '단순연결'을 조건으로 통합 → V−E+F=2−2n 으로 심화, 증명-생성 개념 탄생
    a = appraise_response(
        Response.LEMMA_INCORPORATION,
        excess_content=True, novel_corroborated=True, in_heuristic_spirit=True,
        proof_generated_concept=SIMPLY_CONNECTED,
    )
    assert a.verdict == 'progressive' and a.learned is True and a.ad_hoc == 'progressive'
    assert a.content_direction == 'increase_and_deepen'
    assert a.proof_generated_concept.name.startswith('단순연결')
    assert any('증명-생성 개념' in r for r in a.reasons)


def test_lemma_incorporation_no_content_is_ad_hoc1_degenerating():
    # 통합했지만 초과내용 0 → ad_hoc1 → 퇴행 (통합만으론 부족 — 라카토스 핵심 nuance)
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=False)
    assert a.verdict == 'degenerating' and a.learned is True and a.ad_hoc == 'ad_hoc1'


def test_lemma_incorporation_uncorroborated_is_ad_hoc2():
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True, novel_corroborated=False)
    assert a.verdict == 'degenerating' and a.ad_hoc == 'ad_hoc2'


def test_lemma_incorporation_against_heuristic_is_ad_hoc3():
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=False)
    assert a.verdict == 'degenerating' and a.ad_hoc == 'ad_hoc3'


def test_proofs_and_refutations_mature_method_progressive():
    a = appraise_response(Response.PROOFS_AND_REFUTATIONS, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=True)
    assert a.verdict == 'progressive' and a.learned is True


# ── 음의 휴리스틱: hard core 위반 = 다른 프로그램 ─────────────────────
def test_hard_core_violation_is_degenerating_regardless():
    # 보조정리 통합 + 내용 다 있어도 hard core 치면 퇴행(다른 프로그램)
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, hard_core_preserved=False)
    assert a.verdict == 'degenerating'
    assert any('hard_core' in r for r in a.reasons)


# ── surrender = 철회(진보/퇴행 아님) ──────────────────────────────────
def test_surrender_is_withdrawn():
    a = appraise_response(Response.SURRENDER)
    assert a.verdict == 'withdrawn' and a.learned is False


# ── 양의 휴리스틱 = 다음 문제 생성기 (in_spirit → ad hoc₃ 판정) ───────
def test_positive_heuristic_in_spirit():
    h = PositiveHeuristic(hard_core=('V−E+F=2 의 위상불변성',),
                          planned_problemshifts=('단순연결 조건화', 'n-홀 일반화 2−2n'))
    assert h.in_spirit('단순연결 조건화') is True
    assert h.in_spirit('임시 땜빵 정의') is False   # 휴리스틱 밖 → ad hoc₃


def test_response_enum_completeness():
    # 6법 모두 존재 (Lakatos 정전)
    assert {r.value for r in Response} == {
        'surrender', 'monster_barring', 'exception_barring',
        'monster_adjustment', 'lemma_incorporation', 'proofs_and_refutations'}


# ── 변증법이 판결 권위(spine)에 배선 — 고아 아님 ──────────────────────
def test_dialectic_downgrades_metric_progressive_on_monster_barring():
    # 메트릭은 진보인데 monster-barring 대응 → 변증법이 퇴행으로 강등(라카토스의 심장)
    from lakatos.spine import dialectical_verdict
    mb = appraise_response(Response.MONSTER_BARRING, excess_content=True, novel_corroborated=True)
    d = dialectical_verdict('progressive', pnr_appraisal=mb)
    assert d['verdict'] == 'degenerating' and d['status'] == 'dialectic_overrides'


def test_dialectic_keeps_progressive_on_good_lemma_incorporation():
    from lakatos.spine import dialectical_verdict
    li = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                           novel_corroborated=True, in_heuristic_spirit=True,
                           proof_generated_concept=SIMPLY_CONNECTED)
    d = dialectical_verdict('progressive', pnr_appraisal=li)
    assert d['verdict'] == 'progressive' and d['pnr'] == 'progressive' and d['ad_hoc'] == 'progressive'


def test_dialectic_no_pnr_falls_back_to_reconcile():
    from lakatos.spine import dialectical_verdict
    d = dialectical_verdict('partial')
    assert d['verdict'] == 'partial'   # 반례 대응 없으면 reconcile 그대로
