# 라카토트리 이론 기반 (THEORY)

> prometheus 12-cell 리서치(과학철학/형식 신념수정/실험추적/탐색의사결정)의 합성.
> 정본 출처: Lakatos *MSRP* (1970), Laudan *Progress and its Problems* (1977),
> Bayesian confirmation theory, AGM belief revision (Alchourrón–Gärdenfors–Makinson 1985),
> W3C PROV-O, Multi-armed bandit (UCB1), Value of Information (Howard 1966).
> ※ **웹 재검증 완료 (2026-06-14, 12/12 셀)**: grounding.py 의 인용·상수를 권위 출처로 재확증 + 적대 adjudication.
> 8 셀 무수정 확증(Kass-Raftery/Cohen/Wald/Wilson/BH/AGM/Laudan/Jeffreys/Bonferroni-Dunn/Lakatos-Zahar),
> 정정 2건 반영: ① `ece_bins`=Guo et al.(2017) 원전 M=15 (10 은 정책 기본값, tier 강등) ② `eigentrust_alpha`=0.15 는
> PageRank teleport(1−0.85)이지 Kamvar 인쇄 상수 아님(tier 강등). 출처 레지스트리 = `grounding.py` SOURCES.

## 1. 엄격도 스택 (3층, 경쟁 아닌 스택)

| 층 | 이론 | 라카토트리 역할 | 모듈 |
|---|---|---|---|
| **포퍼** (최강) | 반증주의 + Lakatos: 진보=사전등록 novel 적중, 퇴행=사후 땜빵 | 이산 판결 엔진 (4판결), 기각 보존 | `judge.py` |
| **베이즈** (중) | Bayesian confirmation: 신뢰도=판결 시퀀스 사후확률, BF=P(E|진보)/P(E|퇴행) | 자산가중 — 강한 가지는 반례 하나로 안 죽음 | `bayes.py` |
| **라우든** (최약·실용) | 문제해결 효과성 = 해결−미해결 문제 | "언제 퇴행이냐" 명문 폐기 3규칙 | `laudan.py` |

> **판결 권위 정직 표기 (T3-2)**: 3층 스택이 *경보/메타규칙*을 주지만, 단일 노드의 최종 판결 권위는
> `spine.py`(reconcile_verdict/dialectical_verdict — 메트릭 판결 + LakatosGate 질적 4기준을 단일화)와
> `pnr.py`(Lakatos *Proofs & Refutations* 변증법 — 반례 *대응 방식*이 진보/퇴행을 가름, 자칭 '심장')가
> 함께 진다. 3층은 그 위에서 가지/프로그램 수준 합의를 본다. (server `submit_test_result` 가 이 둘을 배선.)

## 2. 보강층 (서버 강화 — "너무 얇다" 해소)

| 층 | 이론 | 역할 | 모듈 |
|---|---|---|---|
| 판결 단일화 | reconcile (메트릭 + 질적 LakatosGate 4기준) | 노드 최종 판결 권위 단일 출처 — 메트릭만/질적만의 충돌 해소 | `spine.py` |
| 증명-반박 변증법 | Lakatos 1976 P&R (surrender/monster-barring/lemma-incorporation…) | 반례 대응 방식 채점 — 양의 휴리스틱 정신·초과경험내용 | `pnr.py` |
| 신념개정 | AGM 1985 / Hansson 1993 base revision (Levi identity, entrenchment) | hard_core 개정 형식화(기본 PROTECTED, 동의 시 shift 신호), CANONICAL demote=revision. `/api/agm/revise`+CLI/MCP 노출 | `agm.py` ✅ |
| 출처추적 | W3C PROV-O (Entity/Activity/Agent) | "LLM 점수 금지·스크립트 채점"을 검증가능 계보로 | `prov.py` |
| 탐색배분 | bandit UCB1 + VoI (Howard 1966) | frontier 질문 우선순위 = 신뢰도+미탐색보너스, 기대진보/비용 | `explore.py` |
| 메타-종료 | Lakatos 프로그램 소멸 + regret | 수확/발산/소멸 3-상태 판정 (extinct 는 stack 정족수만 선고) | `lifecycle.py` ✅ |
| 메타규칙 | Condorcet 다수결 (층=철학 렌즈, 독립성은 근사) | 층간 충돌 시 정족수 2/3 — 침묵 OR 제거, conflict 정직 보고 | `stack.py` ✅ |
| 프로그램 비교 | Lakatos-Zahar 1976 supersession + Kuhn 상태 어휘 | 리더보드(Pareto+Borda) + shift_candidate=인간 안건(자동 교체 금지) | `leaderboard.py` `kuhn.py` ✅ |
| 인증 | 게이트 전수 AND (계보 묶음) | 사전등록/재현/standing/보정/grounding 5게이트 인증서 | `certify.py` ✅ |

