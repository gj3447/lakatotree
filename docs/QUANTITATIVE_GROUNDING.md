# 라카토트리 정량 점수 기반 지식 (Quantitative Grounding)

> 사용자 요구(2026-06-12): **"야매로 점수주는 게 아니라 기반 지식이 풍부하게 있는 기반으로 정확하게 점수를 매겨야"**.
> 모든 정량 상수/척도는 권위 문헌에 근거한다. 정본 = `lakatos/grounding.py` (이 문서는 거기서 생성, 직접 편집 금지).

## 해석 척도 (raw 점수 → 문헌 등급)

점수는 raw 숫자가 아니라 아래 척도로 **해석**된다 (`grounding.interpret_bayes_factor` 등).

### Bayes factor — Jeffreys (1961)
| BF 하한 | 등급 |
|---|---|
| 1.000 | barely_worth_mentioning |
| 3.162 | substantial |
| 10.000 | strong |
| 31.623 | very_strong |
| 100.000 | decisive |

### Bayes factor — Kass & Raftery (1995), 2·ln(BF)
| 2·ln(BF) 하한 | 등급 |
|---|---|
| 0.0 | not_worth_more_than_bare_mention |
| 2.0 | positive |
| 6.0 | strong |
| 10.0 | very_strong |

### 효과크기 — Cohen (1988)
| d 하한 | 등급 |
|---|---|
| 0.0 | negligible |
| 0.2 | small |
| 0.5 | medium |
| 0.8 | large |

## Grounded 상수 정본

