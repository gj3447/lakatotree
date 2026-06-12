# 라카토트리 (LakatoTree) — 연구 프로그램 트리 서버

> 모든 연구 = 라카토스 나무 탐색. 판결은 LLM 점수가 아니라 **사전등록 예측 + 스크립트 채점 + 순수함수 규칙**.
> 라카토스의 "판정 기준 애매" 한계는 **라우든 문제해결력 정량층**(문제 수지·PSR·비교 점수·폐기 명문규칙)으로 닫는다.

## 구조
```
lakatos/            순수 판결·지표 모듈 (I/O 0, 어디서든 동일 판정) — 이론 기반 = THEORY.md
  judge.py          [포퍼층] 4판결 + 사전등록 게이트 + 구조적 corroboration(NovelTarget 실측 대조)
  bayes.py          [베이즈층] 가지 신뢰도 = 판결 시퀀스 사후확률. 강한 가지는 반례 하나로 안 죽는다
  laudan.py         [라우든층] 문제 수지/PSR/비교 점수/should_abandon 폐기 3규칙
  explore.py        [탐색배분] bandit UCB + VoI — frontier 질문 우선순위(다음 어느 가지)
  prov.py           [출처추적] W3C PROV-O 트리플 — 판결의 검증가능 계보 + 재현 명령
  fertility.py      [이론 발전성] novel 예측 적중 track record — 과학=예측력, nobel_grade
  trust.py          [인터넷 신뢰] TrustRank/EigenTrust — 웹 증거에 신뢰가중 → 베이즈 결합 (P1)
  argue.py          [논증 채널] Dung AF — 인간+agent 의문/반박, grounded extension 정당성
  calibrate.py      [신뢰도 보정] Brier/log/ECE proper scoring — 예측 정직성
  metrics.py        트리 지표 (진보율/기각률/퇴행/베이즈/★발전성 + 라우든)
  cli.py            CLI 조작층 (python -m lakatos.cli)
  mcp_server.py     MCP 도구 7종 (Claude/Codex 가 나무 조작)
server/             FastAPI 박층 (:55170) — Neo4j(그래프 정본)+PG(append-only 이력)+Mongo(산출물)
judges/             채점 스크립트 (결과 파일 → metric, LLM 무관)
tests/              판결 규칙 TDD (16 케이스 — 규칙 변경은 RED 부터)
```

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
python -m pytest tests/ -q      # 엔진 검증 (49 케이스)
bash server/run.sh              # http://localhost:55170 (대시보드 /, API /api/*)
python -m lakatos.cli metrics <tree>      # CLI: 지표(진보율/베이즈/발전성)
python -m lakatos.cli directions <tree>   # CLI: 다음 어느 가지(VoI 우선순위)
claude mcp add lakatotree -- python -m lakatos.mcp_server   # MCP: Claude 가 나무 조작
```

## 이론 발전성 (이론적 기반의 예측력 — 과학 판정의 본질)
`fertility.py`: 과학은 이론으로 **새 사실을 미리 얼마나 맞히는가**(novel fact prediction)로 판정된다 — 노벨상의 본질.
발전성 = 적중 novel 예측 / 등록 novel 예측 (사전등록이라 HARKing 불가). nobel_grade = 예측 수 충분 ∧ 적중률 ≥0.7.

## 위계 — The Great Flow 군단장
라카토트리는 **인류역사흐름의 강물(The Great Flow)의 군단장** — 과학적 연구의 진보를 관장.
KG: `(:GreatFlow)-[:HAS_COMMANDER]->(:LegionCommander LakatoTree_LegionCommander)`.
이론 기반 = `THEORY.md`(7층 + 정직한 8 gaps). 프로토콜·지표 = `~/.claude/skills/lakatos/SKILL.md` (/lakatos). KG 진입 = `(:Doctrine {name:'라카토스'})` (이음동의어 라카토트리).

# KG: SA_LakatoTree_Server_20260612 / Doctrine 라카토스 / LakatosTree_BPC_20View_20260612(첫 인스턴스)
