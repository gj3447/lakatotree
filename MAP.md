# LakatoTree 전체 지도 (MAP)

> 파편화된 정본·문서·코드의 단일 진입점. 산문은 설명 뷰다 — 충돌 시 기계 파일(spec·스키마·테스트)이
> 이긴다. 최종 갱신 2026-08-11 (ts-rebuild 1390430 — 게이트웨이 에픽 완결). 갱신 규칙: 층 구조나 정본 위치가 바뀌는 커밋만
> 이 파일을 손댄다 (일상 슬라이스는 손대지 않음 — 지도가 또 하나의 파편이 되지 않게).

## 0. 한 문장

LakatoTree = 연구 프로그램의 진보 주장을 **사전등록 → 측정 → 결정론 judge 판정 → 불변 영수증**으로만
인정하는 연구 원장 엔진 — 에이전트가 자기 점수를 매기는 경로가 구조적으로 표현 불가능해야 한다.

## 1. 층 구조

| 층 | 위치 | 지위 |
|---|---|---|
| Python 정본 엔진 | `lakatos/` `server/` | 운영 정본. 독립 스토어 2개(:55170 delltower 81트리 / 192.168.0.26 108트리 — 같은 포트, 서로 딴 데이터) |
| 외부 재검증기 | `c1verify/` | 엔진 코드 0 import 로 Certificate 재검증 (import-linter + clean-venv CI 로 구축 사실 증명) |
| 이론 모델 | `formal/` (Lean4) · `THEORY.md` | judge 커널의 이론 검증 — Python 바이너리·측정의 참을 검증하지 않음 (정직 범위) |
| **TS 함수형 재개발** | `ts/` | **PROPOSED/무측정** — 신규 개발장. Python 은 레퍼런스 오라클이며 ts 작업의 수정 대상 아님. 오라클 파리티는 아직 주장하지 않음 (`ts/AGENTS.md` §오라클 경계) |

## 2. 기계 정본 목록 (산문보다 우선)

| 기계 파일 | 봉인 대상 | 드리프트 가드 |
|---|---|---|
| `ts/spec/lakatos-node-fsm.v0.json` | 직교 FSM 5머신 (judgment·standing·question·bundle·tree) | `ts/tests/unit/fsm-conform.test.ts` |
| `ts/spec/lakatos-node-fsm-traces.v0.json` | 21 추상 트레이스 (전 전이·전 가드-false 행사) | 〃 |
| `ts/spec/run-budget.v0.json` | 실행 예산 어휘(reject 12 · halt 5)·상수·cap 순서·합산식 | `ts/tests/unit/run-conform.test.ts` |
| `ts/spec/tool-surface.v0.json` | MCP 51도구 표면 (name·method·path·kind·capBytes) — Python 목록과 전수 일치 실측 | `ts/tests/unit/tool-surface.test.ts` |
| `docs/data/longinus_bindings.json` | Python 코어 def-line ↔ KG 바인딩 | `python -m lakatos.longinus audit` |

## 3. TS 도메인 지도 — 전부 순수 함수

의존은 아래로만: `contracts → domain → application → adapters → entrypoints` (depcruise 게이트).
domain 은 eslint 방화벽이 문법 수준에서 봉쇄: throw·Date·random·async·class·IO·zod 런타임 금지.
오류는 `_tag` 판별합 값, 닫힌 reason 어휘. 돈·토큰·시간은 정수. 상태 전이는 이벤트 소싱 reduce.

- **F 커널 (수명주기)** — `machines.ts`+`step.ts`+`guards.ts` (spec 실행기) → `node.ts` (apply = judge∘step, 측정주권: 이벤트에 verdict 필드 자체가 없음) · `receipts.ts` (canonical-bytes+sha256 CAS 사슬)
- **L 파생 (판정·보증)** — `judge.ts` (결정론 4치 판정, 마이크로 정수) · `derive.ts` (VAL L0~L3 읽기 시점 파생 — 저장하는 순간 SLSA 위반)
- **토큰 이코노미 (§5 기계화)** — `ledger.ts` (AI 토큰/컴퓨팅 이중 평면, 교차 오염 불가) · `budget.ts` (B1 선언·5캡) · `streak.ts` (B3) · `wait.ts` (B4) · `bound.ts` (유계 예방) · `emission.ts` (유계 탐지) · `run.ts` (실행 애그리게이트 — 흡수 정지, 날조 정지 이벤트 표현 불가)

**게이트웨이 층 (MCP 교체 에픽, 2026-08-11 완결)** — `domain/page.ts` (ToolPage 유일 성공 반환형 —
UTF-8 실바이트 cap·코드포인트 경계·정준 커서) · `application/gateway.ts` (fail-closed 기동, 정지 후
백엔드 선차단) · `application/assemblers.ts` (body 조립 11종) · `adapters/storehttp.ts` ·
`entrypoints/mcp.ts` (stdio 서버 — 캡은 env 전용, 도구 인자로 자기 예산 인상 불가).

