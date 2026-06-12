# 라카토트리 (LakatoTree) — 연구 프로그램 트리 서버

> 모든 연구 = 라카토스 나무 탐색. 판결은 LLM 점수가 아니라 **사전등록 예측 + 스크립트 채점 + 순수함수 규칙**.
> 라카토스의 "판정 기준 애매" 한계는 **라우든 문제해결력 정량층**(문제 수지·PSR·비교 점수·폐기 명문규칙)으로 닫는다.

## 구조
```
lakatos/            순수 판결·지표 모듈 (I/O 0, 어디서든 동일 판정) — 이론 기반 = THEORY.md
  judge.py          [포퍼층] 4판결 + 사전등록 게이트 + 구조적 corroboration(NovelTarget 실측 대조)
  engine.py         ★sparse 연구 프레임 — 가능성/행위이력/신뢰승격/재현계약
  bayes.py          [베이즈층] 가지 신뢰도 = 판결 시퀀스 사후확률. 강한 가지는 반례 하나로 안 죽는다
  laudan.py         [라우든층] 문제 수지/PSR/비교 점수/should_abandon 폐기 3규칙
  explore.py        [탐색배분] bandit UCB + VoI — frontier 질문 우선순위(다음 어느 가지)
  prov.py           [출처추적] W3C PROV-O 트리플 — 판결의 검증가능 계보 + 재현 명령
  fertility.py      [이론 발전성] novel 예측 적중 track record — 과학=예측력, nobel_grade
  trust.py          [인터넷 신뢰] TrustRank/EigenTrust — 웹 증거에 신뢰가중 → 베이즈 결합 (P1)
  adapters.py       ★외부 lineage adapter — OpenLineage/DVC/PROV plain-dict export
  claim.py          ★ClaimStanding — 상계/하계 confidence + foundation/lineage/doubt blocking reason
  argue.py          [논증 채널] Dung AF — 인간+agent 의문/반박, grounded extension 정당성
  calibrate.py      [신뢰도 보정] Brier/log/ECE proper scoring — 예측 정직성
  metrics.py        트리 지표 (진보율/기각률/퇴행/베이즈/★발전성 + 라우든)
  lineage.py        ★데이터 계보 — manifest + env fingerprint + root replay 검증. LINEAGE.md
  harness.py        ★하네스 — 상계/하계/인간/agent 한 사이클 엮기 (포트-어댑터). HARNESS.md
  harness_run.py    하네스 실행기 (실 HTTP/bash/git 포트)
  cli.py            CLI 조작층 (python -m lakatos.cli)
  mcp_server.py     MCP 도구 7종 (Claude/Codex 가 나무 조작)
server/             FastAPI 박층 (:55170) — Neo4j(그래프 정본)+PG(append-only 이력)+Mongo(산출물)
judges/             채점 스크립트 (결과 파일 → metric, LLM 무관)
tests/              판결/엔진/서버계약 TDD — 규칙 변경은 RED 부터
docs/BPC_CONSUMER_A_LONGINUS_20260612.md   consumer_b/consumer_a segmentation 기반지식 Longinus pack
```

## 엔진 개발 기반지식

- `docs/ENGINE_DEVELOPMENT_KNOWLEDGE.md`: 인터넷 관측, 인간/agent critique,
  bash evidence, source history, raw ZDF replayability, OpenLineage/DVC/PROV
  reference mapping.
- `docs/REFERENCE_COMPARISON.md`: OpenLineage/Marquez, DVC, W3C PROV,
  MLflow, NetworkX/Neo4j 와 라카토트리 hard core 비교 및 채택/비채택 경계.
- 핵심 원칙: 버퍼와 캐시는 허용하지만 정본이 아니다. 완성본은 raw root
  manifest 에서 기록된 pipeline 으로 재생성 가능해야 한다.

## 엄격도 스택 (과학철학을 층으로 — 경쟁 아닌 스택)
| 층 | 모듈 | 봄 | 엄격도 |
|---|---|---|---|
| 포퍼 | judge.py | 반증되면 기각 (이산 판결) | 최강 |
| **베이즈** | bayes.py | 증거마다 신뢰도 갱신 (연속). 자산 많은 가지는 반례 하나로 안 죽음 | 중 |
| 라우든 | laudan.py | 참/거짓보다 문제 해결력 | 느슨 |

## 폐기 타이밍 (라카토스가 못 준 시간표)
- 라우든(이산, 해석가능): ① 연속 비진보 ≥3 ② 5노드 예산∧적중0 ③ 문제수지 ≤−2
- 베이즈(연속, 자산가중): 가지 신뢰도 < 0.1. 사전등록 novel 적중 = 강한 증거(BF↑), 사후 땜빵 = 약한 증거(BF≈1)
- 한계 정직: 베이즈는 within-tree 신뢰도만 — **새 가설 탄생은 frontier/directions(가설공간 확장)가 담당**

