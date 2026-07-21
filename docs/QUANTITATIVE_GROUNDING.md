# 라카토트리 정량 점수 기반 지식 (Quantitative Grounding)

> 사용자(2026-06-12): **"야매로 점수주는 게 아니라 기반 지식이 풍부하게 있는 기반으로 정확하게 점수를 매겨야"**.
> 정본 = `lakatos/grounding.py` (이 문서는 거기서 `scripts/gen_quantitative_grounding.py` 로 자동생성, 직접 편집 금지).

> ★**정직성(tier)**: 척도/방법이 문헌 근거인 것과 특정 *값*이 정책 선택인 것을 구분한다 — 가짜 정밀(역산값을 derivation 인 척) 금지.
> - `literature` = 값이 문헌서 직접 · `policy_in_scale` = 값은 정책이나 문헌 척도 위 해석 · `policy` = 순수 엔지니어링(영감만 문헌)

## tier 별 정직성 요약

- **literature** (4): `bf_partial_equivalent`, `default_prior`, `pagerank_damping`, `ucb_c`
- **policy_in_scale** (14): `abandon_credence`, `abandon_k`, `bf_progressive`, `bf_rejected`, `ece_bins`, `ece_gate_max`, `ece_gate_min_n`, `eff_cap`, `eigentrust_alpha`, `fdr_q`, `log_score_eps`, `nobel_min_hitrate_lb`, `nobel_min_predictions`, `stack_quorum`
- **policy** (16): `abandon_b`, `abandon_budget`, `claim_min_confidence`, `claim_strong_confidence`, `credibility_extracted_trust`, `credibility_inferred_trust`, `crisis_exploration_scale`, `demote_canonical_penalty`, `effect_size_floor`, `evidence_action_confidence`, `evidence_realm_confidence`, `injection_high_risk_floor`, `lifecycle_stall_window`, `supersession_window`, `w_problem`, `weight_floor`

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
| 0.000 | not_worth_more_than_bare_mention |
| 2.000 | positive |
| 6.000 | strong |
| 10.000 | very_strong |

### 효과크기 — Cohen (1988)
| d 하한 | 등급 |
|---|---|
| 0.000 | negligible |
| 0.200 | small |
| 0.500 | medium |
| 0.800 | large |

## Grounded 상수 정본

