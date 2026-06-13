"""베이즈 신뢰도 층 — 라카토스/라우든 위의 '수학적 심장'.

판결(judge)은 이산(progressive/rejected), 라우든(laudan)은 문제수지.
베이즈는 그 사이 **연속층**: 각 판결을 증거로 보고 가지의 사후 신뢰도를 갱신.
→ 강한 가지(자산 많음=과거 진보 누적)는 반례 하나로 안 죽는다 (사용자 직관의 수학화).

증거력 = P(E|진보 프로그램) / P(E|퇴행 프로그램) = Bayes factor.
  progressive (사전등록 novel 적중): 퇴행 프로그램에선 잘 안 나옴 → BF 큼
  partial (개선이나 사후 땜빵):       둘 다에서 흔함 → BF ≈ 1+
  rejected (악화):                    음의 증거 → BF < 1
효과크기(|delta|/noise)로 BF 를 1에서 더 멀리/가깝게 (마진 개선 < 대폭 개선).

엄격도 스택: 포퍼(judge 이산) > 베이즈(본 모듈, 연속) > 라우든(laudan, 문제수지).
한계 정직(사용자 정리 #10): ①사전확률 주관 → prior 명시 인자(감사 가능) ②새 가설 탄생은
  베이즈 범위 밖 → frontier/directions(가설공간 확장)가 담당, 베이즈는 within-tree 신뢰도만.
# KG: span_lakatotree_bayes
"""
import math
from .trust import evidence_weight
from .grounding import GROUNDED, interpret_bayes_factor

# 판결별 기본 Bayes factor — 값은 grounding 정본서 (Jeffreys 1961 / Kass-Raftery 1995 근거).
#  progressive=6.0(Jeffreys substantial 밴드), rejected=1/6(log-odds 대칭, F-MATH-2),
#  partial/equivalent=1.0(무정보, 누적금지 F-MATH-1). 야매 아님 — grounding.provenance 참조.
BF_BASE = {'progressive': GROUNDED['bf_progressive']['value'],
           'partial': GROUNDED['bf_partial_equivalent']['value'],
           'equivalent': GROUNDED['bf_partial_equivalent']['value'],
           'rejected': GROUNDED['bf_rejected']['value'],
           # THR-1: dialectical 판결도 명시 — 전엔 .get default 1.0(neutral) 로 degenerating 이
           # 음의 증거인데 신뢰도에 무영향이었다. degenerating=rejected 급 음의 증거,
           # withdrawn(철회)·progressive_conditional(미확증)=무정보(1.0, 누적금지).
           'degenerating': GROUNDED['bf_rejected']['value'],
           'withdrawn': GROUNDED['bf_partial_equivalent']['value'],
           'progressive_conditional': GROUNDED['bf_partial_equivalent']['value']}
DEFAULT_PRIOR = GROUNDED['default_prior']['value']        # 무차별 원리 (Laplace 1814)
ABANDON_CREDENCE = GROUNDED['abandon_credence']['value']  # odds 1:9 폐기 문턱
EFF_CAP = GROUNDED['eff_cap']['value']                    # 효과크기 상한 (Cohen d=4=large×5)
WEIGHT_FLOOR = GROUNDED['weight_floor']['value']          # 마진 개선 최소 증거력


def interpret(bf: float) -> dict:
    """Bayes factor → 문헌 등급(Jeffreys + Kass-Raftery). 점수의 해석(raw 숫자 금지)."""
    return interpret_bayes_factor(bf)


def effect_size(delta: float, noise_band: float, floor: float = 1e-6) -> float:
    """증거 강도 = |delta| / max(noise_band, floor). 큰 개선 = 강한 증거."""
    return abs(delta) / max(noise_band, floor)


def bayes_factor(verdict: str, delta: float = 0.0, noise_band: float = 0.0,
                 source_trust: float = 1.0) -> float:
    """판결 + 효과크기 + 인터넷 출처신뢰 → Bayes factor. 권위 출처 = 강한 증거(P1).
    equivalent=1(무정보). source_trust 가 log(BF) 를 evidence_weight 로 감쇠 — 저신뢰도 증거는 약하게."""
    base = BF_BASE.get(verdict, 1.0)
    if base == 1.0:
        return 1.0
    es = min(effect_size(delta, noise_band), EFF_CAP) / EFF_CAP   # 0..1
    w = max(es, WEIGHT_FLOOR) * evidence_weight(source_trust)   # ★출처신뢰 결합
    return math.exp(math.log(base) * w)   # base>1 → BF>1, base<1 → BF<1


def branch_credence(verdicts: list, prior: float = DEFAULT_PRIOR) -> float:
    """판결 시퀀스(시간순) → 사후 신뢰도. odds 곱셈(베이즈 갱신)."""
    odds = prior / (1 - prior)
    for v in verdicts:
        odds *= bayes_factor(v['verdict'], v.get('delta', 0.0), v.get('noise_band', 0.0),
                             v.get('source_trust', 1.0))
    return odds / (1 + odds)


def should_abandon_bayes(verdicts: list, prior: float = DEFAULT_PRIOR,
                         threshold: float = ABANDON_CREDENCE):
    """신뢰도 기반 폐기 — 강한 가지는 반례 하나로 안 죽고, 약한 가지는 누적되면 죽는다.

    laudan.should_abandon(이산 3규칙)의 연속·증거가중 버전. 둘 다 쓰면:
    laudan = 해석 가능한 휴리스틱, bayes = 자산 가중 연속 신뢰도.
    """
    c = branch_credence(verdicts, prior)
    return c < threshold, c