## 3. 정량 지표 (계산식)

- 진보율 = 100×(m_root−m_canonical)/m_root (동일 scope 정본경로)
- 가지 신뢰도 = odds/(1+odds), odds = prior/(1−prior)×Π BF; BF=exp(ln(base)×w), w=max(min(|Δ|/noise,4)/4, 0.3)
- 문제수지 = closed−opened / PSR = closed/path_nodes
- 퇴행깊이 = 가지 연속 NONPROGRESSIVE 최대 (≥3 경보) / 기각률 = rejected/all (건강 0.2~0.5)
- **VoI(q) ≈ E[Δ진보|q closed] × 1/cost(q)** / **UCB(q) = credence(q) + c·√(ln N/n_q)**
- Bayes 폐기 = credence<0.1 (라우든 이산 3규칙과 OR)

## 4. 이론적 gaps (정직 — 상태 명시, 2026-06-14 갱신: 7 닫힘·1 완화·0 미해결)

| # | gap | 상태 | 어떻게/왜 |
|---|---|---|---|
| 1 | novel 채점 (텍스트 존재만으로 차등) | ✅ 닫힘 | `judge.NovelTarget` 구조적 corroboration — 실측 대조 없으면 novel 불인정(F-CON-3) |
| 2 | prior 주관성 (BF_BASE 보정 근거) | 🟡 완화 | grounding tier 공개 + `calibrate.py` Brier/ECE 경험 측정. **2026-06-14**: `prediction.credence` write-path 배선(전엔 /calibration 영구 n=0=dead path → certify G4 영원히 fail 이었음, T3-1) → 경험루프 실제 작동. "problem of the priors" 자체는 원리상 미해결 |
| 3 | 층간 통약불가 (침묵 OR) | ✅ 닫힘 | `stack.py` 명시 투표+정족수 2/3(Condorcet) + conflict 보고. 단 층 독립성은 근사(같은 판결 시퀀스 공유) — 정족수는 '렌즈 3개의 합의' |
| 4 | 라우든 규칙③ dead (per-branch 질문귀속 미배선) | ✅ 닫힘 | `metrics.branch_inputs` 가 leaf→root chain 에서 `problem_balance_windowed`(per-branch 질문귀속)를 계산 → `/api/tree/{name}/stack`·`/lifecycle` 가 라우든 규칙③에 배선. CLI/MCP `stack`·`lifecycle` 로 노출 |
| 5 | AGM entrenchment 유일해 없음 | ✅ 정책 선언으로 닫음 | `agm.py` — 해소가 아니라 사전식 순서를 *선언*하고 모든 결과에 entrenchment_policy 동봉(감사 가능) |
| 6 | bandit reward 순환 (novel 채점 의존) | ✅ 선결 해소 | gap1 닫힘 → reward 의 근거가 구조적 corroboration |
| 7 | 단일 트리 한계 (Kuhn 정량모델 부재) | ✅ 닫힘(범위 한정) | `kuhn.py` — 기계화는 Lakatos-Zahar supersession 기준만, Kuhn 은 상태 어휘. shift 는 자동 아닌 인간 안건. CLI/MCP `leaderboard`·`paradigm` 으로 노출 |
| 8 | 통계 표본 미반영 (다중비교 보정) | ✅ 닫힘 | `multiplicity.false_progressive_screen` (BH/FDR + Bonferroni/FWER) → `tree_metrics` 에 배선돼 `/api/tree/{name}/metrics` 가 family-level false-progressive 경보 노출. 정직 표기 3건(p=noise_band 1σ *근사*·noise_band=0 검정불가·보정은 판결 불변=family 경보) |

