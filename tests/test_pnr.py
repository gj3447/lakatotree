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


def test_exception_barring_piecemeal_is_degenerating():
    # 조각적 배제(in_spirit 미지정=방어적) "볼록만 Eulerian" — content 감소, 안 배움
    a = appraise_response(Response.EXCEPTION_BARRING, excess_content=True, novel_corroborated=True)
    assert a.verdict == 'degenerating' and a.learned is False
    assert a.content_direction == 'decrease'


def test_exception_barring_strategic_withdrawal_can_learn():
    # ★나생문 F1: 전략적 후퇴(초과내용 ∧ 휴리스틱 정신) — 라카토스는 이걸 진보 가능으로 봄
    a = appraise_response(Response.EXCEPTION_BARRING, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=True)
    assert a.learned is True and a.verdict == 'progressive'
    a2 = appraise_response(Response.EXCEPTION_BARRING, excess_content=True,
                           novel_corroborated=False, in_heuristic_spirit=True)
    assert a2.verdict == 'conditional'   # 전략적이나 미확증 → 조건부


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


def test_lemma_incorporation_uncorroborated_is_conditional_not_degenerating():
    # ★나생문 F2: ad_hoc₂(내용 있으나 미확증) = 이론적 진보·경험적 대기 = conditional (배웠으니 퇴행 아님)
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=False, in_heuristic_spirit=True)
    assert a.verdict == 'conditional' and a.ad_hoc == 'ad_hoc2' and a.learned is True


def test_lemma_incorporation_against_heuristic_is_ad_hoc3_degenerating():
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=False)
    assert a.verdict == 'degenerating' and a.ad_hoc == 'ad_hoc3'


def test_lemma_incorporation_spirit_unverified_caps_at_conditional():
    # ★나생문 D3: in_heuristic_spirit 미지정(None) → progressive 확정 불가, conditional 로 보류
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=None)
    assert a.verdict == 'conditional' and a.ad_hoc == 'spirit_unverified'


def test_proofs_and_refutations_requires_proof_generated_concept_for_full_progressive():
    # ★나생문 PROOF-GENERATED-CONCEPT: 성숙법(PnR)의 표식 = 증명-생성 개념. 없으면 conditional 강등(load-bearing)
    without = appraise_response(Response.PROOFS_AND_REFUTATIONS, excess_content=True,
                               novel_corroborated=True, in_heuristic_spirit=True)
    assert without.verdict == 'conditional'
    with_pgc = appraise_response(Response.PROOFS_AND_REFUTATIONS, excess_content=True,
                                novel_corroborated=True, in_heuristic_spirit=True,
                                proof_generated_concept=SIMPLY_CONNECTED)
    assert with_pgc.verdict == 'progressive' and with_pgc.proof_generated_concept is not None


# ── 음의 휴리스틱: hard core 위반 = 다른 프로그램 ─────────────────────
def test_hard_core_violation_is_different_programme():
    # AXIS-CORR (audit qual-fidelity): 보조정리 통합 + 내용 다 있어도 hard core 치면
    # *다른 프로그램*(정체성 축) — degenerating(belt 내용-비진보, 진보 축)이 아님.
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, hard_core_preserved=False)
    assert a.verdict == 'different_programme'
    assert any('hard_core' in r for r in a.reasons)


# ── surrender = 철회(진보/퇴행 아님), hard_core 보다 먼저(D1) ─────────
def test_surrender_is_withdrawn():
    a = appraise_response(Response.SURRENDER)
    assert a.verdict == 'withdrawn' and a.learned is False


def test_surrender_checked_before_hard_core():
    # ★나생문 D1: 철회는 hard_core 위반이어도 withdrawn (철회 신호 손실 금지)
    a = appraise_response(Response.SURRENDER, hard_core_preserved=False)
    assert a.verdict == 'withdrawn'


# ── 양의 휴리스틱 = 다음 문제 생성기 (in_spirit 판정 + next 생성) ──────
def test_positive_heuristic_in_spirit():
    h = PositiveHeuristic(hard_core=('V−E+F=2 의 위상불변성',),
                          planned_problemshifts=('단순연결 조건화', 'n-홀 일반화 2−2n'))
    assert h.in_spirit('단순연결 조건화') is True
    assert h.in_spirit('임시 땜빵 정의') is False   # 휴리스틱 밖 → ad hoc₃


