# HSWM agent network — 행동을 바꾸는 세계모델

> **상태: 설계 계약(design target), 현재 기본 런타임의 기능 주장 아님.**
> LakatoTree에는 사전등록, evidence record, 결정론적 판결, 가지·credence·frontier
> 계산이 구현되어 있다. 하지만 범용 agent attachment, 불변 causal cut, 판결에 따른
> 자동 재배차까지 닫힌 HSWM 네트워크는 아직 구현되어 있지 않다.

## 한 문장 정의

**HSWM이 적용되었다는 것은 agent들이 공유 DB에 결과를 적는다는 뜻이 아니라,
HSWM 네트워크의 현재 causal cut을 읽고, 행동을 전이로 제안하고, 외부 영수증과
LakatoTree 판결을 거친 새 cut 때문에 다음 행동을 바꾼다는 뜻이다.**

따라서 HSWM은 저장 형식이나 특정 그래프 DB가 아니다. 세계 상태, 행동, 관측,
판결, 다음 행동을 하나의 인과적 생명주기로 묶는 network/runtime/protocol이다.
여기서 network는 논리적 네트워크를 뜻한다. 한 프로세스에서도 성립할 수 있고,
분산 agent들로 확장할 수도 있다.

```text
                           HSWM network
┌─────────────────────────────────────────────────────────────┐
│ committed causal cut G_t                                    │
│          │                                                  │
│          ▼                                                  │
│ attached agent ── propose operator ── execute in the world  │
│                                                │            │
│                                                ▼            │
│                              observation / evidence record  │
│                                                │            │
│                                                ▼            │
│                              LakatoTree adjudication        │
│                                                │            │
│                                                ▼            │
│                         validated commit → causal cut G_t+1 │
│                                                │            │
│                                                └── next     │
│                                                    dispatch │
└─────────────────────────────────────────────────────────────┘
```

## 하나의 원자: causal transition

HSWM의 기본 객체를 claim, experiment, agent message마다 따로 발명하지 않는다.
모두 같은 인과적 전이로 본다.

```text
transition :=
    causal parents
  + read set
  + versioned operator
  + proposed outputs
  + evidence / receipt
  + authority
  + observed_at / recorded_at
```

전이는 다음 네 단계의 사건으로 성숙한다.

```text
Proposal → Observation → Verdict → Commit
```

- **Proposal**은 현재 cut과 사전등록된 예측·반증조건·비용 한도를 가리킨다.
- **Observation**은 실행 결과다. 기존 `lakato-evidence-record/v1`을 이 단계의
  portable payload로 재사용한다. producer는 verdict를 쓸 수 없다.
- **Verdict**는 LakatoTree의 버전된 정책이 observation을 판정한 별도 사건이다.
- **Commit**은 작은 결정론적 커널이 causal parent, hash, 권한, 판정 요건을 확인해
  새 cut에서 사용할 수 있도록 허가한 사건이다.

`accepted`는 영원한 진리를 뜻하지 않는다. 해당 cut 이후의 행동이 그 전이를
사용할 권한을 얻었다는 뜻이다. 반증·폐기된 전이도 지우지 않고 causal history와
대안 branch로 보존한다.

## 역할은 분리하되 제품은 늘리지 않는다

| 역할 | 책임 | 금지 |
|---|---|---|
| **HSWM network** | causal cut, 전이 순서, capability, commit, replay, 다음 dispatch | 도메인 판결을 몰래 생성 |
| **attached agent** | cut을 읽고 계산·질문·실험·외부행동을 제안 | 자신의 결과를 스스로 판결 |
| **executor/operator** | 허가된 제안을 실행하고 receipt를 반환 | 관측값을 성공 판정으로 변환 |
| **LakatoTree** | 연구 프로그램, 반증, 의존성, frontier 관점에서 verdict 생성 | 관측값을 조작하거나 실행을 성공으로 보고 |
| **transition kernel** | 형식·인과·권한을 결정론적으로 검증하고 commit | LLM 호출이나 철학적 추측 |

이 역할들은 한 저장소와 한 프로세스 안에 있어도 된다. 필요한 것은 microservice
분리가 아니라 권한과 receipt의 분리다. BHGMAN은 여러 전문 agent와 tool을 제공할
수 있는 **선택적 executor adapter**다. HSWM이나 LakatoTree의 정의상 의존성이 아니다.

## agent attachment 계약

HSWM agent는 단순히 Neo4j나 MCP에 접속한 프로세스가 아니다. 최소한 다음 생명주기를
통과해야 한다.

1. **Attach** — agent identity, capability, operator version을 등록한다.
2. **Context** — HSWM이 `cut_id`, active frontier, 허가된 read set, budget을 준다.
3. **Propose** — agent가 causal parents, operator, 예상 변화, prediction, kill condition을
   가진 전이를 제출한다.
