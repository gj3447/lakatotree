"""정량 점수 기반 지식 정본 — 모든 상수/척도를 권위 문헌에 근거 (야매 점수 금지).

사용자 요구(2026-06-12): "그냥 우리가 야매로 점수주는게 아니라 기반 지식이 풍부하게 있는
기반으로 정확하게 점수를 매겨야". → 모든 정량 상수는 value + source + band + rationale + **tier** 로
근거화된다. 점수는 raw number 가 아니라 문헌 척도에 대해 *해석*된다.

★정직성(나생문 grounding-fidelity 적대검증 후): "척도/방법은 문헌 근거, 특정 값은 정책 선택"을
혼동하지 않는다. tier 로 명시 구분 — 가짜 정밀(역산값을 derivation 인 척) 금지:
  - 'literature'       : 값이 인용 문헌서 직접 (예 damping=0.85 Brin-Page, Cohen 밴드, z=1.96)
  - 'policy_in_scale'  : 값은 엔지니어링 선택이나 *문헌 척도* 위에서 해석/경계됨 (예 BF=6.0 ∈ Jeffreys substantial)
  - 'policy'           : 순수 엔지니어링/도메인 튜너블 (문헌은 영감일 뿐, 값은 literature 도출 아님)

상계(인터넷 read-only)에서 검증한 canonical 지식 내장 (2026-06-12 WebSearch + 계산 확인):
  - Jeffreys (1961), Theory of Probability, 3rd ed., Appendix B — Bayes factor 등급 (밴드=10^(k/2))
  - Kass & Raftery (1995), JASA 90(430):773-795 — 2·ln(BF) 척도 (최상등급 very_strong, decisive 없음)
  - Cohen (1988), Statistical Power Analysis, 2nd ed. — 효과크기 d 등급
  - Wald (1945), Ann. Math. Stat. 16(2):117-186 — SPRT 순차검정 경계 (α+β<1 필요)
  - Wilson (1927), JASA 22(158):209-212 — 점수구간 신뢰하한
  - Brier (1950) / Good (1952) — proper scoring rule (calibrate.py 함수 근거; 상수 아님)
  - Guo et al. (2017) — ECE 10-bin 관행
  - Laplace (1814) — 무차별 원리; Brin & Page (1998) / Kamvar (2003) — PageRank/EigenTrust
# KG: span_lakatotree_grounding / q-lkt-quantitative-grounding
"""
import math

# ════════════════════════════════════════════════════════════════════════
#  문헌 정본 (citation registry) — 상수의 source 키가 모두 여기 등록되어야(고아 인용 금지)
# ════════════════════════════════════════════════════════════════════════
SOURCES = {
    'jeffreys1961': 'Jeffreys, H. (1961). Theory of Probability (3rd ed.), Appendix B. Oxford.',
    'kass_raftery1995': 'Kass, R.E. & Raftery, A.E. (1995). Bayes Factors. JASA 90(430):773-795.',
    'cohen1988': 'Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences (2nd ed.).',
    'wald1945': 'Wald, A. (1945). Sequential Tests of Statistical Hypotheses. Ann. Math. Stat. 16(2):117-186.',
    'wilson1927': 'Wilson, E.B. (1927). Probable Inference... JASA 22(158):209-212.',
    'brier1950': 'Brier, G.W. (1950). Verification of Forecasts Expressed in Probability. MWR 78(1):1-3.',
    'good1952': 'Good, I.J. (1952). Rational Decisions. JRSS-B 14(1):107-114.',
    'guo2017': 'Guo, C. et al. (2017). On Calibration of Modern Neural Networks. ICML (ECE; 원전 M=15 bins — Table 1).',
    'laplace1814': 'Laplace, P.S. (1814). Essai philosophique sur les probabilités (principle of indifference).',
    'laudan1977': 'Laudan, L. (1977). Progress and Its Problems. UC Press (문제해결 효율 — *정성적* 모델).',
    'lakatos1976': 'Lakatos, I. (1976). Proofs and Refutations: The Logic of Mathematical Discovery. Cambridge UP.',
    'lakatos1978': 'Lakatos, I. (1978). The Methodology of Scientific Research Programmes (Phil. Papers v1). Cambridge UP.',
    'zahar1973': 'Zahar, E. (1973). Why did Einstein\'s Programme Supersede Lorentz\'s? BJPS 24 (ad hoc₃ / novelty).',
    'lakatos_zahar1976': 'Lakatos, I. & Zahar, E. (1976). Why did Copernicus\'s Programme Supersede Ptolemy\'s?',
    'popper1959': 'Popper, K. (1959). The Logic of Scientific Discovery (falsifiability, ad hoc).',
    'brin_page1998': 'Brin, S. & Page, L. (1998). The Anatomy of a Large-Scale... Hypertextual Web Search Engine.',
    'kamvar2003': 'Kamvar, S. et al. (2003). The EigenTrust Algorithm for Reputation Management in P2P Networks.',
    'condorcet1785': 'Condorcet, M. (1785). Essai sur l\'application de l\'analyse... (jury theorem — 독립 다수결 > 단일 판정자).',
    'borda1781': 'Borda, J-C. (1781). Mémoire sur les élections au scrutin (Borda count — 순위 합산 집계).',
    'kuhn1962': 'Kuhn, T. (1962). The Structure of Scientific Revolutions. U Chicago Press (*정성적* — 위기/혁명 모델).',
    'agm1985': 'Alchourrón, C., Gärdenfors, P. & Makinson, D. (1985). On the Logic of Theory Change: Partial Meet Contraction and Revision Functions. JSL 50(2):510-530.',
    'hansson1993': 'Hansson, S.O. (1993). Reversing the Levi Identity. J. Phil. Logic 22:637-669 (belief *base* revision).',
    'feyerabend1975': 'Feyerabend, P. (1975). Against Method (방법론 다원주의 — 층 불일치는 보고하라, 숨기지 마라).',
    'benjamini_hochberg1995': 'Benjamini, Y. & Hochberg, Y. (1995). Controlling the False Discovery Rate. JRSS-B 57(1):289-300.',
    'dunn1961': 'Dunn, O.J. (1961). Multiple Comparisons Among Means. JASA 56(293):52-64 (Bonferroni 보정의 정식화).',
    'fisher1925': 'Fisher, R.A. (1925). Statistical Methods for Research Workers (α=0.05 관행의 기원).',
    'policy': '엔지니어링/도메인 정책값 — 문헌 도출 아님 (튜너블). 영감 문헌은 rationale 에 별도 표기.',
}

