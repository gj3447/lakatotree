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

# 판결별 기본 Bayes factor (사전등록 여부가 강도를 가른다 — novel 적중은 위조 어려움)
BF_BASE = {'progressive': 6.0, 'partial': 1.5, 'equivalent': 1.0, 'rejected': 0.3}
DEFAULT_PRIOR = 0.5         # base rate (감사 가능한 명시값 — 숨은 주관 금지)
ABANDON_CREDENCE = 0.1      # 이 밑 = 폐기 (laudan 연속카운터의 연속판)
EFF_CAP = 4.0              # 효과크기 상한 (이상치 1방 폭주 차단)
WEIGHT_FLOOR = 0.3         # 마진이어도 판결 자체가 주는 최소 정보


def effect_size(delta: float, noise_band: float, floor: float = 1e-6) -> float:
    """증거 강도 = |delta| / max(noise_band, floor). 큰 개선 = 강한 증거."""
    return abs(delta) / max(noise_band, floor)


def bayes_factor(verdict: str, delta: float = 0.0, noise_band: float = 0.0) -> float:
    """판결 + 효과크기 → Bayes factor. equivalent=1(무정보), 나머지는 효과로 증폭."""
    base = BF_BASE.get(verdict, 1.0)
    if base == 1.0:
        return 1.0
    es = min(effect_size(delta, noise_band), EFF_CAP) / EFF_CAP   # 0..1
    w = max(es, WEIGHT_FLOOR)
    return math.exp(math.log(base) * w)   # base>1 → BF>1, base<1 → BF<1


def branch_credence(verdicts: list, prior: float = DEFAULT_PRIOR) -> float:
    """판결 시퀀스(시간순) → 사후 신뢰도. odds 곱셈(베이즈 갱신)."""
    odds = prior / (1 - prior)
    for v in verdicts:
        odds *= bayes_factor(v['verdict'], v.get('delta', 0.0), v.get('noise_band', 0.0))
    return odds / (1 + odds)


def should_abandon_bayes(verdicts: list, prior: float = DEFAULT_PRIOR,
                         threshold: float = ABANDON_CREDENCE):
    """신뢰도 기반 폐기 — 강한 가지는 반례 하나로 안 죽고, 약한 가지는 누적되면 죽는다.

    laudan.should_abandon(이산 3규칙)의 연속·증거가중 버전. 둘 다 쓰면:
    laudan = 해석 가능한 휴리스틱, bayes = 자산 가중 연속 신뢰도.
    """
    c = branch_credence(verdicts, prior)
    return c < threshold, c