## 기동/사용
```bash
python -m pytest tests/ -q      # 엔진 검증
bash server/run.sh              # http://localhost:55170 (대시보드 /, API /api/*)
python -m lakatos.cli metrics <tree>      # CLI: 지표(진보율/베이즈/발전성)
python -m lakatos.cli directions <tree>   # CLI: 다음 어느 가지(VoI 우선순위)
python -m lakatos.cli event <tree> <tag> evt-web --realm internet --action fetch_source --payload trust=0.82
python -m lakatos.cli claim-standing <tree> <tag>   # claim standing read-model
python -m lakatos.cli manifest-verify manifest.json   # G-RebuildFromRaw 검증
claude mcp add lakatotree -- python -m lakatos.mcp_server   # MCP: Claude 가 나무 조작
```

## 이론 발전성 (이론적 기반의 예측력 — 과학 판정의 본질)
`fertility.py`: 과학은 이론으로 **새 사실을 미리 얼마나 맞히는가**(novel fact prediction)로 판정된다 — 노벨상의 본질.
발전성 = 적중 novel 예측 / 등록 novel 예측 (사전등록이라 HARKing 불가). nobel_grade = 예측 수 충분 ∧ 적중률 ≥0.7.

## 위계 — 틀(프레임워크) ⊃ 프로젝트
LakatoTree = 추상 형상/틀(domain-agnostic). 그 안에 구체 프로젝트가 인스턴스로 산다(root 데이터·목표 각자).
엔진은 특정 프로젝트를 단칼에 맞추는 dense solver 가 아니라, 가능성·질문·인간/agent 이벤트·인터넷 관측·bash 실행·DB/KG/git 이력을 얇게 엮어 언제든 재현 가능한 연구 흐름으로 보존한다.
예: consumer_b는 root=ZDF인 첫 프로젝트 인스턴스일 뿐이다. KG: `(:LegionCommander)-[:INSTANTIATED_AS]->(:LakatoProject)`.

## v1.1 서버 계약 반영
- `BRANCHED_FROM`은 다중 부모 DAG를 지원하고, edge에 `inferred/relation_kind/evidence_ref`를 기록한다.
- 질문 닫기는 `closed_by` overwrite가 아니라 `QuestionClosure` append-only event로 남긴다.
- verdict 어휘는 `lakatos.verdicts` registry가 단일 출처다.
- `LakatosElement`를 서버/CLI/MCP에서 등록하고 노드의 `USES_ELEMENT`로 연결한다.
- `CANONICAL`은 절대 정본이 아니라 `current_best_pointer`와 scope/assumption/evidence window를 가진 임시 현재 최선이다.
- metrics는 `coverage_backlog`를 보고서에 강제 노출해 전수성 과장을 막는다.
- `ClaimStanding`은 기존 Dung `standing`을 대체하지 않고, 상계(internet/human/kg)와 하계(bash/data/git/agent)를 분리해 confidence와 blocking reason을 보고한다.
- `ResearchEvent`는 판결을 바꾸지 않는 append-only evidence 이며, `claim-standing`이 node 속성/argument/script result 와 함께 읽는다.

## 기반지식 지도
라카토트리 엔진은 연구 전에 필요한 기반지식을 `FoundationRequirement`로 관리한다. 기본 범주는:

- `theory`: 진보/퇴행/부분개선/현재최선의 의미
- `domain`: 프로젝트별 엔티티·관측·개입 어휘
- `data`: root artifact, content hash, stale 정책
- `metric`: metric_name/direction/noise_band/relabel 단절 규칙
- `trust`: 인터넷/문헌/관측 신뢰도와 claim 승격 규칙
- `reproducibility`: lineage DAG, producer sha, rebuild plan
- `human_protocol`: 인간 질문·평가·의문과 agent 빌드 역할 분리

CLI/API:
```bash
python -m lakatos.cli foundation <tree>
python -m lakatos.cli foundation-record <tree> metric-contract --kind metric \
  --question "which metric judges progress?" --accept metric_name --evidence doc:metric-v1 --status satisfied
```

## 위계 — The Great Flow 군단장
라카토트리는 **인류역사흐름의 강물(The Great Flow)의 군단장** — 과학적 연구의 진보를 관장.
KG: `(:GreatFlow)-[:HAS_COMMANDER]->(:LegionCommander LakatoTree_LegionCommander)`.
이론 기반 = `THEORY.md`(7층 + 정직한 8 gaps). 프로토콜·지표 = `~/.claude/skills/lakatos/SKILL.md` (/lakatos). KG 진입 = `(:Doctrine {name:'라카토스'})` (이음동의어 라카토트리).

# KG: SA_LakatoTree_Server_20260612 / Doctrine 라카토스 / LakatosTree_BPC_20View_20260612(첫 인스턴스)
