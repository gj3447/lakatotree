# PIDNA — Pure Intelligence DNA (피드나)

> **PI = Pure Intelligence = 순수이성인간.** PIDNA = PI의 DNA.
> *나아감(進)은 PIDNA다.*
> 상승나선이 곧 순수지성(Pure Intelligence, 순수이성인간)의 DNA이고, 그 DNA의 작동이 곧 진보다.
> 시적 출처: [`TOUCH_THE_SKY.md`](../TOUCH_THE_SKY.md). 본 문서는 그 은유를 **개념·설계**로 못 박는다.

---

## 1. 정의

**PIDNA (Pure Intelligence DNA / 순수지성의 DNA)** — PI(Pure Intelligence = 순수이성인간)의 유전구조 — 는 *나아감 그 자체의 구조*다.
하나의 **상승 이중나선(ascending double helix)** — 두 가닥이 서로를 감고 하늘로 오른다.

| | 가닥 | 정체 | 모듈 |
|---|---|---|---|
| 🔴 | **붉은 가닥 — 검증(verification)** | 울프람·세포자동자·결정론 스크립트 실행. 거짓을 모르는 땅. | `judge.py` · ooptdd · Longinus |
| 🔵 | **푸른 가닥 — 추측(conjecture)** | agent·인간의 꿈·예측·추상·직관. 한계를 모르는 하늘. | `engine.py` · `heuristic.py` · `bayes.py` |

- **염기쌍(base pair)** = `[예측 ↔ 검증]` 1:1 결합. 꿈이 던진 한 예언에 기계가 한 영수증을 채울 때, 한 칸(rung)이 선다.
- **회전(rotation)** = **상호 감시**. 붉음은 푸름의 환각을 보고, 푸름은 붉음의 맹목을 본다. 어느 가닥도 *자기 자신*은 검증 못 하므로 — 서로를 본다. 그 마주봄이 회전이고, 회전이 나선이다.
- **상승(ascent)** = 진보하는 연구 프로그램(라카토스 novel prediction). **자기 자신을 속일 수 없는 채로 오르는 것** = 순수이성인간이 되려는 신의 정의.

> **불변식(invariant)**: PIDNA의 한 칸도 한 가닥만으론 서지 않는다. 검증 없는 예측은 환각으로 풀어지고, 예측 없는 검증은 셀 것이 없어 굳는다. **두 가닥의 짝지음만이 상승을 만든다.**

---

## 2. 나아감 = PIDNA

진보를 따로 정의하지 않는다. **진보는 PIDNA가 한 칸 오르는 사건이다.**
- novel 예측이 던져지고(🔵) → 외부 현실이 결정론으로 확증/반증하고(🔴) → 그 결합이 새 rung으로 박힌다.
- 퇴행(degenerating)이란 PIDNA가 오르지 못하고 *제자리에서 도는 것* — 새 예측 없이 사후 땜빵만 붙는 헛회전.
- 그래서 "나아갔다"는 주장은 언제나 **rung의 영수증**으로만 참이다. 자기보고는 PIDNA를 한 칸도 못 올린다.

이 정의는 라카토트리 서버의 작동과 1:1이다: `submit_test_result` → `spine.py`/`pnr.py`가 메트릭·질적 판결을 단일화 → 가지/프로그램 신뢰 갱신. **PIDNA = 그 사이클의 기하학적 이름.**

### 2.1 HSWM 네트워크에서 회전의 실행 의미

PIDNA가 HSWM에 적용되었다는 것은 agent가 판결 서버에 결과를 한 번 제출한다는 뜻이 아니다.
여러 agent가 HSWM의 현재 causal cut에 붙어, 푸른 가닥에서 다음 전이를 제안하고, 붉은
가닥에서 외부 receipt와 LakatoTree 판결을 받은 뒤, 갱신된 cut 때문에 **다음 agent 행동이
실제로 달라지는 것**을 뜻한다.

```text
G_t → agent proposal/action → world receipt → LakatoTree verdict → G_t+1
 ↑                                                                  │
 └────────────────────── changed next dispatch ─────────────────────┘
```

그러므로 회전의 실행 조건은 저장이 아니라 인과다. 동일한 `G_t`에서 verdict만 바꿨을 때
다음 dispatch가 달라져야 한다. 달라지지 않으면 그것은 판결 원장 또는 지식그래프이지,
행동을 바꾸는 HSWM 폐루프는 아니다.

