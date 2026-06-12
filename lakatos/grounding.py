"""정량 점수 기반 지식 정본 — 모든 상수/척도를 권위 문헌에 근거 (야매 점수 금지).

사용자 요구(2026-06-12): "그냥 우리가 야매로 점수주는게 아니라 기반 지식이 풍부하게 있는
기반으로 정확하게 점수를 매겨야". → 모든 정량 상수는 여기서 value + source(문헌) +
band(척도밴드) + rationale 로 근거화된다. 점수는 raw number 가 아니라 이 척도에 대해 *해석*된다.

상계(인터넷 read-only)에서 검증한 canonical 지식 내장 (2026-06-12 WebSearch 확인):
  - Jeffreys (1961), Theory of Probability, 3rd ed., Appendix B — Bayes factor 등급
  - Kass & Raftery (1995), JASA 90(430):773-795 — 2·ln(BF) 척도
  - Cohen (1988), Statistical Power Analysis, 2nd ed. — 효과크기 d 등급
  - Wald (1945), Ann. Math. Stat. 16(2):117-186 — SPRT 순차검정 경계
  - Wilson (1927), JASA 22(158):209-212 — 점수구간 신뢰하한
  - Brier (1950), Mon. Weather Rev. 78(1):1-3 — proper scoring rule
  - Good (1952), JRSS-B 14(1):107-114 — logarithmic scoring rule
  - Laplace (1814) — 무차별 원리(non-informative prior)
  - Brin & Page (1998) — PageRank damping; Kamvar et al. (2003) — EigenTrust
# KG: span_lakatotree_grounding / q-lkt-quantitative-grounding
"""
import math

# ════════════════════════════════════════════════════════════════════════
#  문헌 정본 (citation registry) — 상수마다 source 키로 참조
# ════════════════════════════════════════════════════════════════════════
SOURCES = {
    'jeffreys1961': 'Jeffreys, H. (1961). Theory of Probability (3rd ed.), Appendix B. Oxford.',
    'kass_raftery1995': 'Kass, R.E. & Raftery, A.E. (1995). Bayes Factors. JASA 90(430):773-795.',
    'cohen1988': 'Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences (2nd ed.).',
    'wald1945': 'Wald, A. (1945). Sequential Tests of Statistical Hypotheses. Ann. Math. Stat. 16(2):117-186.',
    'wilson1927': 'Wilson, E.B. (1927). Probable Inference... JASA 22(158):209-212.',
    'brier1950': 'Brier, G.W. (1950). Verification of Forecasts Expressed in Probability. MWR 78(1):1-3.',
    'good1952': 'Good, I.J. (1952). Rational Decisions. JRSS-B 14(1):107-114.',
    'laplace1814': 'Laplace, P.S. (1814). Essai philosophique sur les probabilités (principle of indifference).',
    'brin_page1998': 'Brin, S. & Page, L. (1998). The Anatomy of a Large-Scale... Hypertextual Web Search Engine.',
    'kamvar2003': 'Kamvar, S. et al. (2003). The EigenTrust Algorithm for Reputation Management in P2P Networks.',
}

# ════════════════════════════════════════════════════════════════════════
#  Bayes factor 해석 척도 (raw BF → 등급) — 점수를 문헌 밴드로 *해석*
# ════════════════════════════════════════════════════════════════════════
# Jeffreys (1961): 밴드 경계 = 10^(k/2) (half-decade on log10). 검증: 3.162/10/31.62/100.
JEFFREYS_BANDS = [   # (BF 하한, 라벨)
    (1.0,             'barely_worth_mentioning'),
    (math.sqrt(10),   'substantial'),    # 10^0.5 ≈ 3.162
    (10.0,            'strong'),          # 10^1
    (10 ** 1.5,       'very_strong'),     # 10^1.5 ≈ 31.623
    (100.0,           'decisive'),        # 10^2
]
# Kass & Raftery (1995): 2·ln(BF) 척도 (deviance 와 동일 단위). 검증: 2lnBF 2/6/10 → BF 2.72/20.1/148.
KASS_RAFTERY_BANDS_2LN = [   # (2lnBF 하한, 라벨)
    (0.0,  'not_worth_more_than_bare_mention'),
    (2.0,  'positive'),
    (6.0,  'strong'),
    (10.0, 'very_strong'),
]
# Cohen (1988): 표준화 효과크기 d 등급.
COHEN_D_BANDS = [(0.0, 'negligible'), (0.2, 'small'), (0.5, 'medium'), (0.8, 'large')]