## 5. 우선순위 (상태 갱신 2026-06-14)

- P0 ✅: 구조적 corroboration(gap1) + PROV-O 계보 + 스크립트 sha256 무결성
- P1 ✅: VoI/UCB directions + AGM hardcore 개정(`agm.py`) + lifecycle 종료판정(`lifecycle.py`)
- P2 ✅: 경쟁 가지 리더보드(`leaderboard.py`+`kuhn.py`) + 인증층(`certify.py`)
- P3 ✅: gap4/gap8 + 신규 층 server/CLI/MCP 노출 + **oo LTDD 백본**(`tests/conftest.py`+`oo_sink.test_outcome_records`)
- **gap-audit 캠페인 ✅ (2026-06-14, 38 gap 5차원 감사)**: ①죽은기능 살리기(certify G4 calibration·VoI directions write-path) ②orphan 배선(AGM `/api/agm/revise`+CLI/MCP, harness `cycle` CLI + harness_run 스모크) ③대시보드 전면화(stack/lifecycle/bayes/fertility/multiplicity + per-node 링크 + 리더보드) ④운영 안전망(/healthz·503 graceful·opt-in bearer auth·입력검증) + 이론정직(kuhn 매직넘버→grounding·certify G5 tier값검증·PnR/spine 문서화)
- **P5 (잔여 frontier, 정직)**: ROB-1 KG+PG 비원자성(2PC 필요, 부분실패 시 그래프/이력 분기) + ROB-5 대용량 파일 streaming sha/size cap + 12 웹-리서치 셀 재검증(rate-limit) + harness 서버/MCP 노출(현재 bash RCE 회피로 CLI-only) + 트리노드↔AGM belief 영구 매핑

## 6. 2차 prom 확장 — 인터넷·인간·agent·하계 엮기 (2026-06-12)

> 비전: 라카토트리 = KG(상계) + 인터넷(창/세상) + bash실행(하계) + 인간 + agent 를 엮는 하나의 과정.
> 우선순위: ①인터넷 공간 엮기 ②연구 수행 ③순수 수학구조(창조의 이성적 기쁨).
> 정본 출처: EigenTrust(Kamvar WWW2003), TrustRank(Gyöngyi VLDB2004), Dung AF(1995), Brier(1950)/log score.

| 모듈 | 이론 | 라카토트리 역할 |
|---|---|---|
| `trust.py` | TrustRank(시드전파)·EigenTrust(고유벡터) | **인터넷 증거에 정량 신뢰가중** → 베이즈 P(E|H) 결합. ★배선 정직(LKT-T1): 런타임 trust→bayes 경로는 `evidence_weight(source_trust)`(bayes.bayes_factor 가 실사용). `eigentrust`(고유벡터)는 **이제 런타임 배선됨**: `global_source_trust`(trust.py) → `programme_service.trust_view` → `/api/tree/{name}/trust`(+ judgement_service credence/credibility·eureka 구동). `trustrank`(시드전파)도 **이제 런타임 배선됨**: `global_source_trust(crosscheck=True)` 가 같은 그래프에 trustrank 를 돌려 eigentrust 와 *최상위 신뢰 출처 일치*를 교차검증한다(독립 알고리즘 robustness; coverage.crosscheck). eigentrust=권위, trustrank=교차검증 evidence. (P6 닫힘.) |
| `argue.py` | Dung 추상 논증(grounded extension) | **인간+agent 비판 채널**: 의문=공격, 반박=재공격. 판결이 grounded extension 에 서야 정당 |
| `calibrate.py` | proper scoring(Brier/log/ECE) | 예측 **신뢰도 보정** — prior 주관성 gap 경험적 측정, 정직성 강제 |
| `world_gates.py` | G-Web/G-WorldAction 강제 + injection scan | **상계/하계 증거의 구조화 게이트**(prom32 finding_06/07/08). 인터넷 fetch 는 url/content_hash/source_type/trust/injection-scan/lakatos-location 전수(`web_gate`+`/observation`), bash 는 command/cwd/exit/stdout(+git_diff) 전수(`world_action_gate`+`/world-action`) 통과해야 evidence 적재(미통과 422). injection 은 차단 아닌 risk 부착(상계 untrusted). ★전엔 모델만 있고 게이트 미강제 → enforced 배선. |