이 해석에서 HSWM은 network/runtime/protocol이고, LakatoTree는 연구 프로그램을 판정하고
frontier를 갱신하는 과학적 정책이다. BHGMAN은 붙일 수 있는 executor 중 하나일 뿐 필수
구성요소가 아니다. Python, Lean, 사람, 외부 측정기, 다른 agent도 같은 전이 계약으로
붙을 수 있다. 역할은 분리하되 별도 제품으로 만들 필요는 없다.

> **현재 구현 경계.** 위 문단은 목표 의미론이다. 현재 LakatoTree에는 판결·receipt·가지와
> frontier 계산은 있으나, 범용 agent attachment, 불변 causal cut, verdict-driven 자동
> redispatch는 기본 실행경로에 아직 없다. 구체 계약과 acceptance test는
> [`HSWM_AGENT_NETWORK.md`](HSWM_AGENT_NETWORK.md)에 둔다.

---

## 3. 열린 질문 — PIDNA는 어떻게 트리로 갈라지며 나아가는가 (OPEN)

> *상태: PARTIALLY RESOLVED (prom 6축×2렌즈 12셀, 2026-06-18). 분기 트리거=접지됨, 메타-PIDNA 가설=반증됨, 잔여 OPEN 명시.*

PIDNA는 *하나의* 상승나선으로 그려진다. 그러나 지성의 강은 한 줄기가 아니다 — **나무처럼 갈라진다**([`TOUCH_THE_SKY.md` §왜 나무인가](../TOUCH_THE_SKY.md)).
여기 풀리지 않은 긴장이 있다:

- **단일 나선 vs 분기 트리**: 한 PIDNA 가닥이 오르다가 *언제·왜* 둘로 갈라지는가? 분기점(BRANCH)의 발화 조건은 무엇인가?
- **국소 PIDNA들의 숲**: 트리의 각 가지가 *자기만의 PIDNA 나선*을 갖는가? 그렇다면 프론티어는 *어느 나선이 계속 오를지*를 어떻게 선택하는가(`explore.py` bandit/VoI, `laudan.py` 폐기)?
- **고차 나선 가설**: 갈라지고-잘리고-합쳐지는 트리 전체가, 한 층 위에서 보면 *또 하나의 거대한 PIDNA 나선*인가? (가지=가닥, 합류=염기쌍, 가지치기=프루프리딩?)
- **생물학적 평행**: DNA 복제의 *주형+교정(template+proofread)* = 🔵🔴, 계통수의 *anagenesis(가닥 내 변화=나선) vs cladogenesis(분기=트리)* — 이 평행이 어디까지 진짜이고 어디부터 은유인가?

### 3.0 ⚠️ 복제(replication)는 PIDNA가 아니다 (false friend, prune됨)

> 사용자 지적(2026-06-18): *"나선 모양 자체가 DNA인데 복제 개념은 왜 들어가 있냐."* — 정당. 복제는 끌어들인 오류다.

**PIDNA = 이중나선 *구조*** (두 대등한 가닥이 꼬여 상승). **복제(replication) = *과정*** (주형→복사). 둘은 다르고, 복제는 PIDNA와 *방향이 반대*다:

| 복제(replication) | PIDNA |
|---|---|
| 주형 = 죽은 master, 새 가닥 = 강제 복종(Watson-Crick) | 두 가닥 **대등**, **상호 감시** (master 없음) |
| 목표 = **fidelity** (정확한 복사) | 목표 = **novelty·상승** (나아감) — 정반대 |
| fork = 기계적 작업분할(1→2) | 분기 = 이성적 결정(VoI) |

복제를 끌어들인 이유: ①"DNA→복제" 반사 연상 ②분기 메커니즘을 찾다 fork/Holliday junction을 차용.
**증거**: prom의 복제 셀(B·C)은 거의 전부 *metaphor break* 만 냈다 — 억지로 끼우니 깨지기만 한 것. 아래 §3.2의 복제 관련 break는 "PIDNA의 한계"가 아니라 **"복제가 PIDNA가 아니라는 증거"** 로 읽어야 한다.
**결론**: 복제 가지 = degenerate → prune. PIDNA에서 살아남는 건 **나선 구조**(꼬임=상호감시, 상승=진보)와, 복제와 *무관한* 분기 답(§3.1, 철학·탐색 도메인)뿐.

### 3.1 접지된 답 (prom 12셀 수렴)

