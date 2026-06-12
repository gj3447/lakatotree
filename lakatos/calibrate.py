"""신뢰도 보정 — proper scoring rule 로 예측 calibration 정량(prior 주관성 gap 해소).

각 사전등록 예측은 신뢰도(credence)와 결과(novel 적중 0/1)를 가짐. proper scoring 은
'참 확률을 말할 때 점수 최소'라 정직 보고를 강제. Brier(균등) / log(overconfidence 강벌) /
ECE(보정오차). 베이즈 BF_BASE 의 주관성을 경험적으로 보정하는 근거.
출처: Brier 1950, Good 1952(log score), strictly proper scoring rules.
# KG: span_lakatotree_calibrate
"""
import math


def brier_score(forecasts: list) -> float:
    """평균 (p−o)^2. 0=완벽, 1=최악. strictly proper, calibration+resolution+uncertainty 분해."""
    if not forecasts:
        return 0.0
    return sum((p - o) ** 2 for p, o in forecasts) / len(forecasts)


def log_score(forecasts: list, eps: float = 1e-9) -> float:
    """평균 −log(관측결과 확률). overconfidence 를 underconfidence 보다 강벌."""
    if not forecasts:
        return 0.0
    s = 0.0
    for p, o in forecasts:
        q = p if o else (1 - p)
        s += -math.log(max(q, eps))
    return s / len(forecasts)


def calibration_error(forecasts: list, bins: int = 10) -> float:
    """ECE = Σ (|bin| / N) × |평균예측 − 평균결과|. 0 에 가까울수록 보정 잘 됨."""
    if not forecasts:
        return 0.0
    buckets = [[] for _ in range(bins)]
    for p, o in forecasts:
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, o))
    n = len(forecasts)
    ece = 0.0
    for b in buckets:
        if not b:
            continue
        mp = sum(p for p, _ in b) / len(b)
        mo = sum(o for _, o in b) / len(b)
        ece += (len(b) / n) * abs(mp - mo)
    return ece
