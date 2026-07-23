# HSWM × LakatoTree 연구 프로그램 — 계속할 이유와 멈출 조건

> **상태: 연구 의사결정 계약(research decision contract).**
> 이 문서는 HSWM의 효과를 주장하지 않는다. 왜 지금 당장 폐기하지 않는지, 어떤
> novel prediction을 먼저 잠글지, 어떤 결과가 나오면 계속·축소·폐기할지를 사전에
> 명시한다. 이 문서 자체도 LakatoTree의 판정 대상이다.

## 결정

**무기한 신뢰하지 않는다. 그러나 하나의 결정적 vertical slice와 equal-compute
benchmark를 수행하기 전에는 폐기하지 않는다.**

현재의 합리적 선택은 `BELIEVE`가 아니라 `RUN THE NEXT DISCRIMINATING EXPERIMENT`다.
성공 확률을 과장할 이유도 없고, 아직 값싼 반증 실험을 하지 않은 option을 버릴
이유도 없다.

```text
research option value
  ≈ probability of a real effect × value if real
    − cost of the next discriminating experiment
```

HSWM은 상방이 크고 다음 실험 비용이 아직 작다. LakatoTree의 독립된 판결·receipt
자산이 하방을 받친다. 그러므로 다음 실험의 정보가치가 양수인 동안만 계속한다.

## 왜 계속할 가치가 있는가

### 1. 실제 병목을 겨냥한다

Agent는 가설, 코드, 설명을 싸게 대량 생성하지만, 그 결과의 외부 타당성은 자동으로
따라오지 않는다. proposal producer가 measurement와 verdict까지 소유하면 빠른 생성이
빠른 자기확증으로 바뀐다. LakatoTree의 사전등록, no-self-verdict evidence,
결정론적 판결, 독립 verifier는 이 병목에 직접 대응한다.

### 2. 아이디어만 있는 프로그램이 아니다

현재 저장소에는 pure verdict kernel, evidence contract, replay/provenance, programme
state, frontier 계산, Lean 모델, 독립 verifier가 있다. HSWM runtime은 아직 목표지만,
그 목표를 시험할 measurement substrate는 이미 존재한다. 첫 실험을 위해 전체 시스템을
새로 만들 필요가 없다.

### 3. 후보 기여가 분리 가능하다

Hypergraph, world model, multi-agent, closed-loop science 각각은 새롭지 않다. 후보
기여는 다음의 **결합 규칙**이다.

> 경쟁 연구 프로그램, agent 행동, 외부 receipt, 반증과 판정을 하나의 causal
> transition network에 놓고, programme-level adjudication이 다음 agent dispatch의
> 권한과 우선순위를 바꾸게 한다.

이것은 아직 novelty claim이 아니라 검증할 contribution hypothesis다. 체계적 문헌
검색과 benchmark에서 차이가 확인되기 전에는 “최초”라고 부르지 않는다.

### 4. 결정적 실험이 작다

완전한 AGI나 물리 실험실이 없어도 첫 가설을 반증할 수 있다. 결정론적 외부 evaluator가
있는 repository-level 연구 과제에서 한 프로세스, 한 `OpenQuestion`, 두 operator,
한 verdict-driven redispatch를 연결하면 된다. 이 작은 실험이 인과 고리를 못 닫으면
분산 agent와 새 DB를 붙일 이유가 없다.

### 5. 큰 가설이 실패해도 자산이 남는다

HSWM의 성능 가설이 실패해도 portable evidence record, independent verification,
research-programme audit, benchmark와 negative result는 독립적으로 쓸 수 있다.
실패 비용 전체가 폐기되지 않으므로 다음 실험의 option value가 높다.

## 전체 조망: 어디가 겹치고 어디를 검증해야 하는가

인접 연구는 이미 상당히 전진했다. 다음은 HSWM의 우선권 주장이 아니라 **중복을
피하기 위한 경계 지도**다.