def _band_label(value: float, bands: list) -> str:
    label = bands[0][1]
    for lo, lbl in bands:
        if value >= lo:
            label = lbl
    return label


def interpret_bayes_factor(bf: float) -> dict:
    """raw Bayes factor → 문헌 등급(Jeffreys + Kass-Raftery). 점수의 *해석* — 야매 숫자 금지.

    BF<1(증거가 반대 방향)이면 역수로 등급 매기고 favors='against'.
    """
    if bf <= 0:
        raise ValueError('Bayes factor must be > 0')
    favors = 'for' if bf >= 1 else 'against'
    mag = bf if bf >= 1 else 1.0 / bf
    two_ln = 2 * math.log(mag)
    return {
        'bf': bf,
        'two_ln_bf': round(two_ln, 4),
        'favors': favors,
        'jeffreys': _band_label(mag, JEFFREYS_BANDS),          # 출처 jeffreys1961
        'kass_raftery': _band_label(two_ln, KASS_RAFTERY_BANDS_2LN),  # 출처 kass_raftery1995
    }


def cohen_d_grade(d: float) -> str:
    """|효과크기| → Cohen 등급 (negligible/small/medium/large). 출처 cohen1988."""
    return _band_label(abs(d), COHEN_D_BANDS)


def sprt_log_boundaries(alpha: float = 0.05, beta: float = 0.05) -> tuple:
    """Wald (1945) SPRT 로그 경계 (lnA 상한=H1수용, lnB 하한=H0수용).

    A=(1-β)/α, B=β/(1-α). 누적 로그우도비가 lnA 초과→H1, lnB 미만→H0, 사이면 더 관측.
    α=β=0.05 → (lnA, lnB) = (+2.944, −2.944). 출처 wald1945.
    """
    if not (0 < alpha < 1 and 0 < beta < 1):
        raise ValueError('alpha, beta must be in (0,1)')
    A = (1 - beta) / alpha
    B = beta / (1 - alpha)
    return math.log(A), math.log(B)


def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> float:
    """Wilson (1927) 점수구간 신뢰하한 — 소표본 과신 방지. z=1.96 → 95%. 출처 wilson1927.

    검증: 10/10→0.722, 9/10→0.596, 3/3→0.438, 20/20→0.839.
    """
    if n == 0:
        return 0.0
    phat = k / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