def test_positive_heuristic_generates_next_problemshift():
    # ★나생문 POSITIVE-HEURISTIC-OVERSELL: 진짜 생성기 — 미완 첫 problemshift 를 *생성*
    h = PositiveHeuristic(planned_problemshifts=('단순연결 조건화', 'n-홀 일반화 2−2n'))
    assert h.next_problemshift() == '단순연결 조건화'
    assert h.next_problemshift(completed=('단순연결 조건화',)) == 'n-홀 일반화 2−2n'
    assert h.next_problemshift(completed=('단순연결 조건화', 'n-홀 일반화 2−2n')) is None  # 궤도 소진


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


def test_dialectic_conditional_downgrades_progressive_to_conditional():
    # ad_hoc2(배웠으나 미확증) → 메트릭 진보를 progressive_conditional 로 (이론적≠경험적 진보)
    from lakatos.spine import dialectical_verdict
    cond = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=False, in_heuristic_spirit=True)
    d = dialectical_verdict('progressive', pnr_appraisal=cond)
    assert d['verdict'] == 'progressive_conditional' and d['pnr'] == 'conditional'


# ── 명시적 라카토스 oracle (test=generator≠verifier, 나생문 TEST-IS-SELF-VERIFYING) ──
# ground truth = Lakatos(1976) 『Proofs and Refutations』 본문의 실제 판정. 코드가 아니라 *책*이 oracle.
LAKATOS_1976_VERDICTS = {
    # (대응, 라카토스의 판정 요지) — 본문서 그가 직접 평가한 인식적 지위
    Response.MONSTER_BARRING: 'degenerating',      # "괴물 차단은 반례를 진지하게 안 받아 — 못 배운다"
    Response.MONSTER_ADJUSTMENT: 'degenerating',   # 재해석으로 반례 회피 — 못 배운다
    Response.SURRENDER: 'withdrawn',               # 추측 포기
    Response.LEMMA_INCORPORATION: 'progressive',   # 죄있는 보조정리 통합 — 배운다(내용·확증·휴리스틱 충족 시)
    Response.PROOFS_AND_REFUTATIONS: 'progressive',# 성숙법 — 증명-생성 개념까지
}


def test_matches_lakatos_1976_oracle():
    # 외부 oracle(책) 대조 — full-progressive 조건으로 호출해 라카토스 판정과 일치 확인
    for resp, expected in LAKATOS_1976_VERDICTS.items():
        a = appraise_response(resp, excess_content=True, novel_corroborated=True,
                              in_heuristic_spirit=True, proof_generated_concept=SIMPLY_CONNECTED)
        assert a.verdict == expected, f'{resp.value}: 라카토스 판정 {expected} ≠ {a.verdict}'


# ── CounterexampleType 배선 (prom16 engine-axis): 문서화됐으나 미배선이던 public enum 을
#    appraise_response 에 additive 로 배선 — verdict 불변, 숨은 보조정리 진단만 추가 ──

def test_counterexample_type_adds_hidden_lemma_signal_additive():
    from lakatos.pnr import appraise_response, Response, CounterexampleType
    base = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                             novel_corroborated=True, in_heuristic_spirit=True)
    ce = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                           novel_corroborated=True, in_heuristic_spirit=True,
                           counterexample_type=CounterexampleType.LOCAL_NOT_GLOBAL)
    assert ce.verdict == base.verdict                       # additive — verdict 불변
    assert ce.ad_hoc == base.ad_hoc
    assert any('보조정리' in r for r in ce.reasons)          # 숨은 보조정리 진단 추가
    assert not any('보조정리' in r for r in base.reasons)    # 없으면 추가 안 됨(default None)


def test_counterexample_type_global_is_not_hidden_lemma():
    from lakatos.pnr import appraise_response, Response, CounterexampleType
    a = appraise_response(Response.LEMMA_INCORPORATION, excess_content=True,
                          novel_corroborated=True, in_heuristic_spirit=True,
                          counterexample_type=CounterexampleType.GLOBAL)
    assert not any('숨은 보조정리' in r for r in a.reasons)   # GLOBAL=추측 직접 반박, 숨은 보조정리 아님


def test_counterexample_type_default_none_byte_identical():
    from lakatos.pnr import appraise_response, Response
    a = appraise_response(Response.MONSTER_BARRING)
    b = appraise_response(Response.MONSTER_BARRING, counterexample_type=None)
    assert a == b                                            # default None → 완전 동일