시나리오 원장 (커밋 = "Scenario X GREEN" 단위): FSM-CONFORM · LEDGER-SPLIT · JUDGE-PURE · TREE-1 ·
RECEIPT-CAS · BOUND-EMIT · BUDGET-DECLARE · CAP-HALT · RED3-HALT · EMISSION-BOUND · WAIT-ONCE ·
RUN-LAWS · TOOL-PAGE · GATEWAY-CORE · STORE-HTTP · PAGE-BYTES · TOOL-SURFACE · ASSEMBLERS ·
MCP-STDIO — 전부 `pnpm verify` GREEN (unit 149 · property 19; 2026-08-11 1390430 격리 제3자 재검증
전 게이트 exit 0).

## 4. 토큰 폭식 문제 → 기계 게이트 (2026-08-11 결산)

진단 실측: MCP 도구 51개 전원이 무제한 통과층(성공 경로 truncation 0건) — `get_tree` 단일 응답 최대
733,838B(165노드, ≈18만 토큰), 108트리 중앙값 35KB, comment 입력 상한 부재. 폭식 사건(08-07~10):
Codex input 13.0B/일 → config 게이트 후 0.33B(40배 감소), 잔여 주범은 장수 세션 캐시리드(일 ~18억).
교훈 = B5: **산문으로만 존재하는 강제 조항은 아직 강제되지 않은 조항이다.**

| CLAUDE.md §5 조문 | 기계화 | 상태 |
|---|---|---|
| B1 예산 선언 · 초과=정지+보고(재시도 아님) | `budget.ts` + `run.ts` 흡수 정지 | ✅ ts 도메인 |
| B3 같은 게이트 3연속 같은 이유 RED = 정지 | `streak.ts` (+ red_without_reason fail-closed) | ✅ |
| B4 대기 ≠ 계산 (폴링 금지) | `wait.ts` duplicate_wait_poll 거부 | ✅ |
| 유계 출력 (canon: AI-facing 무제한 금지) | `bound.ts`+`emission.ts` 이중선 → **MCP 게이트웨이 상주** (51도구 전 응답 ToolPage 강제 + 실바이트 계량) | ✅ 게이트웨이 |
| B2 세션 수명 | 하네스 hook (델타워 b2_session_budget.py) | 하네스 몫 — 산문 유지 |
| 제3자 재검증 | 오케스트레이터 규율 (`replayRun` 결정론이 가능하게 함) | 운영 몫 — 산문 유지 |

Python 측 유계 선례 (이식 후보): fsck `findings[:500]`+truncated 정직 공시 · history `?limit=100` ·
paradigm `.limit(50)` · graph body `[:160]`.

## 5. 거버넌스 (읽는 순서)

1. `CLAUDE.md` — 이 repo 작업 규율 (단일 writer · pathspec 커밋 · RED-first 이중가드 · §3 검증 게이트 · §5 실행 예산)
2. `ts/AGENTS.md` — TS 레인 계약 (`pnpm verify` = DONE 의 유일한 정의)
3. SYMPOSIUM `THEORY/함수형프로그래밍/AGENT_PARADIGM_CONTRACT_v1.md` — §5 B1~B5 원본 (repo 밖 정본)
4. canon 프로그램 5종 — 설계 제약 원장 (요약: `ts/docs/GROUNDING_2026-08-11.md`, 제약 47건):
   C1ExternalVerifier(봉인하라, 포인터는 증거가 아니다) · GitAbsorption(G1~G10: 부정직이 저장층에서
   표현 불가) · JudgeProprioception(판사 자신의 콘텐츠 주소화) · MeasurementSovereignty(재현확인 ≠
   값소유, 부재≠반증) · StandardHarnessMcpState(AI-facing 유계 + 인프라 8불변식)

## 6. 파편 안내 (자주 찾는 것)

- 판정·보증이 왜 이렇게 나왔나 → `lakatos/verdicts.py` (VAL 사다리 정본) · `ts/src/domain/derive.ts` (v0 이식)
- :55170 재시작 → `scripts/dev_server_restart.sh` 만 (CLAUDE.md §4 — 손 재시작 금지)
- 엔진 거동 증명 → `ooptdd_receipts/<ID>/` + `tests/test_ooptdd_receipts_all.py` (자동 발견·전수 실행)
- 진보 주장 채점 → `examples/*_programme.py` 하네스의 judge() 만 (손입력 verdict 금지)
- 결정 기록 → `docs/ADR-*.md` 4건 (그 외 docs/ 38건은 프로토콜·핸드오프·감사 기록)

## 7. 다음 단계 (ts 로드맵)

1. **운용 전환 (사용자 결정)**: `~/.claude.json` 에 `lakatotree-ts` MCP 를 병렬 이름으로 섀도 등록 →
   무발산 확인 → 이름 스왑 (기존 Python MCP 는 레퍼런스로 잔존)
2. 어댑터: PG 이벤트로그(he-sha 멱등 투영) · CAS 증거 번들 스토어 (`ts/docs/FSM_DESIGN_v0.md` §4·5)
3. 오라클 파리티 게이트: 동결 코퍼스 + Python↔TS conformance (승격 전까지 파리티 주장 금지)
4. CLAUDE.md §5 산문 4칙 축약 (B5 규칙 — 기계 게이트가 정본이 된 조항의 산문 제거, 사용자 승인 사항)