| 상수 | 값 | tier | 출처 | 밴드 | 근거(요약) |
|---|---|---|---|---|---|
| `bf_progressive` | 6 | policy_in_scale | jeffreys1961 | Jeffreys substantial [3.162, 10] | single progressive = "substantial" 증거(decisive 아님). 6.0 은 substantial 밴드 *내부의 정책값*(반올림 라운드 |
| `bf_rejected` | 0.1667 | policy_in_scale | jeffreys1961 | substantial (역방향) | log-odds 대칭으로 progressive 의 역수(BF=1/6) — 같은 크기 반대 증거(F-MATH-2). bf_progressive 정책값에 종속(대칭은 |
| `bf_partial_equivalent` | 1 | literature | kass_raftery1995 | not worth more than a bare mention (BF=1) | BF=1 = 무정보(둘 다 흔함) = KR 최저 등급. 신뢰도 불변, 누적 금지(F-MATH-1). 값 1.0 은 "증거 없음"의 수학적 정의 — 정책 아님. |
| `eff_cap` | 4 | policy_in_scale | cohen1988 | Cohen d 스케일 — large(0.8)의 5배 = 포화 | 효과크기 상한(이상치 1방 차단). Cohen large=0.8 대비 5×=4.0 정책 cap — d>4 는 실무서 거의 없음. 스케일은 Cohen, 4.0 ca |
| `weight_floor` | 0.3 | policy | policy | log(BF) 가중 하한 (Jeffreys 스케일서 해석) | ★정직: 0.3 은 *경험적 정책값*(문헌 도출 아님). progressive 가 효과크기 0 에서도 사라지지 않게 하한. log(6)·0.3=0.54 → BF≈ |
| `effect_size_floor` | 1e-06 | policy | policy | 효과크기 분모(noise_band) division-by-zero 가드 하한 | ★정직: 1e-6 은 *순수 수치 가드 정책값*(문헌 도출 아님). effect_size=|delta|/max(noise_band, floor) 의 분모가 0 이 |
| `log_score_eps` | 1e-09 | policy_in_scale | good1952 | Good(1952) log score 의 log(0)=−∞ 클램프 하한 | ★정직: log_score=−log(q) 에서 q=0(완전 빗나간 확신)일 때 −∞ 가 되는 것을 막는 클램프. log score *방법* 은 Good(1952) |
| `ece_gate_max` | 0.1 | policy_in_scale | guo2017 | temperature-scaled well-calibrated ECE(~0.02–0.05, Guo 2017 Table 1)의 한 자릿수 위 | ★정직: ECE *방법*=Guo et al. 2017(ICML, arXiv:1706.04599), τ=0.1 *값*=reliability 척도 위 엔지니어링 정책 |
| `ece_gate_min_n` | 3 | policy_in_scale | wilson1927 | ECE 는 소표본서 noise — n<3 이면 게이트 abstain-closed(존재 스탬프 회귀 금지) | nobel_min_predictions 와 같은 Wilson(1927) 최소표본 근거(n=3). n<3 이면 ECE 추정이 불안정해 보정 인증을 발급하지 않는다  |
| `abandon_credence` | 0.1 | policy_in_scale | policy | posterior odds 1:9 (BF 9 ∈ Jeffreys substantial) | 사후신뢰도 0.1 = odds 1:9 정책 문턱. odds→증거등급 해석은 Jeffreys 근거(9 ∈ substantial 상단), 0.1 임계 자체는 엔지니어 |
| `abandon_k` | 3 | policy_in_scale | wald1945 | Wald SPRT 하한 lnB(α=β=0.05)=−2.944 의 정수 휴리스틱 | ★정직: K=3 은 *휴리스틱 정수*. SPRT 방법(Wald)은 문헌 근거지만 노드당 LLR 은 판결별로 다름(BF 모델: rejected=ln(1/6)=−1. |
| `abandon_budget` | 5 | policy | policy | SPRT 평균표본수(ASN) 규모의 정책 예산 | ★정직: 예측 적중 0 노드 예산 5 = 정책값. 약증거 누적이 SPRT 하한 도달에 드는 표본수 규모(약 lnB/약한per-node)에서 *영감*받은 엔지니어링 |
| `abandon_b` | 2 | policy | policy | 문제수지 적자 한계 (Laudan 영감) | Laudan(1977) 문제해결 효율 — 변명이 문제를 낳는 속도가 해결을 추월(net −2). Laudan 원전은 *정성적* → 정량 임계 2 는 도메인 튜너블 |
| `w_problem` | 5 | policy | policy | 문제수지 vs metric 가중 (Laudan 영감) | Laudan: 해결한 *문제* 1개 > metric % — 문제해결이 과학 목적. 가중 5.0 은 도메인 튜너블 정책값(영감: laudan1977, 정성 원전). |
| `nobel_min_hitrate_lb` | 0.7 | policy_in_scale | wilson1927 | Wilson 95% 하한 임계 — 실효 통과선 ≈9/9 | novel 적중률 Wilson 하한 ≥0.7 정책 임계. Wilson(척도)은 문헌, 0.7 컷은 정책. ★실효: 8/8 하한 0.676<0.7 탈락, 9/9 하 |
| `nobel_min_predictions` | 3 | policy_in_scale | wilson1927 | Wilson 유의 최소 n(=3); 단 실효 통과선은 LB 게이트가 결정(≈9) | ★정직(나생문 F-MATH-1): n=3 은 Wilson 하한이 의미갖는 최소표본일 뿐, *통과 보장 아님*. LB≥0.7 게이트가 binding → 3/3 은  |
| `pagerank_damping` | 0.85 | literature | brin_page1998 | PageRank 표준 damping | TrustRank(biased PageRank) damping 0.85 = Brin-Page 원전 표준값(문헌 직접). |
| `eigentrust_alpha` | 0.15 | policy_in_scale | kamvar2003 | EigenTrust pre-trusted teleport (=1−0.85) | 악성 협잡 저항 pre-trusted 가중. ★정정(웹 재검증 2026-06-14): 0.15 는 PageRank teleport(1−damping=1−0.85) |
| `default_prior` | 0.5 | literature | laplace1814 | 무차별 원리(principle of indifference) | 진보/퇴행 사전 동률 = Laplace 무차별 원리(문헌). 숨은 주관 금지, 감사 가능 기준선. |
| `ece_bins` | 10 | policy_in_scale | guo2017 | ECE bin 수 (정책 기본값) | 예측 보정오차(ECE) 구간 수. ★정정(웹 재검증 2026-06-14): Guo et al.(2017) 원전은 M=15 bins. 10 은 많은 구현의 흔한 기 |
| `stack_quorum` | 2 | policy_in_scale | condorcet1785 | 3층 중 2층 합의 (단순 다수결) | 층간 통약불가(gap3) 메타규칙: 폐기는 3층(포퍼/베이즈/라우든) 중 ≥2층 합의에서만. 다수결 정당화는 Condorcet jury theorem(독립·개별정 |
| `supersession_window` | 3 | policy | policy | 연속 우세 스냅샷 수 (Lakatos-Zahar 영감) | 프로그램 대체(supersession) 판정에 필요한 연속 우세 윈도우. Lakatos&Zahar(1976)는 *시간을 두고* 입증된 초과 novel 적중을 요구 |
| `lifecycle_stall_window` | 3 | policy | policy | 수확/발산 판정 최근 노드 윈도우 | lifecycle 종료판정(수확=novel 등록 고갈+안정, 발산=문제수지 적자+정본 정체)의 관측 윈도우. ABANDON_K=3 과 같은 규모의 정책값(SPRT |
| `fdr_q` | 0.05 | policy_in_scale | benjamini_hochberg1995 | BH false discovery rate 목표 | gap8 다중비교: 가지가 많을수록 우연 통과(false-progressive)가 늘어남 — BH 절차(문헌)로 FDR 통제. q=0.05 컷 자체는 Fisher |
| `ucb_c` | 1.414 | literature | auer2002 | UCB1 탐색계수 | explore.py bandit UCB1 탐색항 계수 c=√2 = Auer et al.(2002) 정본값(문헌 직접). 전엔 explore.py 에 1.414 하 |
| `crisis_exploration_scale` | 2 | policy | policy | Kuhn 위기 시 UCB 탐색항(c) 배율 | Kuhn(1962) 위기(incumbent 퇴행 ∧ 지배 rival 부재)=가설공간 확장 신호 → UCB1 탐색항 c=√2 를 ×2.0 으로 넓혀 덜 본 fron |
| `credibility_extracted_trust` | 0.7 | policy | policy | EXTRACTED 등급 trust 문턱 | trust>=0.70 → 최강 등급 EXTRACTED(게이트 자명통과). spine+engine 공유 정책값. |
| `credibility_inferred_trust` | 0.35 | policy | policy | INFERRED 등급 trust 문턱 | trust>=0.35 → INFERRED, 미만 → AMBIGUOUS. spine+engine 공유 정책값. |
| `claim_strong_confidence` | 0.75 | policy | policy | ClaimStanding strong 문턱 | ClaimStandingPolicy: confidence>=0.75 = 강한 주장. 엔지니어링 정책값. |
| `claim_min_confidence` | 0.5 | policy | policy | ClaimStanding 최소 문턱 | ClaimStandingPolicy: confidence>=0.50 = 최소 standing. 엔지니어링 정책값. |
| `injection_high_risk_floor` | 0.5 | policy | policy | 프롬프트 인젝션 위험 상한(>= → tier AMBIGUOUS 캡) | injection risk>=0.5(시그널 2+)면 상계 증거를 신뢰-추출 불가로 격리(F07 isolation). 차단 아닌 tier 강등 — 인간판정(G-Hu |
| `demote_canonical_penalty` | 0.1 | policy | policy | former_canonical credence 를 새 정본보다 최소 이만큼 아래로 | agm.demote_canonical(THEORY §2 revision): 옛 정본은 제거가 아니라 강등 — credence 를 새 정본보다 0.1 아래 floo |
| `evidence_realm_confidence` | (realm/action dict — 본문 grounding.py 참조) | policy | policy | realm 별 기본 증거신뢰 (명시값 부재 시) | payload 에 명시 confidence 없을 때 realm 기본 신뢰. 서열 DATA(0.70)>BASH/GIT(0.60)>HUMAN/KG(0.50)>AGEN |
| `evidence_action_confidence` | (realm/action dict — 본문 grounding.py 참조) | policy | policy | action 토큰 기반 증거신뢰 (realm 기본값보다 우선) | exit_code 0 / pass·success·replay → 0.80, exit≠0 / fail·reject·error → 0.20, verdict·accep |

## 문헌 정본 (citations)

- **auer2002**: Auer, P., Cesa-Bianchi, N. & Fischer, P. (2002). Finite-time Analysis of the Multiarmed Bandit Problem. Machine Learning 47:235-256 (UCB1, c=√2).
- **benjamini_hochberg1995**: Benjamini, Y. & Hochberg, Y. (1995). Controlling the False Discovery Rate. JRSS-B 57(1):289-300.
- **brin_page1998**: Brin, S. & Page, L. (1998). The Anatomy of a Large-Scale... Hypertextual Web Search Engine.
- **cohen1988**: Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences (2nd ed.).
- **condorcet1785**: Condorcet, M. (1785). Essai sur l'application de l'analyse... (jury theorem — 독립 다수결 > 단일 판정자).
- **good1952**: Good, I.J. (1952). Rational Decisions. JRSS-B 14(1):107-114.
- **guo2017**: Guo, C. et al. (2017). On Calibration of Modern Neural Networks. ICML (ECE; 원전 M=15 bins — Table 1).
- **jeffreys1961**: Jeffreys, H. (1961). Theory of Probability (3rd ed.), Appendix B. Oxford.
- **kamvar2003**: Kamvar, S. et al. (2003). The EigenTrust Algorithm for Reputation Management in P2P Networks.
- **kass_raftery1995**: Kass, R.E. & Raftery, A.E. (1995). Bayes Factors. JASA 90(430):773-795.
- **laplace1814**: Laplace, P.S. (1814). Essai philosophique sur les probabilités (principle of indifference).
- **policy**: 엔지니어링/도메인 정책값 — 문헌 도출 아님 (튜너블). 영감 문헌은 rationale 에 별도 표기.
- **wald1945**: Wald, A. (1945). Sequential Tests of Statistical Hypotheses. Ann. Math. Stat. 16(2):117-186.
- **wilson1927**: Wilson, E.B. (1927). Probable Inference... JASA 22(158):209-212.

## 검증 (상계 WebSearch + 계산, 2026-06-12 / 재확증 2026-06-14)

- Jeffreys 밴드 = 10^(k/2): 3.162/10/31.623/100 ✓ | KR 2ln(BF){2,6,10}→BF{2.72,20.1,148} ✓
- Wald SPRT α=β=0.05 → ln경계 ±2.944 (α+β<1 필수, 아니면 역전) ✓
- Wilson 95% 하한: 10/10=0.722, 9/9=0.701(NOBEL 실효 통과선), 8/8=0.676(탈락), 3/3=0.438 ✓
- ★2026-06-14 정정: eigentrust_alpha(=1−0.85 teleport)·ece_bins(Guo 원전 M=15) → `policy_in_scale` 강등
  (방법은 문헌, 값은 정책). 이 생성기가 grounding.py 정본을 그대로 반영하므로 doc↔code drift 불가.

## 나생문 적대검증 이력 (정직성)

- grounding-fidelity 3렌즈(문헌충실/수학/정직성) 13 confirmed → 전부 수정: tier 도입(정책값 정직표시), _band_label 순서무관, SPRT α+β 검증, NOBEL 실효최소 9 명시, 고아 인용 제거(laudan1977/guo2017/policy 등록).
- 역산 가짜정밀 철회: abandon_k '0.98 nat'(실제 BF rejected=−1.79), weight_floor '0.3=Jeffreys'(실제 정책), bf=6.0 'geom center'(실제 정책).

> 엄격도 스택: Popper(judge 이산) > Bayes(연속신뢰도) > Laudan(문제수지). 점수는 이 척도로만 해석.
