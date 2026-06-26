"""증명과 반박 변증법(Proofs and Refutations, Lakatos 1976) — 라카토트리의 진짜 심장.

라카토스의 핵심: 수학/과학은 단조 누적이 아니라 **추측→증명→반례→대응**의 변증법으로 자란다.
같은 hard core 를 지켜도 *반례에 어떻게 대응하느냐*가 진보/퇴행을 가른다.

★4-way 판정(나생문 라카토스-충실도 후 — 2-way 는 라카토스 곡해였음):
  - withdrawn      : surrender(추측 철회) — 진보/퇴행 축 밖
  - different_programme : hard core 위반(음의 휴리스틱) — 핵을 치면 *다른 프로그램*으로 떠난 것.
                     진보/퇴행 축이 아니라 정체성 축 (AXIS-CORR: 전엔 degenerating 으로 곡해).
  - degenerating   : 안 배움(monster-barring/adjustment, 조각적 exception-barring) ∨ 무내용(ad hoc₁)
                     ∨ 휴리스틱 위배(ad hoc₃)
  - conditional    : *배웠으나* 아직 진보 미확정 — ad hoc₂(초과내용 있으나 미확증 = 이론적 진보·경험적 대기)
                     또는 휴리스틱 정신 미검증. 라카토스의 '이론적 진보 ≠ 경험적 진보' 구분.
  - progressive    : 배움 + 초과내용 + 확증 + 휴리스틱 정합 (PnR 성숙법은 증명-생성 개념까지)

ad hoc 3분류(Lakatos-Zahar): ad hoc₁(초과내용 0) / ad hoc₂(내용 있으나 미확증) / ad hoc₃(휴리스틱 밖).
exception-barring 은 *조각적 배제*(방어적=퇴행)와 *전략적 후퇴*(휴리스틱 내 원리적 축소=배움)를 구분.

엄격도 스택서 이 모듈 = 질적 판정의 *내용*. spine.dialectical_verdict 로 판결 권위에 배선(고아 아님).
정전 예제 = Euler V−E+F=2 + 반례(속빈정육면체 4) + 증명-생성 개념(단순연결).

배선 정직 표기 (prom16 engine-axis):
  - appraise_response : 프로덕션 판결 경로 (server test_result → spine.dialectical_verdict). ★CounterexampleType 도
    counterexample_type 인자로 배선됨(2026-06-14) — verdict 불변, 숨은 보조정리 진단 풍부화.
  - ad_hoc_class / PositiveHeuristic.in_spirit·next_problemshift : public *라이브러리* 표면 — 호출자(연구 프로그램
    계획·문제생성기)가 직접 쓸 수 있는 Lakatos 도구. 최소 appraise 경로엔 없으나 고아 아님(공개 API, 테스트됨).
# KG: span_lakatotree_pnr / q-lkt-lakatos-dialectic-heart
라이선스(THEORY §8): hempel1945 glymour1980
# 출처: grounding.SOURCES[lakatos1976/lakatos1978/zahar1973/lakatos_zahar1976]
"""
from dataclasses import dataclass, replace
from enum import Enum


class CounterexampleType(str, Enum):
    """반례 유형 (Lakatos 1976): 추측(global) vs 증명단계(local) 를 치는지."""
    GLOBAL = 'global'                  # 추측 자체를 반박
    LOCAL = 'local'                    # 증명의 한 보조정리(lemma)를 반박
    LOCAL_AND_GLOBAL = 'local_and_global'      # 둘 다 — lemma-incorporation 의 이상적 출발
    LOCAL_NOT_GLOBAL = 'local_not_global'      # 보조정리는 깨도 추측은 안 깸(숨은 보조정리 신호)
    GLOBAL_NOT_LOCAL = 'global_not_local'      # 추측은 깨는데 단계 불명 → 증명 미흡(숨은 보조정리 탐색)


class Response(str, Enum):
    """반례 대응 6법 (Lakatos 1976). 마지막 둘은 항상 배우고, exception-barring 은 전략적일 때만."""
    SURRENDER = 'surrender'                    # 추측 포기(철회)
    MONSTER_BARRING = 'monster_barring'        # 개념 재정의로 반례 배제 — 안 배움
    EXCEPTION_BARRING = 'exception_barring'    # 도메인 축소 — 조각적(퇴행) or 전략적(배움)
    MONSTER_ADJUSTMENT = 'monster_adjustment'  # 반례 재해석해 반례 아니게 — 안 배움
    LEMMA_INCORPORATION = 'lemma_incorporation'        # 죄있는 보조정리를 조건으로 통합 — 배움
    PROOFS_AND_REFUTATIONS = 'proofs_and_refutations'  # 추측+증명 동시개선, 증명-생성 개념 — 성숙


