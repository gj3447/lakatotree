# 라카토트리 (LakatoTree) — 연구 프로그램 트리 서버

> 모든 연구 = 라카토스 나무 탐색. 판결은 LLM 점수가 아니라 **사전등록 예측 + 스크립트 채점 + 순수함수 규칙**.
> 라카토스의 "판정 기준 애매" 한계는 **라우든 문제해결력 정량층**(문제 수지·PSR·비교 점수·폐기 명문규칙)으로 닫는다.

## 구조
```
lakatos/            순수 판결·지표 모듈 (I/O 0, 어디서든 동일 판정)
  judge.py          진보/땜빵/동급/기각 4판결 + 사전등록·사후변경 게이트
  laudan.py         문제 수지, PSR, 비교 문제해결력, should_abandon (폐기 타이밍 3규칙)
  metrics.py        트리 지표 (진보율/기각률/퇴행깊이/frontier/라우든 폐기 후보)
server/             FastAPI 박층 (:55170) — Neo4j(그래프 정본)+PG(append-only 이력)+Mongo(산출물)
judges/             채점 스크립트 (결과 파일 → metric, LLM 무관)
tests/              판결 규칙 TDD (16 케이스 — 규칙 변경은 RED 부터)
```

## 폐기 타이밍 (라카토스가 못 준 시간표 — laudan.should_abandon)
① 연속 비진보 ≥ 3  ② 5노드 예산 소진 ∧ 예측 적중 0 (적중 1이면 유예)  ③ 문제 수지 ≤ −2

## 기동/사용
```bash
python -m pytest tests/ -q      # 판결 규칙 검증
bash server/run.sh              # http://localhost:55170 (대시보드 /, API /api/*)
```
프로토콜·지표 정의 = `~/.claude/skills/lakatos/SKILL.md` (/lakatos). KG 진입 = `(:Doctrine {name:'라카토스'})` (이음동의어 라카토트리).

# KG: SA_LakatoTree_Server_20260612 / Doctrine 라카토스 / LakatosTree_BPC_20View_20260612(첫 인스턴스)