| 인접 방향 | 이미 보인 것 | HSWM이 그대로 주장하면 새롭지 않은 것 |
|---|---|---|
| [Dynamic-KG distributed self-driving laboratories (Nature Communications, 2024)](https://www.nature.com/articles/s41467-023-44599-9) | agent network가 KG를 갱신하며 물리 실험의 closed loop를 조정 | “agent가 KG에 붙어 실험한다” |
| [Robin multi-agent scientific discovery (Nature, 2026)](https://doi.org/10.1038/s41586-026-10652-y) | 가설·후속 실험·결과 해석·갱신 가설의 lab-in-the-loop | “과학 agent가 반복 실험한다” |
| [SciAgents graph reasoning (arXiv, 2024)](https://arxiv.org/abs/2409.05556) | knowledge graph와 여러 agent가 과학 가설을 생성·비판·수정 | “graph 기반 multi-agent 과학추론을 한다” |
| [AutoLabs autonomous chemical experimentation (Scientific Reports, 2026)](https://www.nature.com/articles/s41598-026-45593-z) | multi-agent가 화학 실험을 계획·실행·감시·자기수정 | “multi-agent가 closed-loop 실험을 수행한다” |
| [Shared Cognitive Substrates (MALGAI 2026 position)](https://openreview.net/forum?id=RRIw2L4Z1g) | text passing 대신 typed world model과 causal graph를 공유하는 설계 | “agent가 shared world model에서 조정된다” |
| [Continual causal-model refinement (UCRL@ICLR 2026)](https://openreview.net/forum?id=jJbzfjODQt) | 행동 루프 안에서 symbolic causal world model을 온라인 학습·수리 | “world model이 계속 바뀐다” |

따라서 연구의 중심은 hypergraph라는 명사나 closed loop라는 표어가 아니다. 평가할
차이는 **Lakatosian programme policy + receipt-separated authority + causal redispatch**다.

이 경계의 기계판독 정본은 [`hswm_related_work.json`](hswm_related_work.json)이다.
Longinus 가드는 각 reference의 URL·중복금지 주장·근거 tier가 이 문서와 함께 움직이는지,
KG anchor와 grounding registry에 선언됐는지 검사한다. 이 목록에 경쟁 연구가 없다는
사실은 우선권 증거가 아니며, systematic review receipt 없이는 “최초”를 주장하지 않는다.

## 잠글 중심 가설

### H1 — 시스템 수준 novel prediction

> **고정된 모델·도구·시간·토큰/실행 예산에서, receipt-gated HSWM feedback을 사용하는
> agent는 비교군보다 단위 비용당 외부 검증된 진보를 더 많이 만들고, 잘못된 진보
> 주장과 반증된 행동의 반복을 더 적게 만든다.**

1차 지표는 하나로 잠근다.

```text
Validated Progress per Cost (VPC)
  = externally accepted novel outcomes / normalized total cost
```

`externally accepted`는 producer의 자기보고가 아니라 hidden tests, independent script,
formal checker 또는 사전에 지정된 외부 evaluator로 결정한다. `cost`는 모델 호출,
토큰, tool execution, wall-clock 중 실험 전에 정한 정규화 합계다.

2차 진단 지표는 다음과 같다.

- **False Progress Rate** — agent가 성공을 주장했지만 외부 gate가 거부한 비율
- **Refutation Adaptation Latency** — 전제 반증 후 그 전제에 의존한 행동을 멈출 때까지의 action 수
- **Redundant Experiment Rate** — 같은 실패 원인을 정보 증가 없이 반복한 비율
- **Novel Hit Rate** — 사전등록된 novel prediction 중 독립 확증된 비율
- **Replay Integrity** — 동일 event log가 동일 causal cut hash를 만드는 비율

2차 지표를 사후에 1차 성공 기준으로 승격하지 않는다.

### H2 — hypergraph의 추가 가설

> **같은 feedback policy에서 higher-order causal dependency를 직접 표현하는
> hypergraph projection은 단순 event log/property-graph projection보다 의존성 수정과
> 반증 전파를 더 정확하거나 저렴하게 만든다.**

H2가 실패하면 hypergraph를 구현 선택으로 강등한다. H1까지 함께 폐기할 이유는 없다.
반대로 H1 없이 H2만 성공해도 “continuous-learning agent architecture”의 성공으로
과장하지 않는다.

## 비교군과 통제

모든 조건은 같은 base model, model version, tool access, task set, hidden evaluator,
총 예산과 중단 규칙을 사용한다.

| 조건 | 상태와 판정 | 다음 행동 |
|---|---|---|
| **B0 Plain agent** | 대화/context 내부 기록 | agent 자체 선택 |
| **B1 Shared log/KG** | 공통 상태와 provenance만 제공 | verdict-driven 재배차 없음 |
| **B2 LakatoTree audit** | 독립 verdict를 생성·기록 | agent policy에는 자동 반영하지 않음 |
| **B3 Full HSWM** | causal cut + receipt + LakatoTree verdict | verdict가 frontier/eligibility/dispatch를 변경 |
| **B4 HSWM non-hypergraph ablation** | B3와 같은 policy, 단순 event DAG/property graph | H2 분리 평가 |

비교는 가능한 한 blinded seed와 독립 evaluator를 사용한다. task 수는 결과를 본 뒤
정하지 않고 pilot variance를 이용한 power analysis로 사전 고정한다. 실패 seed 제거,
prompt 사후 튜닝, 유리한 metric 교체는 새로운 preregistration 없이는 금지한다.

## 단계별 실행과 gate

### Phase 0 — 의미론 동결

- `Proposal → Observation → Verdict → Commit → Redispatch` 이외의 평행 write path를 금지한다.
- agent identity, capability, causal parent, idempotency, bitemporal fields를 잠근다.
- 새 철학 계층은 operator, metric, falsifier 중 하나를 바꾸지 않으면 추가하지 않는다.

**Gate:** schema와 state transition을 두 사람이 독립 구현해 같은 replay hash를 만들 수 있다.

### Phase 1 — 한 프로세스 vertical slice

- 한 `OpenQuestion`과 두 개의 결정론적 operator만 사용한다.
- verdict A/B를 주입했을 때 다음 dispatch X/Y가 달라지는 반사실 테스트를 만든다.
- stale parent, duplicate event, self-authored verdict가 fail closed하는지 확인한다.

**Gate:** causal feedback과 replay가 테스트로 증명되지 않으면 여기서 중단한다.

### Phase 2 — equal-compute benchmark

- 먼저 외부 정답을 숨길 수 있는 software/scientific-computing 과제를 사용한다.
- B0–B3를 동일 예산으로 비교하고 H1의 VPC를 평가한다.
- effect size, confidence interval, 모든 seed와 실패를 공개한다.

**Gate:** 사전등록한 실용적 최소효과를 넘지 못하면 HSWM 성능 주장을 축소한다. 새 개념을
추가해 같은 benchmark를 사후 구조하는 것으로 실패를 덮지 않는다.

### Phase 3 — 표현 ablation

- B3와 B4로 H2를 분리한다.
- 반증된 전제가 연결된 주장·계획·행동에 전파되는 정확도, latency, storage/query cost를 잰다.

**Gate:** hypergraph 이점이 없으면 Neo4j/event DAG를 포함한 단순 projection을 채택하고
“hypergraph가 본질”이라는 주장을 폐기한다.

### Phase 4 — network scale-out

- single-process gate를 통과한 뒤에만 여러 agent와 외부 executor를 붙인다.
- BHGMAN은 이 단계의 선택적 adapter다. BHGMAN 부재는 Phase 0–3의 blocker가 아니다.

## 축소·폐기 조건

다음 중 하나가 충족되면 해당 주장을 보호하기보다 축소하거나 폐기한다.

1. 두 개의 사전등록되고 충분한 검정력을 가진 서로 다른 task family에서 B3가 B1/B2보다
   VPC의 실용적 최소효과를 넘지 못한다.
2. verdict를 바꾸어도 다음 행동이 안정적으로 달라지지 않거나, 달라져도 결과 향상과
   인과적으로 연결되지 않는다.
3. LakatoTree verdict가 hidden evaluator 또는 독립 전문가 판정과 반복적으로 불일치한다.
4. feedback의 이득보다 orchestration, latency, storage, 운영 실패 비용이 크다.
5. 실패 뒤 prediction·metric·kill condition을 바꾸는 사후 보호대만 늘어난다.
6. producer, observer, judge, committer의 권한분리를 실제 배치에서 유지할 수 없다.

폐기 단위는 구분한다.

- H2 실패 → hypergraph 본질 주장만 prune
- H1 실패 → HSWM 성능 주장 prune, LakatoTree audit/verification은 독립 평가
- 외부 판정 정합성 실패 → LakatoTree scoring policy 재검증 또는 폐기
- replay/authority 실패 → network runtime 배치 금지

## 성공했을 때의 가치

- **과학적 가치:** agent 성능을 답변 품질이 아니라 검증된 프로그램 진보와 반증 적응으로 측정한다.
- **시스템 가치:** agent의 행동, 관측, 판정, 학습을 replay 가능한 한 인과 경로로 만든다.
- **안전 가치:** proposal producer가 성공 판정과 commit 권한까지 독점하지 못하게 한다.
- **철학적 가치:** Lakatos의 연구 프로그램을 회고적 분류가 아니라 실행 가능한 control policy로 시험한다.
- **부정결과 가치:** epistemic feedback 또는 hypergraph가 비용만 늘린다는 결과도 재사용 가능한 benchmark가 된다.

가장 큰 연구 가치는 “아름다운 구조” 자체가 아니다. 아름다움은 원시 객체 하나,
write path 하나, 명시적 권한분리로 복잡성을 줄이는 설계 기준이다. 최종 가치는 그
구조가 **agent가 다음에 무엇을 하는지를 더 낫게 바꾸는가**로만 판정한다.

## 당분간 하지 않을 것

- H1 vertical slice 전에 새로운 철학자·메타포·판정층을 추가하지 않는다.
- benchmark 전에 AGI, consciousness, transformer replacement를 성공 주장에 넣지 않는다.
- H2 ablation 전에 graph database 교체를 핵심 연구 성과로 취급하지 않는다.
- 외부 evaluator 없이 LakatoTree가 자기 효과를 스스로 채점하지 않는다.
- BHGMAN 통합을 HSWM 존재 조건으로 만들지 않는다.

다음 행동은 하나다. **H1을 사전등록하고, Phase 1의 작은 폐루프를 구현해, verdict가
다음 행동과 외부 결과를 실제로 바꾸는지 측정한다.**