# content 방향(서술 메타 — 판정의 근거를 설명, 라벨 자체가 게이트는 아님)
CONTENT_DIRECTION = {
    Response.SURRENDER: 'abandon',
    Response.MONSTER_BARRING: 'preserve_by_redefinition',
    Response.EXCEPTION_BARRING: 'decrease',
    Response.MONSTER_ADJUSTMENT: 'preserve_by_reinterpretation',
    Response.LEMMA_INCORPORATION: 'increase_and_deepen',
    Response.PROOFS_AND_REFUTATIONS: 'increase_and_deepen',
}
# 무조건 안 배우는 대응(반례를 진지하게 안 받음)
_NEVER_LEARNS = {Response.MONSTER_BARRING, Response.MONSTER_ADJUSTMENT}

AD_HOC_CLASSES = ('progressive', 'ad_hoc1', 'ad_hoc2', 'ad_hoc3')


def ad_hoc_class(excess_content: bool, novel_corroborated: bool, in_heuristic_spirit: bool) -> str:
    """Lakatos-Zahar 3분류 — 진보 ⟺ 셋 다 통과(이론적∧경험적∧휴리스틱적).

    ad hoc₁(무 초과내용) → ad hoc₂(내용 있으나 미확증) → ad hoc₃(휴리스틱 정신 위배). 순서대로.
    출처: lakatos1978, zahar1973, lakatos_zahar1976.
    """
    if not excess_content:
        return 'ad_hoc1'
    if not novel_corroborated:
        return 'ad_hoc2'
    if not in_heuristic_spirit:
        return 'ad_hoc3'
    return 'progressive'


@dataclass
class PositiveHeuristic:
    """양의 휴리스틱 — hard core 를 지키며 *다음 모델을 생성*하는 문제생성기(Lakatos 1978)."""
    hard_core: tuple = ()
    planned_problemshifts: tuple = ()   # 미리 예견한 모델 개선 궤도(순서)

    def in_spirit(self, move: str) -> bool:
        """move 가 계획 궤도 위인가 — ad hoc₃(휴리스틱 위배)의 반대. (생성 아님, 멤버십 판정)."""
        return move in self.planned_problemshifts

    def next_problemshift(self, completed: tuple = ()) -> str | None:
        """양의 휴리스틱이 *생성*하는 다음 문제 — 계획 궤도서 아직 안 한 첫 problemshift.

        라카토스: 양의 휴리스틱은 반례를 기다리지 않고 다음 모델을 미리 만든다(문제생성기).
        """
        done = set(completed)
        for s in self.planned_problemshifts:
            if s not in done:
                return s
        return None   # 궤도 소진 — 새 휴리스틱 필요


@dataclass
class ProofGeneratedConcept:
    """증명-생성 개념 — 반례 통합 과정서 *탄생한* 개념(예: '단순연결 다면체').

    Lakatos: 성숙 진보의 표식. 개념이 미리 주어진 게 아니라 증명-반박 변증법서 나온다.
    PnR(성숙법)의 full progressive 판정에 load-bearing(없으면 conditional 로 강등).
    """
    name: str
    born_from_counterexample: str       # 어느 반례가 낳았나
    incorporated_lemma: str             # 어느 숨은 보조정리를 조건화했나


@dataclass
class PnRAppraisal:
    verdict: str                # progressive | conditional | degenerating | withdrawn
    learned: bool               # 반례서 배웠는가
    ad_hoc: str                 # progressive | ad_hoc1/2/3 | spirit_unverified | n/a
    content_direction: str
    reasons: tuple = ()
    proof_generated_concept: 'ProofGeneratedConcept | None' = None


def _appraise_learned(response: Response, excess: bool, corrob: bool,
                      spirit: 'bool | None', pgc: 'ProofGeneratedConcept | None') -> tuple:
    """배우는 대응의 ad hoc 평가 → (verdict, ad_hoc_class, reasons). 4-way 매핑."""
    if not excess:
        return 'degenerating', 'ad_hoc1', ['ad_hoc1: 초과 경험내용 없음 — 새 예측 0(이론적 퇴행)']
    if spirit is False:
        return 'degenerating', 'ad_hoc3', ['ad_hoc3: 양의 휴리스틱 밖 임시 땜빵(Zahar)']
    if not corrob:
        return ('conditional', 'ad_hoc2',
                ['ad_hoc2: 초과내용 있으나 미확증 — 이론적 진보·경험적 대기(조건부, 아직 퇴행 아님)'])
    if spirit is None:
        return ('conditional', 'spirit_unverified',
                ['초과내용+확증 but 휴리스틱 정신 미검증 — progressive 확정 보류(조건부, D3)'])
    if response == Response.PROOFS_AND_REFUTATIONS and pgc is None:
        return ('conditional', 'progressive',
                ['성숙법(PnR)인데 증명-생성 개념 미제시 — 조건부(개념 탄생이 성숙 진보의 표식)'])
    msgs = ['반례서 배워 통합 + 초과내용·확증·휴리스틱 정합 → 진보']
    if pgc:
        msgs.append(f'증명-생성 개념 탄생: {pgc.name} (성숙 진보의 표식)')
    return 'progressive', 'progressive', msgs