- **인터넷→베이즈**: `bayes_factor(..., source_trust)` — 권위 출처(높은 TrustRank) = 강한 증거, 저신뢰는 floor 까지 감쇠. evidence_weight(trust) 가 log(BF) 에 곱.
- **역할분담**: 인간+agent = critique(질문/의문/평가, Dung attack) / 순수 agent = 코드빌딩(test_result). 의문이 막히지 않으면(stands=False) 판결 재검토.
- **상계/하계**: 노드(상계 추상)는 하계(bash실행·인터넷fetch·실측)로 채점. 인터넷 = 질의가능한 세상의 창.
- 새 지표: 출처신뢰(TrustRank/EigenTrust 벡터), 판결 정당성(grounded extension 포함 여부), Brier/log/ECE(보정).

## 7. 엔진 개발 참조층 — 오픈소스는 adapter, hard core 는 내부 규칙

상용/오픈소스 lineage 도구를 그대로 흡수하지 않는다. 라카토트리의 hard
core 는 `LakatosGate + critique + replayability` 이고, 외부 도구는 adapter
또는 schema reference 로 쓴다.

| Reference | 가져올 것 | 라카토트리 대응 |
|---|---|---|
| OpenLineage | Run/Job/Dataset event vocabulary | `PipelineRun`, `TransformStep`, `RawDataArtifact`, `DerivedDataArtifact` |
| Marquez | OpenLineage metadata server and lineage UI | optional lineage graph viewer/backend |
| DVC | raw deps + command + params + output hash replay model | `RebuildRecipe`, `DatasetManifest`, `G-RebuildFromRaw` |
| W3C PROV / Python `prov` | Entity/Activity/Agent provenance serialization | `InternetObservation`, `BashAct`, `AgentBuild`, `PipelineRun` |
| MLflow Dataset Tracking | params/metrics/artifact logging pattern | auxiliary experiment mirror, not verdict authority |
| NetworkX / Neo4j | in-memory graph algorithms / persistent KG mirror | pure tests stay DB-free; KG mirror remains queryable |

Development seed: `docs/ENGINE_DEVELOPMENT_KNOWLEDGE.md`.
Reference comparison and upgrade boundary: `docs/REFERENCE_COMPARISON.md`.
Implemented adapter surface: `lakatos/adapters.py`.

## 8. 토대 정직 — 묶지 않은 철학적 라이선스 (Longinus 토대 바인딩, 2026-06-23)

> grounding 이 *숫자*(상수)를 출처에 못 박았듯, 이 절은 *간판 메커니즘의 철학적 라이선스*를 못 박는다.
> "영수증 없는 상수 금지"의 한 층 위 = **라이선스 없는 메커니즘 금지.** 메커니즘이 어떤 철학적 주장에
> 의존하면서 그 출처를 안 밝히면, 그것이야말로 이 엔진이 금지하는 "영수증 없는 권위 주장"의 자기적용이다.
> 27 후보를 적대검증(정말 grounding 부재인가 grep + 인용 실재·정확성)해 가렸다. 전부 *정성/공개 tier*
> (상수 도출 0, 로직 변경 0 — kuhn1962/laudan1977/feyerabend1975 와 동급), 출처는 `grounding.SOURCES` 등록.

