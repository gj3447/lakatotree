"""판결 규칙 — 라카토스 원전의 기계화. LLM 점수 금지, 순수함수만.

진보(progressive) = 새로운 예측(novel_prediction)이 적중하는 것.
땜빵(partial)     = 개선됐으나 새 예측이 없는 것 (라카토스가 경계한 보호대 패치).
# KG: SA_LakatoTree_Server_20260612 / span_lakatotree_S2_judge_tdd
라이선스(THEORY §8): stevens1946 duhem1906 goodman1955 cronbach_meehl1955 hempel1945 mayo1996 hanson1958 pearl2009
"""
import math
from dataclasses import dataclass


class PredictionMissing(Exception):
    """사전등록 없는 채점 금지 (사후 합리화 차단)."""


class PredictionLocked(Exception):
    """채점 후 예측 변경 금지 (조작 차단)."""


# Stevens(1946) 측정척도 — 크기연산(빼기·크기 밴드·effect-size)의 적법성은 척도형에 달렸다.
#   ratio/interval : delta=measured−baseline + noise_band 크기 밴드 + effect-size 전부 적법
#   ordinal        : *순서*만 의미(rank/Likert) — 빼기 크기 무의미 → noise_band 금지(부호 비교만)
#   nominal        : 순서조차 없음 → '개선 방향' 정의 불가 → 채점 불가(구성 거부)
# '정밀·재현 ≠ 타당'(THEORY §8): 순서형에 interval 산술을 묵시 적용하던 구멍을 막는다. 라이선스: stevens1946.
SCALE_TYPES = ('ratio', 'interval', 'ordinal', 'nominal')
_MAGNITUDE_SCALES = ('ratio', 'interval')   # 빼기·크기 밴드·effect-size 적법
VERDICTS = ('progressive', 'partial', 'equivalent', 'rejected')
NOVEL_MARKER = 'novel'


@dataclass(frozen=True)
class Prediction:
    metric_name: str
    direction: str               # 'lower' | 'higher' = 개선 방향
    baseline_value: float
    noise_band: float = 0.0
    novel_prediction: str = ''   # 무엇이 "새로" 맞아야 하는가
    closes_question: str = ''
    scale_type: str = 'ratio'    # Stevens 측정척도 (기본 ratio = 하위호환·크기연산 적법)

    def __post_init__(self):
        if not isinstance(self.metric_name, str) or not self.metric_name.strip():
            raise ValueError('metric_name 은 비어 있지 않은 문자열')
        if self.novel_prediction is not None and not isinstance(self.novel_prediction, str):
            raise ValueError('novel_prediction 은 문자열')
        if self.scale_type not in SCALE_TYPES:
            raise ValueError(f"scale_type 은 {SCALE_TYPES} 중 (Stevens 측정척도)")
        # 명목형: 순서 부재 → 개선 방향 정의 불가 → 채점 불가(일찍 거부)
        if self.scale_type == 'nominal':
            raise ValueError('nominal metric 은 순서가 없어 진보 방향이 정의 불가 — judge 채점 불가 (Stevens)')
        # 순서형: 크기연산 불가 → 크기 밴드(noise_band) 부적법. 묵시적 interval 산술 차단.
        if self.scale_type == 'ordinal' and self.noise_band != 0:
            raise ValueError('ordinal metric 에 noise_band(크기 밴드) 부적법 — 순서형은 크기연산 불가, '
                             'noise_band=0 으로 순서 비교만 (Stevens)')
        # 조작 차단(나생문 F-FG-2): 음수 노이즈밴드 = worse-is-progressive 게임
        if self.noise_band < 0:
            raise ValueError('noise_band 음수 불가 (worse-is-progressive 조작 차단)')
        if not math.isfinite(self.baseline_value):
            raise ValueError('baseline_value 는 유한수')
        if self.direction not in ('lower', 'higher'):
            raise ValueError("direction 은 'lower'|'higher'")
        if not math.isfinite(self.noise_band):
            raise ValueError('noise_band 는 유한수')


NOVELTY_SENSES = ('zahar_use_novelty', 'temporal_novelty', 'worrall_use_novelty')
NOVELTY_SENSE_SCORING_POLICY = 'tag_only'