# 반례 유형이 '숨은 보조정리'를 시사하는 경우 (Lakatos 1976): lemma-incorporation 권장 신호
_HIDDEN_LEMMA = {CounterexampleType.LOCAL_NOT_GLOBAL, CounterexampleType.GLOBAL_NOT_LOCAL}


def _counterexample_note(ct: 'CounterexampleType | None') -> 'str | None':
    """반례 유형 진단 메모 (additive — verdict 불변, 근거만 풍부화). CounterexampleType 배선."""
    if ct is None:
        return None
    if ct in _HIDDEN_LEMMA:
        return (f'반례유형 {ct.value}: 숨은 보조정리 신호 — lemma-incorporation 으로 '
                f'죄있는 보조정리를 조건화 권장 (Lakatos 1976)')
    if ct == CounterexampleType.LOCAL_AND_GLOBAL:
        return f'반례유형 {ct.value}: local+global — lemma-incorporation 의 이상적 출발점'
    return f'반례유형 {ct.value}'


def appraise_response(response: Response, *, excess_content: bool = False,
                      novel_corroborated: bool = False, in_heuristic_spirit: 'bool | None' = None,
                      hard_core_preserved: bool = True,
                      proof_generated_concept: 'ProofGeneratedConcept | None' = None,
                      counterexample_type: 'CounterexampleType | None' = None) -> PnRAppraisal:
    """반례 대응 → 라카토스 4-way 평가. 같은 hard core 라도 *대응 방식*이 판결을 가른다.

    `counterexample_type`(선택)은 verdict 를 바꾸지 않고 *진단 근거*만 풍부화한다 — 반례가
    추측(global)/증명단계(local) 중 무엇을 치는지(Lakatos 1976). LOCAL_NOT_GLOBAL/GLOBAL_NOT_LOCAL
    은 숨은 보조정리 신호 → lemma-incorporation 권장. (기본 None → 기존 동작 byte-identical.)
    """
    a = _appraise_core(response, excess_content, novel_corroborated, in_heuristic_spirit,
                       hard_core_preserved, proof_generated_concept)
    note = _counterexample_note(counterexample_type)
    return replace(a, reasons=a.reasons + (note,)) if note else a


def _appraise_core(response: Response, excess_content: bool, novel_corroborated: bool,
                   in_heuristic_spirit: 'bool | None', hard_core_preserved: bool,
                   proof_generated_concept: 'ProofGeneratedConcept | None') -> PnRAppraisal:
    """핵심 4-way 평가 (counterexample_type 무관 — 순수 대응방식 판정).

    순서(나생문 D1: surrender 가 hard_core 보다 먼저):
      1. surrender → withdrawn (추측 철회 — hard_core 무관).
      2. hard_core 위반 → different_programme (음의 휴리스틱: 핵을 치면 다른 프로그램 — 정체성 축, 퇴행 아님).
      3. monster-barring/adjustment → degenerating (반례 진지하게 안 받음 = 안 배움).
      4. exception-barring → 전략적 후퇴(초과내용 ∧ in_spirit=True)면 배움→ad hoc 평가, 아니면 조각적=degenerating.
      5. lemma-incorporation/PnR → 배움 → ad hoc 평가(progressive/conditional/degenerating).
    """
    direction = CONTENT_DIRECTION[response]
    if response == Response.SURRENDER:
        return PnRAppraisal('withdrawn', False, 'n/a', direction, ('conjecture_surrendered',))
    if not hard_core_preserved:
        # AXIS-CORR (audit qual-fidelity): 핵을 치면 진보/퇴행이 아니라 *다른 프로그램*으로 떠난 것
        # (정체성 축). degenerating(belt 내용-비진보, 진보 축)과 구분 — 안 그러면 MSRP 곡해.
        return PnRAppraisal('different_programme', False, 'n/a', direction,
                            ('hard_core_violated: 음의 휴리스틱 위반 — 다른 프로그램(정체성 축, 퇴행 아님)',))
    if response in _NEVER_LEARNS:
        return PnRAppraisal('degenerating', False, 'n/a', direction,
                            (f'{response.value}: 반례 재정의/재해석으로 회피 — 안 배움',))
    if response == Response.EXCEPTION_BARRING:
        strategic = bool(excess_content) and in_heuristic_spirit is True
        if not strategic:
            return PnRAppraisal('degenerating', False, 'n/a', 'decrease',
                                ('exception_barring(조각적 배제): 도메인 축소 방어 — 안 배움',))
        verdict, klass, msgs = _appraise_learned(response, excess_content, novel_corroborated,
                                                  in_heuristic_spirit, proof_generated_concept)
        return PnRAppraisal(verdict, True, klass, direction,
                            ('exception_barring(전략적 후퇴): 휴리스틱 내 원리적 축소 — 배움', *msgs),
                            proof_generated_concept)
    # lemma-incorporation, proofs-and-refutations
    verdict, klass, msgs = _appraise_learned(response, excess_content, novel_corroborated,
                                             in_heuristic_spirit, proof_generated_concept)
    return PnRAppraisal(verdict, True, klass, direction, tuple(msgs), proof_generated_concept)
