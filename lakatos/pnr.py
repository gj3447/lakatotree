"""증명과 반박(Proofs and Refutations, Lakatos 1976)의 변증법 — 라카토트리의 진짜 심장.

라카토스의 핵심 통찰: 수학/과학은 단조 누적이 아니라 **추측→증명→반례→대응**의 변증법으로 자란다.
같은 hard core 를 지켜도 *반례에 어떻게 대응하느냐*가 진보/퇴행을 가른다:
  - monster-barring(개념 재정의로 배제): 반례서 *안 배움* → 퇴행
  - exception-barring(도메인 축소): content 감소, 방어적 후퇴 → 퇴행
  - lemma-incorporation(죄있는 보조정리를 조건으로 통합): 반례서 *배움*, 증명-생성 개념 → 진보(단 ad hoc 아닐 때)
라카토스는 lemma-incorporation/proofs-and-refutations 를 선호 — 반례를 진지하게 받아 배우기 때문.

+ ad hoc 3분류(Lakatos-Zahar): 어떤 수정이 진보이려면 셋 다 통과해야:
  ad hoc₁ = 초과 경험내용 없음(새 예측 0) / ad hoc₂ = 내용 있으나 미확증 / ad hoc₃ = 휴리스틱 정신 위배.
  progressive ⟺ 이론적(초과내용 novel 예측) ∧ 경험적(일부 확증) ∧ 휴리스틱적(양의 휴리스틱 정신).

엄격도 스택서 이 모듈 = 질적 판정의 *내용*. judge(포퍼 이산)·bayes(연속)·laudan(문제수지) 위에서
"진보라는 판결이 라카토스 의미로 진짜 진보인가"를 변증법으로 검증.
정전 예제 = Euler 다면체 공식 V−E+F=2 + 반례(속빈정육면체 4, 액자/토러스 0) + 증명-생성 개념(단순연결).
# KG: span_lakatotree_pnr / q-lkt-lakatos-dialectic-heart
# 출처: grounding.SOURCES[lakatos1976/lakatos1978/zahar1973/lakatos_zahar1976]
"""
from dataclasses import dataclass, field
from enum import Enum


class CounterexampleType(str, Enum):
    """반례 유형 (Lakatos 1976): 추측(global) vs 증명단계(local) 를 치는지."""
    GLOBAL = 'global'                  # 추측 자체를 반박
    LOCAL = 'local'                    # 증명의 한 보조정리(lemma)를 반박
    LOCAL_AND_GLOBAL = 'local_and_global'      # 둘 다 — lemma-incorporation 의 이상적 출발
    LOCAL_NOT_GLOBAL = 'local_not_global'      # 보조정리는 깨도 추측은 안 깸(숨은 보조정리 신호)
    GLOBAL_NOT_LOCAL = 'global_not_local'      # 추측은 깨는데 어느 단계? → 증명 미흡(숨은 보조정리 탐색)


class Response(str, Enum):
    """반례 대응 6법 (Lakatos 1976). 마지막 둘만 '배운다'."""
    SURRENDER = 'surrender'                    # 추측 포기(철회)
    MONSTER_BARRING = 'monster_barring'        # 개념 재정의로 반례 배제 — 안 배움
    EXCEPTION_BARRING = 'exception_barring'    # 도메인 축소("볼록 다면체만") — content 감소
    MONSTER_ADJUSTMENT = 'monster_adjustment'  # 반례를 재해석해 반례 아니게 — 안 배움
    LEMMA_INCORPORATION = 'lemma_incorporation'        # 죄있는 보조정리를 조건으로 통합 — 배움
    PROOFS_AND_REFUTATIONS = 'proofs_and_refutations'  # 추측+증명 동시개선, 증명-생성 개념 — 성숙


# 반례서 배우는가 (Lakatos 의 인식적 평가)
LEARNS_FROM_COUNTEREXAMPLE = {
    Response.SURRENDER: False,
    Response.MONSTER_BARRING: False,
    Response.EXCEPTION_BARRING: False,
    Response.MONSTER_ADJUSTMENT: False,
    Response.LEMMA_INCORPORATION: True,
    Response.PROOFS_AND_REFUTATIONS: True,
}
# content 방향: 통합/PnR 만 내용 증가(심화), 예외차단은 감소, 괴물차단은 재정의로 보존(가짜)
CONTENT_DIRECTION = {
    Response.SURRENDER: 'abandon',
    Response.MONSTER_BARRING: 'preserve_by_redefinition',
    Response.EXCEPTION_BARRING: 'decrease',
    Response.MONSTER_ADJUSTMENT: 'preserve_by_reinterpretation',
    Response.LEMMA_INCORPORATION: 'increase_and_deepen',
    Response.PROOFS_AND_REFUTATIONS: 'increase_and_deepen',
}

AD_HOC_CLASSES = ('progressive', 'ad_hoc1', 'ad_hoc2', 'ad_hoc3')


