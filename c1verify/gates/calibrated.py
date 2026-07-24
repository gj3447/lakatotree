"""calibrated gate reverifier (심화 D3) — issuer 보정을 봉인된 (예측,결과) 쌍에서 재유도.

엔진의 calibration 게이트(certify G4)는 issuer 의 예측 신뢰도가 실제 결과와 얼마나 맞는지(ECE/Brier)로
정한다. 그 증거는 포인터였다. 이 게이트는 번들이 나르는 sealed forecast pairs 에서 ECE/Brier 를
*재계산*(엔진 calibrate.py 와 동형, import 0)해 보정 밴드 안인지 재유도한다.

정책 상수(정직 표기 — 엔진의 grounding tier 관례와 동일 장르): ECE ≤ 0.10(well-calibrated 밴드) ∧
n ≥ 10(소표본 고분산 회피) ∧ Brier ≤ 0.25(constant-0.5 추측보다 나음). 이 셋은 *정책*이지 진리가
아니다(literature 가 아니라 policy tier). 번들이 더 엄한 threshold 를 선언하면 그걸 쓰되, 하드 상한
(ECE 0.10)을 넘는 자기선언은 거부한다(producer 가 threshold=1.0 으로 통과하는 것 봉쇄).

열거된 잔여: (예측,결과) 쌍의 AUTHENTICITY 는 out-of-band — 봉인은 쌍이 바뀌지 않았음을 증명하지,
그 결과 o 가 실제 세계 관측인지는 재유도로 알 수 없다.
"""
from __future__ import annotations

from .._decision import ACCEPT, REJECT, gate_decision

GATE = "calibrated"
_ECE_CEILING = 0.10      # policy: well-calibrated 밴드 상한(하드 — producer 자기선언이 못 넘음)
_MIN_N = 10              # policy: 소표본 고분산 회피
_BRIER_CEILING = 0.25   # policy: constant-0.5 추측(Brier 0.25)보다 나아야

_RESIDUAL = ("(forecast,outcome) pair AUTHENTICITY is out-of-band: the seal proves the pairs are "
             "unchanged, NOT that each outcome o is a real-world observation; and the ECE<=0.10 / "
             "Brier<=0.25 bounds are POLICY values (calibration band), not truths.")


def _brier(pairs) -> float:
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def _ece(pairs, bins: int = 10) -> float:
    buckets = [[] for _ in range(bins)]
    for p, o in pairs:
        idx = max(0, min(int(p * bins), bins - 1))
        buckets[idx].append((p, o))
    n = len(pairs)
    ece = 0.0
    for b in buckets:
        if not b:
            continue
        mp = sum(p for p, _ in b) / len(b)
        mo = sum(o for _, o in b) / len(b)
        ece += (len(b) / n) * abs(mp - mo)
    return ece


def verify_calibrated(payload, ctx) -> dict:
    """payload = {forecasts:[[p,o],...], ece_threshold?:float}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return gate_decision(GATE, REJECT, "calibrated payload absent or not an object")
    raw = payload.get("forecasts")
    if not isinstance(raw, list) or len(raw) < _MIN_N:
        return gate_decision(GATE, REJECT, f"forecasts 부족(n < {_MIN_N} = 소표본 보류)")
    try:
        pairs = []
        for p, o in raw:
            p = float(p); o = float(o)
            if not (0.0 <= p <= 1.0) or o not in (0.0, 1.0):
                return gate_decision(GATE, REJECT, "forecast 는 (p∈[0,1], o∈{0,1}) 이어야")
            pairs.append((p, o))
    except (TypeError, ValueError):
        return gate_decision(GATE, REJECT, "forecasts 형식 오류(각 원소 [p,o])")

    # producer 가 더 엄한 threshold 를 선언하면 채택하되 하드 상한 초과 자기선언은 거부.
    thr = payload.get("ece_threshold")
    if thr is not None:
        try:
            thr = float(thr)
        except (TypeError, ValueError):
            return gate_decision(GATE, REJECT, "ece_threshold 비수치")
        if thr > _ECE_CEILING:
            return gate_decision(GATE, REJECT,
                                 f"선언 ece_threshold {thr} > 하드 상한 {_ECE_CEILING}(자기완화 봉쇄)")
    bound = min(thr, _ECE_CEILING) if thr is not None else _ECE_CEILING

    ece = _ece(pairs)
    brier = _brier(pairs)
    if ece > bound:
        return gate_decision(GATE, REJECT, f"ECE {ece:.4f} > {bound}(미보정)")
    if brier > _BRIER_CEILING:
        return gate_decision(GATE, REJECT, f"Brier {brier:.4f} > {_BRIER_CEILING}(coin-flip 추측 이하)")
    return gate_decision(GATE, ACCEPT,
                         f"보정 재계산 통과(ECE {ece:.4f} ≤ {bound}, Brier {brier:.4f}, n={len(pairs)})",
                         residual_trust_surface=_RESIDUAL)
