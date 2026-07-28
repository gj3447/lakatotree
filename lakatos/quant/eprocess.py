"""e-process — anytime-valid 연속 증거층 (S9 흡수, 2026-07-28).

계보 문제(finding_b2a8aa7064fc11aa / finding_ee9f5cb90c5235f7):
  - should_abandon_bayes: verdict 라벨당 고정 BF 상수 누적 — 고정 상수의 곱은 일반적으로
    E[e|H0] <= 1 을 만족하지 않아 optional stopping 하 오류 보증이 없다(Jeffreys 밴드는
    해석 스케일이지 생성기가 아니다).
  - should_abandon_sprt: Wald(1945) 경계 참조 구현 — production 미배선(호출 0, grounding 자인).
  - BH: 독립/PRDS 가정 — 같은 metric/baseline 을 공유하는 가지들은 명백히 의존적.
엔진 실운용 체제(제출 시점 임의 선택·budget 재제출·연속 모니터링)를 위해 발명된 것이
e-values / safe anytime-valid inference (Ville 1939; Vovk & Wang 2021; Wang & Ramdas 2022;
Ramdas et al. 2023, Statistical Science) — 이 모듈은 그 3 프리미티브의 순수 stdlib 포팅이다.

  ① p→e calibrator      : e = κ·p^(κ-1), κ∈(0,1) — 임의 유효 p 에서 E[e|H0] <= 1.
  ② betting e-process   : 이진 결과 스트림 위 H0 "적중률 >= p0" 에 반대 베팅 —
                          e_t = 1 + λ(p0 - x_t), 0 < λ < 1/(1-p0). 누적곱 = test
                          supermartingale, Ville: P(sup_t E_t >= 1/α | H0) <= α
                          → *임의 시점 consult* 에도 거짓-abandon 확률 <= α.
  ③ e-BH                : 내림차순 e_[k] >= m/(q·k) 인 최대 k 를 reject —
                          임의 의존 구조 하 FDR <= q (BH 의 독립 가정 불필요).

정직 표기:
  ① null 선택(p0)은 여전히 정책이다 — 판단이 사라지는 게 아니라 감사가능한 상수 한 곳으로
     이동할 뿐(EPROCESS_POLICY, GROUNDED 와 동일 shape 공시).
  ② e-검정은 고정-n 검정보다 보수적 — 소형 트리(예측 수십 건)에선 대부분 undecided 가
     정직한 거동이다. 즉각적 판정 변화를 약속하지 않는다.
  ③ 기존 K=3 휴리스틱(should_abandon)을 대체하지 않는다 — challenger 병행 출력으로
     실트리 판정 일치율을 먼저 실측한다(즉시 삭제 금지, finding_ee9f5cb90c5235f7 권고).
# KG: plan-lktadv-p4-eprocess-s9-20260728 / seed-lktadv-eprocess-absorption-s9-20260728
"""
from __future__ import annotations

import math

from lakatos.grounding import GROUNDED

# 자유 파라미터 전부 GROUNDED 공시 경유 — 리터럴 금지 규율 (test_p7a_grounding_hygiene 형).
_KAPPA = GROUNDED['eprocess_kappa']['value']
_P0 = GROUNDED['eprocess_p0']['value']
_LAM_FRAC = GROUNDED['eprocess_lambda_fraction']['value']
_ALPHA = GROUNDED['eprocess_alpha']['value']


def p_to_e(p: float | None, kappa: float = _KAPPA) -> float | None:
    """κ-calibrator (Vovk-Wang 2021): 유효 p → 유효 e. p∈(0,1] 밖은 None(침묵 무한 e 금지)."""
    if not (0.0 < kappa < 1.0):
        raise ValueError(f"κ∈(0,1) 이어야: {kappa}")
    if p is None or not (0.0 < p <= 1.0) or not math.isfinite(p):
        return None
    return kappa * p ** (kappa - 1.0)


def default_lambda(p0: float) -> float:
    """안전 베팅 크기 — 최대 1/(1-p0)의 절반(EPROCESS_POLICY 공시). wealth 음수 불가."""
    return _LAM_FRAC / (1.0 - p0)


def betting_eprocess(outcomes: list, p0: float = _P0, lam: float | None = None) -> dict:
    """이진 결과 스트림 → test supermartingale 경로.

    H0: 적중률 >= p0. miss(0)마다 wealth ×(1+λp0), hit(1)마다 ×(1-λ(1-p0)).
    E[e_t|H0] = 1 + λ(p0 - E[x]) <= 1 (E[x]>=p0). 반환 {'wealth_path','e_final','e_max','n'}."""
    if not (0.0 < p0 < 1.0):
        raise ValueError(f"p0∈(0,1) 이어야: {p0}")
    lam = default_lambda(p0) if lam is None else lam
    if not (0.0 < lam < 1.0 / (1.0 - p0)):
        raise ValueError(f"λ∈(0, 1/(1-p0)) 이어야 (wealth 음수 방지): λ={lam}, p0={p0}")
    wealth, path = 1.0, []
    for x in outcomes:
        if x not in (0, 1, True, False):
            raise ValueError(f"이진 결과만: {x!r}")
        wealth *= 1.0 + lam * (p0 - (1 if x else 0))
        path.append(wealth)
    return {'wealth_path': path, 'e_final': path[-1] if path else 1.0,
            'e_max': max(path) if path else 1.0, 'n': len(path)}


def ville_threshold(alpha: float = _ALPHA) -> float:
    return 1.0 / alpha


def should_abandon_eprocess(outcomes: list, p0: float = _P0, alpha: float = _ALPHA,
                            lam: float | None = None) -> dict:
    """anytime-valid abandon 신호 — sup wealth 가 Ville 임계(1/α)를 넘으면 H0(건강) 기각 권고.

    K=3 휴리스틱과 달리 '임의 시점에 들여다봐도 거짓 신호 확률 <= α' 가 보증된다.
    advisory 신호이며 차단이 아니다(기존 abandon 계약 계승 — 인간/사용자 verdict 가 종심)."""
    r = betting_eprocess(outcomes, p0=p0, lam=lam)
    threshold = ville_threshold(alpha)
    fired_at = next((i + 1 for i, w in enumerate(r['wealth_path']) if w >= threshold), None)
    return {'abandon': fired_at is not None, 'fired_at': fired_at,
            'e_final': r['e_final'], 'e_max': r['e_max'], 'threshold': threshold,
            'n': r['n'], 'p0': p0, 'alpha': alpha}


def e_bh(evalues: list, q: float) -> list:
    """e-BH (Wang-Ramdas 2022): 내림차순 e_[k] >= m/(q·k) 인 최대 k 만 reject.

    임의 의존 하 FDR <= q — 같은 metric/baseline 을 공유하는 가지 family 에 안전.
    None(검정 불가)은 reject 불가 = False (침묵 통과 금지), m = 검정가능 수."""
    if q <= 0:
        raise ValueError(f"q > 0 이어야: {q}")
    indexed = sorted(((e, i) for i, e in enumerate(evalues) if e is not None), reverse=True)
    m = len(indexed)
    out = [False] * len(evalues)
    if m == 0:
        return out
    k_star = 0
    for k, (e, _) in enumerate(indexed, start=1):
        if e >= m / (q * k):
            k_star = k
    for e, i in indexed[:k_star]:
        out[i] = True
    return out