@dataclass(frozen=True)
class NovelTarget:
    """구조적 novel 예측 — 텍스트가 아니라 검증가능 명세 (gap1/F-FG-2 해소).

    novelty_sense (audit P2, tag-only — 점수 불변): 어느 'novel' 의미를 주장하는가.
      - zahar_use_novelty   : Zahar(1973) — 이론 구성에 쓰이지 않은 사실. 사전등록 잠금이 이걸 강제 = 운영 기본.
      - temporal_novelty    : Popper-Lakatos — 이론 *이후* 시간순으로 발견된 사실(달력 novelty).
      - worrall_use_novelty : Worrall — 그 사실에 *맞춰 튜닝되지 않은* 예측.
    세 의미는 같은 사실에 불일치할 수 있다(예: 수성 근일점). 엔진은 zahar 만 *채점*하고 나머지는
    감사용 태그로만 구분(DON'T force contested senses into scoring).
    """
    metric_name: str
    direction: str               # lower|higher
    threshold: float             # 이 값을 넘어서야 '적중'
    novelty_sense: str = 'zahar_use_novelty'   # NOVELTY_SENSES 중 (감사 태그, 채점 불변)

    def corroborated(self, measured: float) -> bool:
        if self.direction == 'lower':
            return measured <= self.threshold
        return measured >= self.threshold

    def __post_init__(self):
        if not isinstance(self.metric_name, str) or not self.metric_name.strip():
            raise ValueError('novel metric_name 은 비어 있지 않은 문자열')
        if self.direction not in ('lower', 'higher'):
            raise ValueError("novel_target.direction 은 'lower'|'higher'")
        if self.novelty_sense not in NOVELTY_SENSES:
            raise ValueError(f'novelty_sense 는 {NOVELTY_SENSES} 중 하나')
        if not math.isfinite(self.threshold):
            raise ValueError('novel_target.threshold 는 유한수')


@dataclass(frozen=True)
class Verdict:
    verdict: str                 # progressive | partial | equivalent | rejected
    delta: float
    improved: bool
    novel: bool
    reason: str


@dataclass(frozen=True)
class _NovelAssessment:
    novel: bool
    noindep: bool = False
    noindep_cross: bool = False
    witness_licensed: bool = False


def check_registration(already_judged: bool) -> None:
    if already_judged:
        raise PredictionLocked('이미 채점된 노드 — 사후 예측등록/변경 금지')


def _distinct_sha(a: str, b: str) -> bool:
    return bool(a and b and a != b)


def _resolve_novelity(pred: Prediction, novel_target: NovelTarget | None = None, novel_measured: float | None = None,
                     *, measured_sha: str = '', novel_sha: str = '',
                     require_independent_source: bool = False, independence_witness: str = '') -> _NovelAssessment:
    witness = independence_witness.strip()
    if novel_target is None:
        return _NovelAssessment(novel=False)
    novel = novel_target.corroborated(novel_measured)  # type: ignore[arg-type]
    noindep = noindep_cross = False
    witness_licensed = False
    same_metric = novel_target.metric_name == pred.metric_name

    if novel and same_metric and not _distinct_sha(measured_sha, novel_sha):
        noindep = True
        novel = False
    elif novel and require_independent_source and not same_metric and not _distinct_sha(measured_sha, novel_sha):
        if witness:
            witness_licensed = True
        else:
            noindep_cross = True
            novel = False
    return _NovelAssessment(
        novel=novel,
        noindep=noindep,
        noindep_cross=noindep_cross,
        witness_licensed=witness_licensed,
    )


def _classify_verdict(improved: bool, novel: bool, within_noise: bool) -> str:
    if improved and novel:
        return 'progressive'
    if improved:
        return 'partial'
    if within_noise:
        return 'equivalent'
    return 'rejected'


def _reason_suffix(novel_assessment: _NovelAssessment, novel_target: NovelTarget | None, witness: str) -> str:
    if novel_target is None:
        return ''
    parts = [f', novelty_sense={novel_target.novelty_sense}']
    if novel_assessment.noindep:
        parts.append(' [novel 비독립: 같은 metric·동일 출처(sha)/측정 재활용 → 초과내용 아님]')
    if novel_assessment.noindep_cross:
        parts.append(' [novel 비독립: cross-metric 출처 미증명(distinct sha·witness 부재) — '
                     'require_independent_source 하 초과내용 불인정]')
    if novel_assessment.witness_licensed:
        parts.append(f' [independence_witness: {witness}]')
    return ''.join(parts)


