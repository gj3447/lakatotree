# 라카토트리 정량 점수 기반 지식 (Quantitative Grounding)

> 사용자(2026-06-12): **"야매로 점수주는 게 아니라 기반 지식이 풍부하게 있는 기반으로 정확하게 점수를 매겨야"**.
> 정본 = `lakatos/grounding.py` (이 문서는 거기서 자동생성, 직접 편집 금지).

> ★**정직성(tier)**: 척도/방법이 문헌 근거인 것과 특정 *값*이 정책 선택인 것을 구분한다 — 가짜 정밀(역산값을 derivation 인 척) 금지.
> - `literature` = 값이 문헌서 직접 · `policy_in_scale` = 값은 정책이나 문헌 척도 위 해석 · `policy` = 순수 엔지니어링(영감만 문헌)

## tier 별 정직성 요약

- **literature** (5): `bf_partial_equivalent`, `pagerank_damping`, `eigentrust_alpha`, `default_prior`, `ece_bins`
- **policy_in_scale** (7): `bf_progressive`, `bf_rejected`, `eff_cap`, `abandon_credence`, `abandon_k`, `nobel_min_hitrate_lb`, `nobel_min_predictions`
- **policy** (4): `weight_floor`, `abandon_budget`, `abandon_b`, `w_problem`

## 해석 척도 (raw 점수 → 문헌 등급)

### Bayes factor — Jeffreys (1961), 밴드=10^(k/2)
| BF 하한 | 등급 |
|---|---|
| 1.000 | barely_worth_mentioning |
| 3.162 | substantial |
| 10.000 | strong |
| 31.623 | very_strong |
| 100.000 | decisive |

### Bayes factor — Kass & Raftery (1995), 2·ln(BF) — ★원전 최상=very_strong (decisive 없음=Jeffreys 전용)
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