# ════════════════════════════════════════════════════════════════════════
#  해석 척도 (raw 점수 → 등급) — 점수를 문헌 밴드로 *해석*
# ════════════════════════════════════════════════════════════════════════
# Jeffreys (1961): 밴드 경계 = 10^(k/2) (half-decade on log10). 검증: 3.162/10/31.62/100.
JEFFREYS_BANDS = [   # (BF 하한, 라벨) — 오름차순
    (1.0,             'barely_worth_mentioning'),
    (math.sqrt(10),   'substantial'),    # 10^0.5 ≈ 3.162
    (10.0,            'strong'),          # 10^1
    (10 ** 1.5,       'very_strong'),     # 10^1.5 ≈ 31.623
    (100.0,           'decisive'),        # 10^2
]
# Kass & Raftery (1995): 2·ln(BF) 척도. ★원전 최상 등급 = very_strong(2lnBF>10); 'decisive' 없음
#  (그건 Jeffreys 스케일). 따라서 BF>e^5≈148.4 saturate 는 원전 충실 — 버그 아님(나생문 F-MATH-4 응답).
KASS_RAFTERY_BANDS_2LN = [   # (2lnBF 하한, 라벨) — 오름차순
    (0.0,  'not_worth_more_than_bare_mention'),
    (2.0,  'positive'),
    (6.0,  'strong'),
    (10.0, 'very_strong'),
]
# Cohen (1988): 표준화 효과크기 d 등급.
COHEN_D_BANDS = [(0.0, 'negligible'), (0.2, 'small'), (0.5, 'medium'), (0.8, 'large')]


def _band_label(value: float, bands: list) -> str:
    """value 가 속한 최상위 밴드 라벨. 입력 순서 무관(내부 오름차순 정렬 — 나생문 F-MATH-2)."""
    label = None
    for lo, lbl in sorted(bands, key=lambda x: x[0]):
        if value >= lo:
            label = lbl
    if label is None:   # value < 첫 하한 → 최저 밴드
        label = min(bands, key=lambda x: x[0])[1]
    return label