| 상수 | 값 | 출처 | 밴드 | 근거 |
|---|---|---|---|---|
| `bf_progressive` | 6.0 | jeffreys1961 | substantial [3.162, 10] | 단일 progressive 판결 = "substantial" 증거(decisive 아님). Jeffreys substantial 밴드 기하중심 √(3.162·10 |
| `bf_rejected` | 0.16666666666666666 | jeffreys1961 | substantial (역방향) | log-odds 대칭 — rejected 는 progressive 의 역수(BF=1/6). 진보 증거와 같은 크기의 반대 증거(나생문 F-MATH-2). |
| `bf_partial_equivalent` | 1.0 | kass_raftery1995 | not worth more than a bare mention (BF≈1) | 사후 땜빵/동등 = 무정보(둘 다 흔함). BF=1 → 신뢰도 불변, 누적 금지(F-MATH-1). |
| `eff_cap` | 4.0 | cohen1988 | d=4.0 = "large"(0.8)의 5배 — 포화영역 | 효과크기 상한 — Cohen "large"=0.8 의 5배. 이상치 1방이 BF 를 무한정 키우지 못하게(증거 포화). d>4 는 실무서 거의 없음. |
| `weight_floor` | 0.3 | jeffreys1961 | log(BF) 최소 가중 — 마진 개선의 하한 증거력 | 효과크기 0 에 수렴해도 판결 자체(progressive=substantial)가 주는 최소 정보. log(6)·0.3=0.54 → BF≈1.7(Jeffreys  |
| `abandon_credence` | 0.1 | jeffreys1961 | posterior odds ≈ 1:9 (BF 9 ≈ Jeffreys substantial 상단) | 사후신뢰도 0.1 = odds 1:9. 진보 가설이 퇴행 대비 9배 불리 = substantial-to-strong 반대증거 누적. 폐기 문턱. |
| `abandon_k` | 3 | wald1945 | SPRT 하한 lnB(α=β=0.05)=−2.944 의 이산근사 | 연속 비진보 K=3 = Wald SPRT 하한 교차의 휴리스틱. 노드당 로그우도비 ≈−0.98 nat(비진보=퇴행이 e배 우세)이면 3개 누적 −2.94 ≈ ln |
| `abandon_budget` | 5 | wald1945 | SPRT 평균표본수(ASN) 규모 — 약증거 누적 관용창 | 예측 적중 0 인 채 소진 가능한 노드 예산. 약한 per-node 증거(≈0.59 nat)일 때 lnB 도달에 필요한 표본수(2.944/0.59≈5). 적중 1 |
| `abandon_b` | 2 | laudan | 문제수지 적자 한계(정책) | Laudan(1977) 문제해결 효율 — 변명이 문제를 낳는 속도가 해결을 추월(net −2). 정량 임계는 정책값(Laudan 원전은 정성적), SPRT 와 독 |
| `w_problem` | 5.0 | laudan | 문제수지 vs metric 가중(정책) | Laudan: 해결한 *문제* 1개 > metric % 개선 — 문제해결이 과학의 목적. 정책 가중(도메인 튜너블), 보편상수 아님(명시). |
| `nobel_min_hitrate_lb` | 0.7 | wilson1927 | Wilson 95% 하한 ≥0.7 → 사실상 10/10 요구 | novel 예측 적중률의 Wilson 하한 임계. 9/10 하한 0.596<0.7 탈락, 10/10 하한 0.722≥0.7 통과. "운 좋은 소표본" 배제(F-M |
| `nobel_min_predictions` | 3 | wilson1927 | 표본 하한 — Wilson 하한이 의미 갖는 최소 n | 등록 novel 예측 최소 수. n<3 이면 Wilson 하한이 너무 넓어 무의미. |
| `pagerank_damping` | 0.85 | brin_page1998 | PageRank 표준 damping | TrustRank(biased PageRank) damping. Brin-Page 원전 0.85 표준. |
| `eigentrust_alpha` | 0.15 | kamvar2003 | EigenTrust pre-trusted teleport (=1−0.85) | 악성 협잡 저항용 pre-trusted 가중. Kamvar 권장 ~0.1–0.2. |
| `default_prior` | 0.5 | laplace1814 | 무차별 원리(principle of indifference) | 진보/퇴행 사전 동률 — 숨은 주관 금지, 감사 가능한 명시 기준선. |
| `ece_bins` | 10 | good1952 | ECE 표준 bin 수 | 예측 보정오차(ECE) 구간 수 — 문헌 관행 10(Guo 2017 등). |

## 문헌 정본 (citations)

- **jeffreys1961**: Jeffreys, H. (1961). Theory of Probability (3rd ed.), Appendix B. Oxford.
- **kass_raftery1995**: Kass, R.E. & Raftery, A.E. (1995). Bayes Factors. JASA 90(430):773-795.
- **cohen1988**: Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences (2nd ed.).
- **wald1945**: Wald, A. (1945). Sequential Tests of Statistical Hypotheses. Ann. Math. Stat. 16(2):117-186.
- **wilson1927**: Wilson, E.B. (1927). Probable Inference... JASA 22(158):209-212.
- **brier1950**: Brier, G.W. (1950). Verification of Forecasts Expressed in Probability. MWR 78(1):1-3.
- **good1952**: Good, I.J. (1952). Rational Decisions. JRSS-B 14(1):107-114.
- **laplace1814**: Laplace, P.S. (1814). Essai philosophique sur les probabilités (principle of indifference).
- **brin_page1998**: Brin, S. & Page, L. (1998). The Anatomy of a Large-Scale... Hypertextual Web Search Engine.
- **kamvar2003**: Kamvar, S. et al. (2003). The EigenTrust Algorithm for Reputation Management in P2P Networks.

## 검증 (상계 WebSearch + 계산, 2026-06-12)

- Jeffreys 밴드 = 10^(k/2): 3.162 / 10 / 31.623 / 100 ✓
- Kass-Raftery 2ln(BF) {2,6,10} → BF {2.72, 20.09, 148.4} ✓
- Wald SPRT α=β=0.05 → ln경계 ±2.944; `ABANDON_K=3` = 노드당 ≈1 nat 증거의 이산근사 ✓
- Wilson 95% 하한: 10/10→0.722, 9/10→0.596 → 임계 0.7 = 거의 완벽 실적 요구 ✓

> 엄격도 스택: Popper(judge 이산) > Bayes(연속신뢰도) > Laudan(문제수지). 점수는 이 문서의 척도로만 해석.
