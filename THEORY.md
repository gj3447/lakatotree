# 라카토트리 이론 기반 (THEORY)

> prometheus 12-cell 리서치(과학철학/형식 신념수정/실험추적/탐색의사결정)의 합성.
> 정본 출처: Lakatos *MSRP* (1970), Laudan *Progress and its Problems* (1977),
> Bayesian confirmation theory, AGM belief revision (Alchourrón–Gärdenfors–Makinson 1985),
> W3C PROV-O, Multi-armed bandit (UCB1), Value of Information (Howard 1966).
> ※ 12 웹-리서치 셀은 rate-limit 으로 실패 — 본 이론맵은 정본 명명 출처 기반 합성. 웹 재검증은 frontier.

## 1. 엄격도 스택 (3층, 경쟁 아닌 스택)

| 층 | 이론 | 라카토트리 역할 | 모듈 |
|---|---|---|---|
| **포퍼** (최강) | 반증주의 + Lakatos: 진보=사전등록 novel 적중, 퇴행=사후 땜빵 | 이산 판결 엔진 (4판결), 기각 보존 | `judge.py` |
| **베이즈** (중) | Bayesian confirmation: 신뢰도=판결 시퀀스 사후확률, BF=P(E|진보)/P(E|퇴행) | 자산가중 — 강한 가지는 반례 하나로 안 죽음 | `bayes.py` |
| **라우든** (최약·실용) | 문제해결 효과성 = 해결−미해결 문제 | "언제 퇴행이냐" 명문 폐기 3규칙 | `laudan.py` |

## 2. 보강 4층 (서버 강화 — "너무 얇다" 해소)

| 층 | 이론 | 역할 | 모듈 |
|---|---|---|---|
| 신념개정 | AGM 1985 / Hansson 1993 base revision (Levi identity, entrenchment) | hard_core 개정 형식화(기본 PROTECTED, 동의 시 shift 신호), CANONICAL demote=revision | `agm.py` ✅ |
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

## 4. 이론적 gaps (정직 — 상태 명시, 2026-06-13 갱신)

| # | gap | 상태 | 어떻게/왜 |
|---|---|---|---|
| 1 | novel 채점 (텍스트 존재만으로 차등) | ✅ 닫힘 | `judge.NovelTarget` 구조적 corroboration — 실측 대조 없으면 novel 불인정(F-CON-3) |
| 2 | prior 주관성 (BF_BASE 보정 근거) | 🟡 완화 | grounding tier 공개 + `calibrate.py` Brier/ECE 로 경험 측정 — "problem of the priors" 자체는 원리상 미해결 |
| 3 | 층간 통약불가 (침묵 OR) | ✅ 닫힘 | `stack.py` 명시 투표+정족수 2/3(Condorcet) + conflict 보고. 단 층 독립성은 근사(같은 판결 시퀀스 공유) — 정족수는 '렌즈 3개의 합의' |
| 4 | 라우든 규칙③ dead (per-branch 질문귀속 미배선) | ❌ 미해결 | 엔진은 problem_balance_windowed 인자를 받지만 서버의 per-branch 질문귀속 배선이 없음 — 다음 작업 |
| 5 | AGM entrenchment 유일해 없음 | ✅ 정책 선언으로 닫음 | `agm.py` — 해소가 아니라 사전식 순서를 *선언*하고 모든 결과에 entrenchment_policy 동봉(감사 가능) |
| 6 | bandit reward 순환 (novel 채점 의존) | ✅ 선결 해소 | gap1 닫힘 → reward 의 근거가 구조적 corroboration |
| 7 | 단일 트리 한계 (Kuhn 정량모델 부재) | ✅ 닫힘(범위 한정) | `kuhn.py` — 기계화는 Lakatos-Zahar supersession 기준만, Kuhn 은 상태 어휘. shift 는 자동 아닌 인간 안건 |
| 8 | 통계 표본 미반영 (다중비교 보정) | ❌ 미해결 | 점추정 비교만 — false-progressive 율 추정 없음. 후보: 가지 수에 Bonferroni/BH 보정 |

## 5. 우선순위 (상태 갱신 2026-06-13)

- P0 ✅: 구조적 corroboration(gap1) + PROV-O 계보 + 스크립트 sha256 무결성
- P1 ✅: VoI/UCB directions + AGM hardcore 개정(`agm.py`) + lifecycle 종료판정(`lifecycle.py`)
- P2 ✅: 경쟁 가지 리더보드(`leaderboard.py`+`kuhn.py`) + 인증층(`certify.py`)
- **P3 (신규 frontier)**: gap4 per-branch 질문귀속 서버 배선 + gap8 다중비교 보정 + 신규 층의 서버/CLI/MCP 노출

## 6. 2차 prom 확장 — 인터넷·인간·agent·하계 엮기 (2026-06-12)

> 비전: 라카토트리 = KG(상계) + 인터넷(창/세상) + bash실행(하계) + 인간 + agent 를 엮는 하나의 과정.
> 우선순위: ①인터넷 공간 엮기 ②연구 수행 ③순수 수학구조(창조의 이성적 기쁨).
> 정본 출처: EigenTrust(Kamvar WWW2003), TrustRank(Gyöngyi VLDB2004), Dung AF(1995), Brier(1950)/log score.

| 모듈 | 이론 | 라카토트리 역할 |
|---|---|---|
| `trust.py` | TrustRank(시드전파)·EigenTrust(고유벡터) | **인터넷 증거에 정량 신뢰가중** → 베이즈 P(E|H) 결합. 골방 아님 |
| `argue.py` | Dung 추상 논증(grounded extension) | **인간+agent 비판 채널**: 의문=공격, 반박=재공격. 판결이 grounded extension 에 서야 정당 |
| `calibrate.py` | proper scoring(Brier/log/ECE) | 예측 **신뢰도 보정** — prior 주관성 gap 경험적 측정, 정직성 강제 |

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