def ad_hoc_class(excess_content: bool, novel_corroborated: bool, in_heuristic_spirit: bool) -> str:
    """Lakatos-Zahar 3분류 — 진보 ⟺ 셋 다 통과(이론적∧경험적∧휴리스틱적).

    ad hoc₁(무 초과내용) → ad hoc₂(내용 있으나 미확증) → ad hoc₃(휴리스틱 정신 위배). 순서대로 검사.
    출처: lakatos1978, zahar1973, lakatos_zahar1976.
    """
    if not excess_content:
        return 'ad_hoc1'        # 초과 경험내용 없음 — 새 예측 0(degenerating)
    if not novel_corroborated:
        return 'ad_hoc2'        # 내용 있으나 확증된 novel 사실 0(아직 진보 미확정)
    if not in_heuristic_spirit:
        return 'ad_hoc3'        # 양의 휴리스틱 밖 임시 땜빵(Zahar)
    return 'progressive'


@dataclass
class PositiveHeuristic:
    """양의 휴리스틱 — hard core 를 지키며 *다음 모델을 생성*하는 문제생성기(Lakatos 1978).

    수정이 'in the spirit' 인지(ad hoc₃ 판정) = 계획된 problemshift 궤도 위에 있는가.
    """
    hard_core: tuple = ()
    planned_problemshifts: tuple = ()   # 미리 예견한 모델 개선 궤도(순서)

    def in_spirit(self, move: str) -> bool:
        """move 가 양의 휴리스틱 궤도 위인가 — ad hoc₃(휴리스틱 위배) 의 반대."""
        return move in self.planned_problemshifts


@dataclass
class ProofGeneratedConcept:
    """증명-생성 개념 — 반례 통합 과정서 *탄생한* 개념(예: '단순연결 다면체').

    Lakatos: 진짜 진보의 표식. 개념이 미리 주어진 게 아니라 증명-반박 변증법서 나온다.
    """
    name: str
    born_from_counterexample: str       # 어느 반례가 낳았나
    incorporated_lemma: str             # 어느 숨은 보조정리를 조건화했나


@dataclass
class PnRAppraisal:
    verdict: str                # progressive | degenerating | withdrawn
    learned: bool               # 반례서 배웠는가
    ad_hoc: str                 # progressive | ad_hoc1/2/3 | n/a
    content_direction: str
    reasons: tuple = ()
    proof_generated_concept: ProofGeneratedConcept | None = None


def appraise_response(response: Response, *, excess_content: bool = False,
                      novel_corroborated: bool = False, in_heuristic_spirit: bool = True,
                      hard_core_preserved: bool = True,
                      proof_generated_concept: ProofGeneratedConcept | None = None) -> PnRAppraisal:
    """반례 대응 → 라카토스 평가(변증법의 핵심). 같은 hard core 라도 *대응 방식*이 판결을 가른다.

    규칙(Lakatos 1976/1978 충실):
      0. hard_core 위반 → degenerating (음의 휴리스틱: modus tollens 가 핵을 치면 다른 프로그램).
      1. surrender → withdrawn(추측 철회 — 진보/퇴행 아닌 후퇴).
      2. 안 배우는 대응(monster-barring/adjustment/exception-barring) → degenerating.
         (Lakatos: 반례를 진지하게 안 받으면 못 배운다. 예외차단은 content 감소까지.)
      3. 배우는 대응(lemma-incorporation/PnR) → ad_hoc_class 로 최종판정.
         배워도 ad hoc(무내용/미확증/휴리스틱밖)이면 진보 아님 — 통합 자체로 충분치 않다.
    """
    reasons = []
    if not hard_core_preserved:
        return PnRAppraisal('degenerating', LEARNS_FROM_COUNTEREXAMPLE.get(response, False),
                            'n/a', CONTENT_DIRECTION.get(response, '?'),
                            ('hard_core_violated: 음의 휴리스틱 위반 — 다른 프로그램',))
    if response == Response.SURRENDER:
        return PnRAppraisal('withdrawn', False, 'n/a', 'abandon',
                            ('conjecture_surrendered',))
    learned = LEARNS_FROM_COUNTEREXAMPLE[response]
    direction = CONTENT_DIRECTION[response]
    if not learned:
        if response == Response.EXCEPTION_BARRING:
            reasons.append('exception_barring: 도메인 축소 — content 감소, 반례서 안 배움')
        elif response == Response.MONSTER_BARRING:
            reasons.append('monster_barring: 개념 재정의로 배제 — 반례 진지하게 안 받음')
        else:
            reasons.append('monster_adjustment: 반례 재해석으로 회피 — 안 배움')
        return PnRAppraisal('degenerating', False, 'n/a', direction, tuple(reasons))
    # 배우는 대응 — ad hoc 검증 통과해야 진보
    klass = ad_hoc_class(excess_content, novel_corroborated, in_heuristic_spirit)
    if klass != 'progressive':
        reasons.append(f'{response.value} 했으나 {klass}: 통합만으론 부족(내용/확증/휴리스틱)')
        return PnRAppraisal('degenerating', True, klass, direction, tuple(reasons),
                            proof_generated_concept)
    reasons.append(f'{response.value}: 반례서 배워 보조정리 통합 + 초과내용·확증·휴리스틱 정합 → 진보')
    if proof_generated_concept:
        reasons.append(f'증명-생성 개념 탄생: {proof_generated_concept.name}')
    return PnRAppraisal('progressive', True, 'progressive', direction, tuple(reasons),
                        proof_generated_concept)