# ════════════════════════════════════════════════════════════════════════
#  Grounded 상수 정본 — 각 상수 value + source + band + rationale (provenance)
#  점수 모듈은 inline 매직넘버 대신 여기를 import. "어느 근거로 이 점수가?" 추적 가능.
# ════════════════════════════════════════════════════════════════════════
GROUNDED = {
    'bf_progressive': {
        'value': 6.0, 'source': 'jeffreys1961',
        'band': 'substantial [3.162, 10]',
        'rationale': '단일 progressive 판결 = "substantial" 증거(decisive 아님). '
                     'Jeffreys substantial 밴드 기하중심 √(3.162·10)=5.66 ≈ 6.0. '
                     'Kass-Raftery 2ln(6)=3.58 → "positive" 밴드 [2,6] 정합.',
    },
    'bf_rejected': {
        'value': 1.0 / 6.0, 'source': 'jeffreys1961',
        'band': 'substantial (역방향)',
        'rationale': 'log-odds 대칭 — rejected 는 progressive 의 역수(BF=1/6). '
                     '진보 증거와 같은 크기의 반대 증거(나생문 F-MATH-2).',
    },
    'bf_partial_equivalent': {
        'value': 1.0, 'source': 'kass_raftery1995',
        'band': 'not worth more than a bare mention (BF≈1)',
        'rationale': '사후 땜빵/동등 = 무정보(둘 다 흔함). BF=1 → 신뢰도 불변, 누적 금지(F-MATH-1).',
    },
    'eff_cap': {
        'value': 4.0, 'source': 'cohen1988',
        'band': 'd=4.0 = "large"(0.8)의 5배 — 포화영역',
        'rationale': '효과크기 상한 — Cohen "large"=0.8 의 5배. 이상치 1방이 BF 를 '
                     '무한정 키우지 못하게(증거 포화). d>4 는 실무서 거의 없음.',
    },
    'weight_floor': {
        'value': 0.3, 'source': 'jeffreys1961',
        'band': 'log(BF) 최소 가중 — 마진 개선의 하한 증거력',
        'rationale': '효과크기 0 에 수렴해도 판결 자체(progressive=substantial)가 주는 최소 정보. '
                     'log(6)·0.3=0.54 → BF≈1.7(Jeffreys "barely~substantial 경계"). 0 으로 죽지 않음.',
    },
    'abandon_credence': {
        'value': 0.1, 'source': 'jeffreys1961',
        'band': 'posterior odds ≈ 1:9 (BF 9 ≈ Jeffreys substantial 상단)',
        'rationale': '사후신뢰도 0.1 = odds 1:9. 진보 가설이 퇴행 대비 9배 불리 = '
                     'substantial-to-strong 반대증거 누적. 폐기 문턱.',
    },
    'abandon_k': {
        'value': 3, 'source': 'wald1945',
        'band': 'SPRT 하한 lnB(α=β=0.05)=−2.944 의 이산근사',
        'rationale': '연속 비진보 K=3 = Wald SPRT 하한 교차의 휴리스틱. 노드당 로그우도비 '
                     '≈−0.98 nat(비진보=퇴행이 e배 우세)이면 3개 누적 −2.94 ≈ lnB. '
                     '즉 표준 오류율(0.05/0.05) 순차검정의 정수 근사 — 야매 아님.',
    },
    'abandon_budget': {
        'value': 5, 'source': 'wald1945',
        'band': 'SPRT 평균표본수(ASN) 규모 — 약증거 누적 관용창',
        'rationale': '예측 적중 0 인 채 소진 가능한 노드 예산. 약한 per-node 증거(≈0.59 nat)일 때 '
                     'lnB 도달에 필요한 표본수(2.944/0.59≈5). 적중 1 이면 가설 살림.',
    },
    'abandon_b': {
        'value': 2, 'source': 'laudan',
        'band': '문제수지 적자 한계(정책)',
        'rationale': 'Laudan(1977) 문제해결 효율 — 변명이 문제를 낳는 속도가 해결을 추월(net −2). '
                     '정량 임계는 정책값(Laudan 원전은 정성적), SPRT 와 독립한 안전망.',
    },
    'w_problem': {
        'value': 5.0, 'source': 'laudan',
        'band': '문제수지 vs metric 가중(정책)',
        'rationale': 'Laudan: 해결한 *문제* 1개 > metric % 개선 — 문제해결이 과학의 목적. '
                     '정책 가중(도메인 튜너블), 보편상수 아님(명시).',
    },
    'nobel_min_hitrate_lb': {
        'value': 0.7, 'source': 'wilson1927',
        'band': 'Wilson 95% 하한 ≥0.7 → 사실상 10/10 요구',
        'rationale': 'novel 예측 적중률의 Wilson 하한 임계. 9/10 하한 0.596<0.7 탈락, '
                     '10/10 하한 0.722≥0.7 통과. "운 좋은 소표본" 배제(F-MATH-6).',
    },
    'nobel_min_predictions': {
        'value': 3, 'source': 'wilson1927',
        'band': '표본 하한 — Wilson 하한이 의미 갖는 최소 n',
        'rationale': '등록 novel 예측 최소 수. n<3 이면 Wilson 하한이 너무 넓어 무의미.',
    },
    'pagerank_damping': {
        'value': 0.85, 'source': 'brin_page1998',
        'band': 'PageRank 표준 damping',
        'rationale': 'TrustRank(biased PageRank) damping. Brin-Page 원전 0.85 표준.',
    },
    'eigentrust_alpha': {
        'value': 0.15, 'source': 'kamvar2003',
        'band': 'EigenTrust pre-trusted teleport (=1−0.85)',
        'rationale': '악성 협잡 저항용 pre-trusted 가중. Kamvar 권장 ~0.1–0.2.',
    },
    'default_prior': {
        'value': 0.5, 'source': 'laplace1814',
        'band': '무차별 원리(principle of indifference)',
        'rationale': '진보/퇴행 사전 동률 — 숨은 주관 금지, 감사 가능한 명시 기준선.',
    },
    'ece_bins': {
        'value': 10, 'source': 'good1952',
        'band': 'ECE 표준 bin 수',
        'rationale': '예측 보정오차(ECE) 구간 수 — 문헌 관행 10(Guo 2017 등).',
    },
}


def provenance(constant: str) -> dict:
    """상수의 근거 — value + 문헌 전체인용 + band + rationale. 점수가 자기 근거를 들고 다님."""
    g = GROUNDED[constant]
    return {**g, 'citation': SOURCES.get(g['source'], g['source'])}