def interpret_bayes_factor(bf: float) -> dict:
    """raw Bayes factor → 문헌 등급(Jeffreys + Kass-Raftery). 점수의 *해석* — 야매 숫자 금지.

    BF<1(증거가 반대 방향)이면 역수 크기로 등급 매기고 favors='against'.
    반환 two_ln_bf = 증거 *크기*(항상 ≥0); 방향은 favors 가 준다(나생문 F-MATH-5 명시).
    """
    if bf <= 0:
        raise ValueError('Bayes factor must be > 0')
    favors = 'for' if bf >= 1 else 'against'
    mag = bf if bf >= 1 else 1.0 / bf
    two_ln = 2 * math.log(mag)
    return {
        'bf': bf,
        'two_ln_bf': round(two_ln, 4),     # 크기(magnitude, ≥0). 방향은 favors.
        'favors': favors,
        'jeffreys': _band_label(mag, JEFFREYS_BANDS),          # 출처 jeffreys1961
        'kass_raftery': _band_label(two_ln, KASS_RAFTERY_BANDS_2LN),  # 출처 kass_raftery1995
    }


def cohen_d_grade(d: float) -> str:
    """|효과크기| → Cohen 등급 (negligible/small/medium/large). 출처 cohen1988."""
    return _band_label(abs(d), COHEN_D_BANDS)


def sprt_log_boundaries(alpha: float = 0.05, beta: float = 0.05) -> tuple:
    """Wald (1945) SPRT 로그 경계 (lnA 상한=H1수용, lnB 하한=H0수용).

    A=(1-β)/α, B=β/(1-α). 누적 로그우도비 ≥lnA→H1, ≤lnB→H0, 사이면 더 관측.
    ★α+β<1 필수 — 아니면 lnA≤lnB(경계 역전, 의미 붕괴). 나생문 F-MATH-3.
    α=β=0.05 → (lnA, lnB) = (+2.944, −2.944). 출처 wald1945.
    """
    if not (0 < alpha < 1 and 0 < beta < 1):
        raise ValueError('alpha, beta must be in (0,1)')
    if alpha + beta >= 1:
        raise ValueError('alpha + beta must be < 1 (else SPRT boundaries invert: lnA ≤ lnB)')
    A = (1 - beta) / alpha
    B = beta / (1 - alpha)
    return math.log(A), math.log(B)


def wilson_lower_bound(k: int, n: int, z: float = 1.96) -> float:
    """Wilson (1927) 점수구간 신뢰하한 — 소표본 과신 방지. z=1.96 → 95%. 출처 wilson1927.

    검증: 10/10→0.722, 9/10→0.596, 9/9→0.701, 8/8→0.676, 3/3→0.438, 20/20→0.839.
    """
    if n == 0:
        return 0.0
    phat = k / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