4. **Execute** — 허가된 operator가 계산이나 외부 행동을 수행한다.
5. **Observe** — producer verdict가 없는 grounded evidence record를 반환한다.
6. **Adjudicate** — LakatoTree가 별도 verdict와 의존성 변화를 만든다.
7. **Commit** — 커널이 새 cut을 만들거나 stale parent를 새 branch로 격리한다.
8. **Redispatch** — frontier policy가 새 cut을 읽어 다음 agent/operator를 선택한다.

모든 변경 사건은 content-addressed이고 idempotent해야 한다. 동일 event 재전송은
중복 행동을 만들지 않아야 하며, `observed_at`과 `recorded_at`을 분리해 늦게 도착한
관측이 과거를 조용히 다시 쓰지 못하게 한다.

## 무엇이 실제 폐루프인가

판결을 그래프에 저장하는 것만으로는 feedback이 아니다. 다음의 반사실 검사를
통과해야 한다.

```text
same initial cut + verdict A → next dispatch X
same initial cut + verdict B → next dispatch Y
X != Y
```

다음 행동이 달라지지 않으면 그것은 audit trail 또는 지식그래프이지, 행동을 바꾸는
HSWM 폐루프가 아니다. 추가 acceptance 조건은 다음과 같다.

- 동일 event log를 replay하면 동일한 cut hash가 나온다.
- producer가 observation에 verdict를 넣으면 fail closed한다.
- stale causal parent는 현재 branch를 덮지 못하고 명시적 fork 또는 reject가 된다.
- progressive/rejected 판정은 적어도 하나의 후속 frontier 우선순위나 operator
  eligibility를 다르게 만든다.
- agent가 실행하지 않은 행동을 receipt 없이 완료로 만들 수 없다.

## Markdown과 그래프의 경계

Markdown은 사람이 쓰는 source surface이지 실행 상태가 아니다.

```text
Markdown/Git commit
    → source hash와 span을 가진 Proposal
    → HSWM 생명주기
    → generated annotation 또는 pull request
    → 사람의 다음 수정
```

문서를 LLM으로 해석해도 결과는 untrusted proposal이다. 원문을 자동으로 진실이나
명령으로 승격하지 않는다. 반대 방향의 피드백도 사람의 문장을 몰래 덮어쓰지 않고
generated status, annotation, pull request로 돌려준다.

## 저장소는 의미론이 아니다

유일한 원본은 append-only causal event ledger다. Neo4j, 트리, 대시보드, Markdown은
같은 ledger의 교체 가능한 projection이다.

```text
append-only causal events
          ├─ current HSWM cut
          ├─ Lakatos programme tree view
          ├─ evidence dependency view
          ├─ Neo4j query projection
          └─ Markdown/human review projection
```

따라서 Wolfram에서 가져올 핵심은 특정 hypergraph DB가 아니라 **rewrite event와 그
사이의 causal graph**다. 수학 계산은 pure rewrite, 외부 행동은 effectful rewrite로
취급하되 둘 다 같은 transition envelope를 쓴다. 차이는 요구되는 receipt다.

## 현재 경계와 첫 구현 절단면

| 능력 | 현재 LakatoTree | HSWM target |
|---|---|---|
| 사전등록·grounded evidence·no-self-verdict | 구현됨 | 그대로 재사용 |
| 결정론적 verdict와 replay receipt | 구현됨(측정주권 한계는 별도 ADR 참조) | commit 입력 |
| tree/credence/frontier 계산 | 구현됨 | cut projection과 dispatch policy |
| 범용 agent attach/capability 계약 | 미구현 | 필요 |
| append-only causal cut과 transition commit | 미구현 | 필요 |
| verdict가 다음 agent 행동을 자동 변경 | 미구현 | 폐루프의 결정적 조건 |
| BHGMAN 결합 | 예제 adapter | 선택 사항 |

첫 구현은 BHGMAN 없이 한 프로세스에서 닫는다. 하나의 `OpenQuestion`, 두 개의 작은
operator, 하나의 evidence record, 하나의 LakatoTree verdict, 하나의 다음 dispatch만
연결한다. 그 vertical slice가 위 반사실 검사와 replay 검사를 통과한 뒤에만 분산
agent와 외부 executor를 붙인다.

## 범위 밖

- agent의 모든 토큰이나 비공개 scratchpad를 그래프에 저장하는 것
- 공유 DB에 쓰기만 하면 HSWM이라고 부르는 것
- LLM에게 proposal, measurement, verdict, commit 권한을 동시에 주는 것
- 특정 graph database를 HSWM 자체와 동일시하는 것
- BHGMAN 또는 임의의 multi-agent framework를 필수 의존성으로 만드는 것

HSWM의 최소 명제는 더 작다. **검증된 전이가 공유 세계모델을 바꾸고, 그 변화가
붙어 있는 agent가 다음에 무엇을 하는지를 바꾼다.**