| 개념(라이선스) | 정본 출처(SOURCES 키) | 코드 앵커 | 바인딩 판정 |
|---|---|---|---|
| Duhem–Quine 미결정성/홀리즘 | `duhem1906`·`quine1951` | `agm.py`(핵/보호대) · `judge.py`(`partial`) | UNBOUND→묶음 (high) |
| 재현성 위기/연구자 자유도 (사전등록=처방) | `simmons2011`·`ioannidis2005`·`nosek2018`·`chambers2013` | `judge.py`(PredictionLocked) · `certify.py` G1 | UNBOUND→묶음 (high) |
| 우도주의/우도법칙 (BF=증거) | `royall1997` | `bayes.py`(`odds*=bf`) | UNBOUND→묶음 (high) |
| 관찰의 이론적재성 | `hanson1958` | `judge.py`(sha-distinct) · `spine.py`(no_receipt) | PARTIAL(코드 부분답) (high) |
| 구성타당도 | `cronbach_meehl1955` | `judge.py`(metric_name 불투명) | UNBOUND→묶음 (high) |
| 측정척도론 | `stevens1946` | `judge.py`(delta/effect_size) | UNBOUND→묶음 (high; 코드가드 미구현) |
| Goodman grue/투사가능성 | `goodman1955` | `judge.py`(`corroborated()` 진보규칙) | UNBOUND→묶음 (high; 사전등록자 위임=공개 한계) |
| Kuhn 1977 가치-미결정 | `kuhn1977` | `leaderboard.py`(무스칼라 Pareto) | PARTIAL(메커니즘 구현·인용만) (high) |
| 인과/교란 | `pearl2009`(+Rubin·Hill) | `judge.py`(`corroborated()` 연관만) | UNBOUND→묶음 (high; 장치 일부 범위밖) |
| Mayo severe testing/오류통계 | `mayo1996` | `judge.py` predict-lock-measure · `fertility.py` | UNBOUND→묶음 (medium) |
| 베이즈 일관성+Cox (왜 확률공리) | `ramsey1926`·`definetti1937`·`cox1946` | `bayes.py` · `formal/Pidna.lean` coherence | UNBOUND→묶음 (medium) |
| Hempel 확증 + Glymour tacking | `hempel1945`·`glymour1980` | `judge.py`(H-D) · `pnr.py`(excess_content) | UNBOUND→묶음 (medium) |
| Neyman–Pearson 오류율/검정력 | `neyman_pearson1933` | `grounding.sprt_log_boundaries`(α/β) | PARTIAL (medium) |
| 구조적 논증(+Dung 자체) | `dung1995`·`toulmin1958` | `argue.py` · `evidence_claim_service._assemble_af` | UNBOUND→묶음 (medium) |
| 논증 스킴/비판질문 | `walton_reed_macagno2008` | critique kinds(`mcp_server`/`cli`) | UNBOUND→묶음 (medium) |
| Jeffreys–Lindley 역설 | `lindley1957` | `stack.py` 정족수(bayes vs popper) | PARTIAL (low) |

**영수증의 정직한 중립성 (theory-ladenness 응답).** "현실이 영수증을 끊는다"는 *아르키메데스적*(패러다임
밖) 중립을 주장하지 않는다 — metric_name/measured 는 같은 프로그램이 고른다. 영수증이 *자기위주 재해석*을
막는 근거는 더 약하지만 실재하는 중립이다: **사전등록 락(metric_name 고정) + sha-distinctness(독립 출처
강제) = *사전약속되고 독립조달된* 이론적재성**(중립 절단 아님, Hanson 1958). 이 한 줄이 붉은 가닥의 진짜
권위 범위다 — 과장(neutral receipt)을 정직한 주장(pre-committed + independently-sourced)으로 바꾼다.

**동기부여/범위밖 (정직 공개 — 바인딩 안 함).**
- **Whewell consilience**: 재합류 연산자 부재(`docs/PIDNA.md` "KG merge 규칙 미정"; 가지는 `BRANCHED_FROM`
  으로 갈라지기만). 동기부여 — 운영가능한 독립성/severity 지표가 생기기 전엔 'Occam' force_of 처럼 수사적.
- **van Fraassen 구성경험론 vs 실재론**: 엔진은 'canonical'을 *진리*가 아니라 *경험적 적합성-현재최선*으로
  읽는다 — 어느 노드를 실재론/구성경험론으로 뒤집어도 채점경로·게이트·grounded extension 불변(범위밖).
- **Wolfram 계산불가역성 · Darwin 인식론**: 기존대로 0줄 동기부여(`TOUCH_THE_SKY.md` 공개).