def judge(pred: Prediction | None, measured: float,
          novel_target: 'NovelTarget | None' = None,
          novel_measured: float | None = None,
          measured_sha: str = '', novel_sha: str = '', *,
          require_independent_source: bool = False,
          independence_witness: str = '') -> Verdict:
    # jp6 (JP 캠페인 2026-07-08, jp6a 정정 준수): opt-in 독립출처 게이트 — 기본 False 는 모든 기존
    #   호출부에서 바이트동일 거동(keyword-only 라 positional 유입 불가). armed 시 cross-metric novel 도
    #   distinct sha OR 선언 witness 를 요구해, FF1 이 의도적으로 남긴 순수-judge() 하네스 경로의
    #   relabel 공격(m→m_v2 개명·빈 sha·excess content 0)을 봉합한다. 서버층(judgement_policy
    #   novel-anchor demote)은 별개 신뢰 tier 로 불변. T3 정직 경계: 순수술어로 causal 독립 증명은
    #   불가 — witness 는 silent license 를 explicit·challengeable 선언으로 바꿀 뿐이다.
    witness = independence_witness.strip()
    if independence_witness and not require_independent_source:
        raise ValueError('independence_witness 는 require_independent_source=True 와만 — '
                         '아무 일도 안 하는 witness(죽은 장식) 금지')
    if independence_witness and novel_target is None:
        raise ValueError('independence_witness 는 novel 주장(novel_target)과만 — 장식 금지')
    if pred is None:
        raise PredictionMissing('사전등록된 예측 없음 — prediction 먼저 (사후 채점 금지)')
    if not math.isfinite(measured):
        raise ValueError('measured 비유한 — 무효 입력 (NaN-은-rejected 침묵 금지)')
    delta = measured - pred.baseline_value
    if pred.direction == 'lower':
        improved = delta < -pred.noise_band
    else:
        improved = delta > pred.noise_band
    within_noise = abs(delta) <= pred.noise_band
    # 구조적 corroboration: 명세가 있으면 실측 대조로 채점(텍스트 존재만으론 novel 불인정)
    if novel_target is not None:
        # audit P2: default-to-measured 붕괴 차단 — novel_measured 생략 시 옛날엔 measured 로 채점해
        # *개선 측정 1개*가 이론(improved)+경험(novel) 양쪽을 공짜로 만족(가짜 초과경험내용)했다.
        # 같은 metric 이면 독립 초과내용이 아니고, 다른 metric 이면 measured(타 metric 값)는 무의미.
        # → 어느 쪽이든 novel_measured 명시 요구(독립 측정).
        if novel_measured is None:
            same = novel_target.metric_name == pred.metric_name
            raise ValueError(
                'novel_target 가 있는데 novel_measured 생략 — 독립 초과경험내용 필요. '
                + ('같은 metric 의 개선 측정으로 novel 을 공짜 인정할 수 없음(가짜 초과내용).'
                   if same else
                   f'novel metric({novel_target.metric_name})≠개선 metric({pred.metric_name}) — 독립 측정 명시.'))
        if not math.isfinite(novel_measured):
            raise ValueError('novel_measured 비유한')

        assessment = _resolve_novelity(
            pred, novel_target, novel_measured,
            measured_sha=measured_sha, novel_sha=novel_sha,
            require_independent_source=require_independent_source,
            independence_witness=witness,
        )
        novel = assessment.novel
        noindep = assessment.noindep
        noindep_cross = assessment.noindep_cross
        witness_licensed = assessment.witness_licensed
    else:
        # 나생문 F-CON-3: 구조적 novel_target 없으면 텍스트 존재만으론 novel 불인정(→partial)
        novel = False
        noindep = False
        noindep_cross = False
        witness_licensed = False
    verdict = _classify_verdict(improved=improved, novel=novel, within_noise=within_noise)
    reason = (_reason_suffix(
        _NovelAssessment(novel=novel, noindep=noindep,
                         noindep_cross=noindep_cross, witness_licensed=witness_licensed),
        novel_target, witness))
    return Verdict(verdict=verdict, delta=delta, improved=improved, novel=novel,
                   reason=f'improved={improved}, novel={novel}, noise_band={pred.noise_band}{reason}')