# ════════════════════════════════════════════════════════════════════════
#  Grounded 상수 정본 — value + source + tier + band + rationale (provenance)
#  tier 가 정직성의 핵심: literature(문헌값) vs policy_in_scale(척도내 정책) vs policy(순수 정책).
# ════════════════════════════════════════════════════════════════════════
GROUNDED = {
    'bf_progressive': {
        'value': 6.0, 'source': 'jeffreys1961', 'tier': 'policy_in_scale',
        'band': 'Jeffreys substantial [3.162, 10]',
        'rationale': 'single progressive = "substantial" 증거(decisive 아님). 6.0 은 substantial 밴드 '
                     '*내부의 정책값*(반올림 라운드, 기하평균 √32≈5.66 근방) — 밴드는 문헌, 6.0 자체는 '
                     '엔지니어링 선택(derivation 아님). KR 2ln(6)=3.58 → "positive".',
    },
    'bf_rejected': {
        'value': 1.0 / 6.0, 'source': 'jeffreys1961', 'tier': 'policy_in_scale',
        'band': 'substantial (역방향)',
        'rationale': 'log-odds 대칭으로 progressive 의 역수(BF=1/6) — 같은 크기 반대 증거(F-MATH-2). '
                     'bf_progressive 정책값에 종속(대칭은 수학적 필연).',
    },
    'bf_partial_equivalent': {
        'value': 1.0, 'source': 'kass_raftery1995', 'tier': 'literature',
        'band': 'not worth more than a bare mention (BF=1)',
        'rationale': 'BF=1 = 무정보(둘 다 흔함) = KR 최저 등급. 신뢰도 불변, 누적 금지(F-MATH-1). '
                     '값 1.0 은 "증거 없음"의 수학적 정의 — 정책 아님.',
    },
    'eff_cap': {
        'value': 4.0, 'source': 'cohen1988', 'tier': 'policy_in_scale',
        'band': 'Cohen d 스케일 — large(0.8)의 5배 = 포화',
        'rationale': '효과크기 상한(이상치 1방 차단). Cohen large=0.8 대비 5×=4.0 정책 cap — '
                     'd>4 는 실무서 거의 없음. 스케일은 Cohen, 4.0 cap 은 엔지니어링 선택.',
    },
    'weight_floor': {
        'value': 0.3, 'source': 'policy', 'tier': 'policy',
        'band': 'log(BF) 가중 하한 (Jeffreys 스케일서 해석)',
        'rationale': '★정직: 0.3 은 *경험적 정책값*(문헌 도출 아님). progressive 가 효과크기 0 에서도 '
                     '사라지지 않게 하한. log(6)·0.3=0.54 → BF≈1.71(Jeffreys "barely~substantial 경계"). '
                     '원하는 ~1.7× 배율에 맞춘 튜닝값 — Jeffreys 가 0.3 을 주는 게 아님.',
    },
    'abandon_credence': {
        'value': 0.1, 'source': 'policy', 'tier': 'policy_in_scale',
        'band': 'posterior odds 1:9 (BF 9 ∈ Jeffreys substantial)',
        'rationale': '사후신뢰도 0.1 = odds 1:9 정책 문턱. odds→증거등급 해석은 Jeffreys 근거(9 ∈ '
                     'substantial 상단), 0.1 임계 자체는 엔지니어링 선택.',
    },
    'abandon_k': {
        'value': 3, 'source': 'wald1945', 'tier': 'policy_in_scale',
        'band': 'Wald SPRT 하한 lnB(α=β=0.05)=−2.944 의 정수 휴리스틱',
        'rationale': '★정직: K=3 은 *휴리스틱 정수*. SPRT 방법(Wald)은 문헌 근거지만 노드당 LLR 은 '
                     '판결별로 다름(BF 모델: rejected=ln(1/6)=−1.79 nat → ~2 노드서 lnB 교차; partial=0 nat). '
                     'K=3 = 보수적 정수 근사(SPRT 영역). 엄밀판 = should_abandon_sprt(실제 LLR 누적). '
                     '"노드당 0.98 nat" 류 역산 정밀 주장 철회.',
    },
    'abandon_budget': {
        'value': 5, 'source': 'policy', 'tier': 'policy',
        'band': 'SPRT 평균표본수(ASN) 규모의 정책 예산',
        'rationale': '★정직: 예측 적중 0 노드 예산 5 = 정책값. 약증거 누적이 SPRT 하한 도달에 드는 '
                     '표본수 규모(약 lnB/약한per-node)에서 *영감*받은 엔지니어링 선택 — 역산 아님.',
    },
    'abandon_b': {
        'value': 2, 'source': 'policy', 'tier': 'policy',
        'band': '문제수지 적자 한계 (Laudan 영감)',
        'rationale': 'Laudan(1977) 문제해결 효율 — 변명이 문제를 낳는 속도가 해결을 추월(net −2). '
                     'Laudan 원전은 *정성적* → 정량 임계 2 는 도메인 튜너블 정책값(영감: laudan1977).',
    },
    'w_problem': {
        'value': 5.0, 'source': 'policy', 'tier': 'policy',
        'band': '문제수지 vs metric 가중 (Laudan 영감)',
        'rationale': 'Laudan: 해결한 *문제* 1개 > metric % — 문제해결이 과학 목적. 가중 5.0 은 도메인 '
                     '튜너블 정책값(영감: laudan1977, 정성 원전). 보편상수 아님.',
    },
    'nobel_min_hitrate_lb': {
        'value': 0.7, 'source': 'wilson1927', 'tier': 'policy_in_scale',
        'band': 'Wilson 95% 하한 임계 — 실효 통과선 ≈9/9',
        'rationale': 'novel 적중률 Wilson 하한 ≥0.7 정책 임계. Wilson(척도)은 문헌, 0.7 컷은 정책. '
                     '★실효: 8/8 하한 0.676<0.7 탈락, 9/9 하한 0.701 통과 — 이게 진짜 표본 하한(아래 참조).',
    },
    'nobel_min_predictions': {
        'value': 3, 'source': 'wilson1927', 'tier': 'policy_in_scale',
        'band': 'Wilson 유의 최소 n(=3); 단 실효 통과선은 LB 게이트가 결정(≈9)',
        'rationale': '★정직(나생문 F-MATH-1): n=3 은 Wilson 하한이 의미갖는 최소표본일 뿐, *통과 보장 아님*. '
                     'LB≥0.7 게이트가 binding → 3/3 은 하한 0.438 로 탈락, 9/9(0.701)부터 통과. '
                     '즉 두 게이트 AND 의 실효 최소는 9/9. 3 은 하한선, 9 는 통과선.',
    },
    'pagerank_damping': {
        'value': 0.85, 'source': 'brin_page1998', 'tier': 'literature',
        'band': 'PageRank 표준 damping',
        'rationale': 'TrustRank(biased PageRank) damping 0.85 = Brin-Page 원전 표준값(문헌 직접).',
    },
    'eigentrust_alpha': {
        'value': 0.15, 'source': 'kamvar2003', 'tier': 'policy_in_scale',
        'band': 'EigenTrust pre-trusted teleport (=1−0.85)',
        'rationale': '악성 협잡 저항 pre-trusted 가중. ★정정(웹 재검증 2026-06-14): 0.15 는 PageRank '
                     'teleport(1−damping=1−0.85) 표준값이지 Kamvar(2003)가 인쇄한 상수가 아님 — EigenTrust 의 '
                     'pre-trusted 가중 a 에 구조적으로 대응(통상 0.1~0.2). 값은 정책, 방법은 문헌(Kamvar).',
    },
    'default_prior': {
        'value': 0.5, 'source': 'laplace1814', 'tier': 'literature',
        'band': '무차별 원리(principle of indifference)',
        'rationale': '진보/퇴행 사전 동률 = Laplace 무차별 원리(문헌). 숨은 주관 금지, 감사 가능 기준선.',
    },
    'ece_bins': {
        'value': 10, 'source': 'guo2017', 'tier': 'policy_in_scale',
        'band': 'ECE bin 수 (정책 기본값)',
        'rationale': '예측 보정오차(ECE) 구간 수. ★정정(웹 재검증 2026-06-14): Guo et al.(2017) 원전은 '
                     'M=15 bins. 10 은 많은 구현의 흔한 기본값(정책 선택)이지 Guo 의 값이 아님 — ECE *방법*은 '
                     '문헌(Guo), bin *수*는 정책. 값 변경 영향 없어 10 유지(보정데이터 축적 전).',
    },
    'stack_quorum': {
        'value': 2, 'source': 'condorcet1785', 'tier': 'policy_in_scale',
        'band': '3층 중 2층 합의 (단순 다수결)',
        'rationale': '층간 통약불가(gap3) 메타규칙: 폐기는 3층(포퍼/베이즈/라우든) 중 ≥2층 합의에서만. '
                     '다수결 정당화는 Condorcet jury theorem(독립·개별정확도>0.5 가정 — 층 독립성은 '
                     '근사일 뿐임을 정직 표기). 2/3 컷 자체는 정책 선택.',
    },
    'supersession_window': {
        'value': 3, 'source': 'policy', 'tier': 'policy',
        'band': '연속 우세 스냅샷 수 (Lakatos-Zahar 영감)',
        'rationale': '프로그램 대체(supersession) 판정에 필요한 연속 우세 윈도우. Lakatos&Zahar(1976)는 '
                     '*시간을 두고* 입증된 초과 novel 적중을 요구(정성) → 윈도우 3 은 도메인 정책값.',
    },
    'lifecycle_stall_window': {
        'value': 3, 'source': 'policy', 'tier': 'policy',
        'band': '수확/발산 판정 최근 노드 윈도우',
        'rationale': 'lifecycle 종료판정(수확=novel 등록 고갈+안정, 발산=문제수지 적자+정본 정체)의 '
                     '관측 윈도우. ABANDON_K=3 과 같은 규모의 정책값(SPRT 영감, 도출 아님).',
    },
    'fdr_q': {
        'value': 0.05, 'source': 'benjamini_hochberg1995', 'tier': 'policy_in_scale',
        'band': 'BH false discovery rate 목표',
        'rationale': 'gap8 다중비교: 가지가 많을수록 우연 통과(false-progressive)가 늘어남 — '
                     'BH 절차(문헌)로 FDR 통제. q=0.05 컷 자체는 Fisher 1925 이래 관행적 정책값.',
    },
}

# Brier(1950)/Good(1952) = calibrate.py 의 brier_score/log_score *함수* 근거(상수 아님) — SOURCES 등록만.

# tier 별 정직성 요약 (감사용): 어느 값이 문헌이고 어느 게 정책인지 한눈에.
def grounding_tiers() -> dict:
    """tier → 상수 리스트. 정직성 감사 — '문헌값 vs 정책값' 명시 (가짜 정밀 자가검출)."""
    out = {}
    for k, g in GROUNDED.items():
        out.setdefault(g['tier'], []).append(k)
    return out


def provenance(constant: str) -> dict:
    """상수 근거 — value + tier + 문헌 전체인용 + band + rationale. 점수가 자기 근거를 들고 다님."""
    g = GROUNDED[constant]
    return {**g, 'citation': SOURCES.get(g['source'], g['source'])}