| 상수 | 값 | tier | 출처 | 밴드 | 근거(요약) |
|---|---|---|---|---|---|
| `bf_progressive` | 6 | policy_in_scale | jeffreys1961 | Jeffreys substantial [3.162, 10] | single progressive = "substantial" 증거(decisive 아님). 6.0 은 substantial 밴드 *내부의 정책 |
| `bf_rejected` | 0.1667 | policy_in_scale | jeffreys1961 | substantial (역방향) | log-odds 대칭으로 progressive 의 역수(BF=1/6) — 같은 크기 반대 증거(F-MATH-2). bf_progressive 정 |
| `bf_partial_equivalent` | 1 | literature | kass_raftery1995 | not worth more than a bare mention (BF=1) | BF=1 = 무정보(둘 다 흔함) = KR 최저 등급. 신뢰도 불변, 누적 금지(F-MATH-1). 값 1.0 은 "증거 없음"의 수학적 정의  |
| `eff_cap` | 4 | policy_in_scale | cohen1988 | Cohen d 스케일 — large(0.8)의 5배 = 포화 | 효과크기 상한(이상치 1방 차단). Cohen large=0.8 대비 5×=4.0 정책 cap — d>4 는 실무서 거의 없음. 스케일은 Coh |
| `weight_floor` | 0.3 | policy | policy | log(BF) 가중 하한 (Jeffreys 스케일서 해석) | ★정직: 0.3 은 *경험적 정책값*(문헌 도출 아님). progressive 가 효과크기 0 에서도 사라지지 않게 하한. log(6)·0.3= |
| `abandon_credence` | 0.1 | policy_in_scale | policy | posterior odds 1:9 (BF 9 ∈ Jeffreys substantial) | 사후신뢰도 0.1 = odds 1:9 정책 문턱. odds→증거등급 해석은 Jeffreys 근거(9 ∈ substantial 상단), 0.1 임 |
| `abandon_k` | 3 | policy_in_scale | wald1945 | Wald SPRT 하한 lnB(α=β=0.05)=−2.944 의 정수 휴리스틱 | ★정직: K=3 은 *휴리스틱 정수*. SPRT 방법(Wald)은 문헌 근거지만 노드당 LLR 은 판결별로 다름(BF 모델: rejected=l |
| `abandon_budget` | 5 | policy | policy | SPRT 평균표본수(ASN) 규모의 정책 예산 | ★정직: 예측 적중 0 노드 예산 5 = 정책값. 약증거 누적이 SPRT 하한 도달에 드는 표본수 규모(약 lnB/약한per-node)에서 *영 |
| `abandon_b` | 2 | policy | policy | 문제수지 적자 한계 (Laudan 영감) | Laudan(1977) 문제해결 효율 — 변명이 문제를 낳는 속도가 해결을 추월(net −2). Laudan 원전은 *정성적* → 정량 임계 2 |
| `w_problem` | 5 | policy | policy | 문제수지 vs metric 가중 (Laudan 영감) | Laudan: 해결한 *문제* 1개 > metric % — 문제해결이 과학 목적. 가중 5.0 은 도메인 튜너블 정책값(영감: laudan197 |
| `nobel_min_hitrate_lb` | 0.7 | policy_in_scale | wilson1927 | Wilson 95% 하한 임계 — 실효 통과선 ≈9/9 | novel 적중률 Wilson 하한 ≥0.7 정책 임계. Wilson(척도)은 문헌, 0.7 컷은 정책. ★실효: 8/8 하한 0.676<0.7 |
| `nobel_min_predictions` | 3 | policy_in_scale | wilson1927 | Wilson 유의 최소 n(=3); 단 실효 통과선은 LB 게이트가 결정(≈9) | ★정직(나생문 F-MATH-1): n=3 은 Wilson 하한이 의미갖는 최소표본일 뿐, *통과 보장 아님*. LB≥0.7 게이트가 bindin |
| `pagerank_damping` | 0.85 | literature | brin_page1998 | PageRank 표준 damping | TrustRank(biased PageRank) damping 0.85 = Brin-Page 원전 표준값(문헌 직접). |
| `eigentrust_alpha` | 0.15 | literature | kamvar2003 | EigenTrust pre-trusted teleport (=1−0.85) | 악성 협잡 저항 pre-trusted 가중. Kamvar 권장 ~0.1–0.2 범위 표준(문헌). |
| `default_prior` | 0.5 | literature | laplace1814 | 무차별 원리(principle of indifference) | 진보/퇴행 사전 동률 = Laplace 무차별 원리(문헌). 숨은 주관 금지, 감사 가능 기준선. |
| `ece_bins` | 10 | literature | guo2017 | ECE 표준 bin 수 | 예측 보정오차(ECE) 구간 수 10 = Guo et al.(2017) 등 보정 문헌 표준 관행(문헌). |

## 문헌 정본 (citations)

- **jeffreys1961**: Jeffreys, H. (1961). Theory of Probability (3rd ed.), Appendix B. Oxford.
- **kass_raftery1995**: Kass, R.E. & Raftery, A.E. (1995). Bayes Factors. JASA 90(430):773-795.
- **cohen1988**: Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences (2nd ed.).
- **wald1945**: Wald, A. (1945). Sequential Tests of Statistical Hypotheses. Ann. Math. Stat. 16(2):117-186.
- **wilson1927**: Wilson, E.B. (1927). Probable Inference... JASA 22(158):209-212.
- **brier1950**: Brier, G.W. (1950). Verification of Forecasts Expressed in Probability. MWR 78(1):1-3.
- **good1952**: Good, I.J. (1952). Rational Decisions. JRSS-B 14(1):107-114.
- **guo2017**: Guo, C. et al. (2017). On Calibration of Modern Neural Networks. ICML (ECE, 10-bin 관행).
- **laplace1814**: Laplace, P.S. (1814). Essai philosophique sur les probabilités (principle of indifference).
- **laudan1977**: Laudan, L. (1977). Progress and Its Problems. UC Press (문제해결 효율 — *정성적* 모델).
- **brin_page1998**: Brin, S. & Page, L. (1998). The Anatomy of a Large-Scale... Hypertextual Web Search Engine.
- **kamvar2003**: Kamvar, S. et al. (2003). The EigenTrust Algorithm for Reputation Management in P2P Networks.
- **policy**: 엔지니어링/도메인 정책값 — 문헌 도출 아님 (튜너블). 영감 문헌은 rationale 에 별도 표기.

## 검증 (상계 WebSearch + 계산, 2026-06-12)

- Jeffreys 밴드 = 10^(k/2): 3.162/10/31.623/100 ✓ | KR 2ln(BF){2,6,10}→BF{2.72,20.1,148} ✓
- Wald SPRT α=β=0.05 → ln경계 ±2.944 (α+β<1 필수, 아니면 역전) ✓
- Wilson 95% 하한: 10/10=0.722, 9/9=0.701(NOBEL 실효 통과선), 8/8=0.676(탈락), 3/3=0.438 ✓

## 나생문 적대검증 이력 (정직성)

- grounding-fidelity 3렌즈(문헌충실/수학/정직성) 13 confirmed → 전부 수정: tier 도입(정책값 정직표시), _band_label 순서무관, SPRT α+β 검증, NOBEL 실효최소 9 명시, 고아 인용 제거(laudan1977/guo2017/policy 등록).
- 역산 가짜정밀 철회: abandon_k '0.98 nat'(실제 BF rejected=−1.79), weight_floor '0.3=Jeffreys'(실제 정책), bf=6.0 'geom center'(실제 정책).

> 엄격도 스택: Popper(judge 이산) > Bayes(연속신뢰도) > Laudan(문제수지). 점수는 이 척도로만 해석.