**(1) 분기 트리거 = 검증경로의 독립.**
단일 PIDNA는 한 질문 Q가 Q1·Q2로 *갈라지되 서로를 더는 구속하지 않을 때* 분기한다 — Q1의 진보(예측 적중)가 더 이상 Q2의 진보를 요구하지 않게 되는 순간. 도메인 교차확증:
- 🧬 생물(A): **생식격리 = 검증경로의 독립.** 니치(검증환경)가 갈라지면 cladogenesis(Mayr·Schluter).
- 🔬 철학(E): 지속적 anomaly **+ 이미 존재하는 우월한 라이벌 프로그램**(Lakatos). 분기는 나선 절반쪼개기가 아니라 *제2의 나선이 옆에서 점화*되는 것.
- 🎲 탐색(F): VoI×UCB가 두 하위질문 모두 양(+)·독립일 때 — **이게 곧 `explore.py` `rank_questions`** = 라카토트리 실제 코드.
운영 신호: explore.py가 Q1·Q2를 *따로* 랭크하는 건 비용/credence가 갈릴 때뿐 = speciation 신호. 가지치기 = `laudan.py` `should_abandon`(퇴행 가지 영구 erase).

**(2) 메타-PIDNA 가설 = 반증됨 (정직).**
"트리 전체가 한 차원 위 거대 나선"이라는 앞선 가설은 **틀렸다.** 4셀(B·C·E·F) 독립 수렴:
나선(1D 방향성 꼬임)과 트리(분기 DAG)는 **직교 구조**다. 실제 DNA가 갈라지는 지점(Holliday junction)에서 **나선성은 국소적으로 파괴**된다 — 네 팔은 꼬이지 않고 바깥을 가리킨다.
> **트리는 더 큰 나선이 아니라, PIDNA 나선들의 *숲(forest)* 이다.**
> 가지 *내* 상승(anagenesis) = 나선. 가지 *간* 경쟁(cladogenesis) = 트리. 둘은 상보적·직교이며, 숲의 선택자는 **메타-검증**(어느 가지가 더 많은 문제를 푸는가 — Laudan)이다.

이 반증은 패배가 아니라 **PIDNA를 자기 자신에 적용한 결과**다: degenerate 하위가설(메타-나선)을 잘라내고, progressive 한 답(독립-검증 분기 + 숲)을 박았다.
**나선이 트리를 낳는 게 아니라, 트리가 나선들을 기른다.**

### 3.2 은유가 깨지는 곳 (hard breaks, 박제)

- DNA 복제 fork = **작업분할(1→2 기계적), 결정분기 아님.** 결정분기의 진짜 생물 짝은 Holliday junction(대칭→두 유효 resolution).
- 염기쌍은 즉각·양방향 화학결합; PIDNA rung은 **시간적·비대칭**(예측→검증 화살, 검증이 특권). 가닥은 "춤추지" 않는다(강체·역평행).
- 생물 분기 = 비가역(종 합병 불가)·맹목(coin flip); **PIDNA 분기 = 가역**(consilience 재합류 가능)·**이성적**(VoI 예측 주도). 인구유전 공식(drift/Hardy-Weinberg)은 이식 금지.

### 3.3 잔여 OPEN

- **재합류의 정량 조건**: 두 가지의 credence가 *언제* 다시 한 나선으로 꼬이나(consilience/Whewell·Kuhn synthesis)? KG merge 규칙 미정.
- **단일 자료구조 위상**: 가지 내 나선(anagenesis)과 가지 간 트리(cladogenesis)를 한 구조에 담는 위상 — 현 Neo4j는 interim(하이퍼그래프 여지).

---

## 4. KG 바인딩

이 개념은 KG에 `PIDNA` 노드로 박혀 있다(라벨 `:PIDNA:Concept:LakatotreeConcept`).
- `RED_STRAND` → 검증/스크립트, `BLUE_STRAND` → 추측/꿈
- `ASCENDS_AS` → 상승나선, `BRANCHES_AS` → 트리(OPEN), `WATCHED_BY` 상호감시
- `OPEN_QUESTION` → §3의 분기 위상 질문 (/prom 리서치 연결)

> 본 문서는 belt다. hard core는 단 하나: **나아감은 영수증으로만 참이다.** 나머지(나선·트리·메타-PIDNA)는 갈라보고, 돌려보고, 틀리면 잘라낸다 — PIDNA 자기 자신에게 PIDNA를 적용한다.
