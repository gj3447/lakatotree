# LakatoTree 전체 지도 (MAP)

> 파편화된 정본·문서·코드의 단일 진입점이자 **유일한 현행 로드맵**. 산문은 설명 뷰다 — 충돌 시 기계 파일(spec·스키마·테스트)이
> 이긴다. 최종 갱신 2026-08-14 (eval-first freeze + frozen-evidence audit 분리). 갱신 규칙: 층 구조나 정본 위치가 바뀌는 커밋만
> 이 파일을 손댄다 (일상 슬라이스는 손대지 않음 — 지도가 또 하나의 파편이 되지 않게).

## 0. 한 문장

LakatoTree = 연구 프로그램의 진보 주장을 **사전등록 → 측정 → 결정론 judge 판정 → 불변 영수증**으로만
인정하는 연구 원장 엔진 — 에이전트가 자기 점수를 매기는 경로가 구조적으로 표현 불가능해야 한다.

## 1. 층 구조

| 층 | 위치 | 지위 |
|---|---|---|
| **TypeScript 재개발 레인** | `ts/` | **PROPOSED**. 함수형 코어·유계 MCP 게이트웨이·Effect I/O 경계. `pnpm verify`가 이 레인의 DONE 게이트 |
| Python LTS 구현·오라클 | `lakatos/` `server/` 루트 `tests/` | 현재 배포·비교 기준. 신규 기능 확장은 동결하고 치명 결함 수리·TS parity 판정만 수행 |
| 외부 재검증기 | `c1verify/` | 엔진 코드 0 import 로 Certificate 재검증 (import-linter + clean-venv CI 로 구축 사실 증명) |
| 이론 모델 | `formal/` (Lean4) · `THEORY.md` | judge 커널의 이론 검증 — Python 바이너리·측정의 참을 검증하지 않음 (정직 범위) |

## 2. 기계 정본 목록 (산문보다 우선)

| 기계 파일 | 봉인 대상 | 드리프트 가드 |
|---|---|---|
| `ts/spec/lakatos-node-fsm.v0.json` | 직교 FSM 5머신 (judgment·standing·question·bundle·tree) | `ts/tests/unit/fsm-conform.test.ts` |
| `ts/spec/lakatos-node-fsm-traces.v0.json` | 21 추상 트레이스 (전 전이·전 가드-false 행사) | 〃 |
| `ts/spec/run-budget.v0.json` | 실행 예산 어휘(reject 12 · halt 5)·상수·cap 순서·합산식 | `ts/tests/unit/run-conform.test.ts` |
| `ts/spec/tool-surface.v0.json` | MCP 도구 표면 (name·method·path·kind·capBytes) | `ts/tests/unit/tool-surface.test.ts` |
| `ts/sql/ts_history.v0.sql` | PG append-only 감사 투영 스키마 (he-sha 멱등 키, ck/uq 제약) | `ts/tests/unit/pg-eventlog-int.test.ts` (DSN 시) |
| `docs/data/longinus_bindings.json` | 레거시 Python 코어 def-line ↔ KG 바인딩 | Python 오라클 변경 시에만 `python -m lakatos.longinus audit` |

## 3. TS 도메인 지도 — 전부 순수 함수

의존은 아래로만: `contracts → domain → application → adapters → entrypoints` (depcruise 게이트).
domain 은 eslint 방화벽이 문법 수준에서 봉쇄: throw·Date·random·async·class·IO·zod 런타임 금지.
오류는 `_tag` 판별합 값, 닫힌 reason 어휘. 돈·토큰·시간은 정수. 상태 전이는 이벤트 소싱 reduce.

- **F 커널 (수명주기)** — `machines.ts`+`step.ts`+`guards.ts` (spec 실행기) → `node.ts` (apply = judge∘step, 측정주권: 이벤트에 verdict 필드 자체가 없음) · `receipts.ts` (canonical-bytes+sha256 CAS 사슬)
- **L 파생 (판정·보증)** — `judge.ts` (결정론 4치 판정, 마이크로 정수) · `derive.ts` (VAL L0~L3 읽기 시점 파생 — 저장하는 순간 SLSA 위반)
- **토큰 이코노미 (§5 기계화)** — `ledger.ts` (AI 토큰/컴퓨팅 이중 평면, 교차 오염 불가) · `budget.ts` (B1 선언·5캡) · `streak.ts` (B3) · `wait.ts` (B4) · `bound.ts` (유계 예방) · `emission.ts` (유계 탐지) · `run.ts` (실행 애그리게이트 — 흡수 정지, 날조 정지 이벤트 표현 불가)

**게이트웨이 층** — `domain/page.ts` (ToolPage 유일 성공 반환형 —
UTF-8 실바이트 cap·코드포인트 경계·정준 커서) · `application/gateway.ts` (fail-closed 기동, 정지 후
백엔드 선차단) · `application/assemblers.ts` · `application/store.ts` (Effect StoreClient service) ·
`adapters/storehttp.ts` (Effect Layer, typed unknown transport/timeout, 자동 retry 없음) ·
`entrypoints/mcp.ts` (단일 ManagedRuntime, bounded admission, stdio composition root).

`pnpm verify`는 타입·lint·동작/property test 뒤 JavaScript를 빌드하고 `--no-strip-types` 실제 HTTP
tool-call smoke를 실행한다. `pnpm deploy:mcp <commit>`은 dirty 작업트리가 아니라 해당 Git 커밋을
추출해 production dependency만 설치한 versioned read-only artifact를 활성화한다. MCP는 기본
read-only이고 인증된 full posture에서 write/ops 도구를 노출한다. HTTP store는 아직 Python
backend이므로 전체 이식·파리티·production 승격을 주장하지 않는다.

**기타 어댑터** — `adapters/casstore.ts` (파일시스템 증거 번들 CAS:
이름=내용·write-once·읽기 재해시) · `adapters/pgeventlog.ts` (PG append-only 투영: he-sha 멱등
ON CONFLICT, 유계 readSince, UPDATE/DELETE 문 부재) · `domain/eventlog.ts` (he-sha·페이로드
정준화). 이 구현들은 아직 MCP composition root에 배선되지 않았다.

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
| 유계 출력 (canon: AI-facing 무제한 금지) | `bound.ts`+`emission.ts` 이중선 → **MCP 게이트웨이 상주** (도구 응답 ToolPage 강제 + 실바이트 계량) | ✅ 게이트웨이 |
| B2 세션 수명 | 하네스 hook (델타워 b2_session_budget.py) | 하네스 몫 — 산문 유지 |
| 제3자 재검증 | 오케스트레이터 규율 (`replayRun` 결정론이 가능하게 함) | 운영 몫 — 산문 유지 |

Python 측 유계 선례 (이식 후보): fsck `findings[:500]`+truncated 정직 공시 · history `?limit=100` ·
paradigm `.limit(50)` · graph body `[:160]`.

## 5. 거버넌스 (읽는 순서)

1. `MAP.md` — 유일한 현행 인덱스·로드맵
2. `CLAUDE.md` — 공통 작업 규율 (단일 writer · pathspec 커밋 · 경로별 검증 · 실행 예산)
3. `ts/AGENTS.md` — TS 계약 (`pnpm verify` = DONE 의 유일한 정의)
4. SYMPOSIUM `THEORY/함수형프로그래밍/AGENT_PARADIGM_CONTRACT_v1.md` — 실행 예산 원본 (repo 밖 정본)
5. canon 프로그램 5종 — 설계 제약 원장 (요약: `ts/docs/GROUNDING_2026-08-11.md`, 제약 47건):
   C1ExternalVerifier(봉인하라, 포인터는 증거가 아니다) · GitAbsorption(G1~G10: 부정직이 저장층에서
   표현 불가) · JudgeProprioception(판사 자신의 콘텐츠 주소화) · MeasurementSovereignty(재현확인 ≠
   값소유, 부재≠반증) · StandardHarnessMcpState(AI-facing 유계 + 인프라 8불변식)

## 6. 파편 안내 (자주 찾는 것)

- 판정·보증이 왜 이렇게 나왔나 → `ts/src/domain/derive.ts` (TS 레인) · `lakatos/verdicts.py` (Python 구현·비교 오라클)
- :55170 재시작 → `scripts/dev_server_restart.sh` 만 (CLAUDE.md §4 — 손 재시작 금지)
- 동결 역사 영수증 감사 → `ooptdd_receipts/<ID>/` + `.github/workflows/frozen-evidence-audit.yml`
  (주간·수동 checkout-only 전수 실행; 외부 HSWM source binding은 별도 cross-repo 감사,
  일상 제품 게이트와 분리)
- 진보 주장 채점 → `examples/*_programme.py` 하네스의 judge() 만 (손입력 verdict 금지)
- 결정 기록 → `docs/ADR-*.md` (그 외 문서는 프로토콜·핸드오프·감사 기록)

### 문서 지위

| 묶음 | 지위 |
|---|---|
| `MAP.md` §7 | 유일한 현행 작업 순서 |
| `README.md` · `CLAUDE.md` · `CONTRIBUTING.md` · `ts/AGENTS.md` | 진입점·작업 규율. 로드맵을 복제하지 않음 |
| `ts/spec/*.json` · `docs/lakato-evidence-record-v1.md` | 언어 중립 기계/포맷 정본 |
| `ts/docs/GROUNDING_2026-08-11.md` · `ts/docs/FSM_DESIGN_v0.md` · `docs/ADR-*.md` | 동결 근거·결정 기록. `Next` 큐를 소유하지 않음 |
| 날짜형 plan/audit/handoff 문서 | 역사적 증거. 문서 안의 `Current`·`Next`는 작성 당시 시제 |
| `docs/ENGINE_DEVELOPMENT_KNOWLEDGE.md` · `docs/EVIDENCE_RECORD.md` | 레거시 Python 어댑터 노트 |
| `server.json` | 기존 PyPI/Python MCP 레지스트리 설명자. TS 패키지 발행 전까지 로컬 TS MCP 정본이 아님 |

## 7. 다음 단계 (ts 로드맵)

1. **실사용 eval이 먼저**: 실제 작업 실패에서 뽑은 20–50개 clean-task corpus로 Python baseline과
   TS 레인을 비교한다. trace·receipt 수가 아니라 최종 DB/파일/판정 결과를 독립 grader가 채점한다.
   이 corpus 전에는 새 규칙·judge·receipt·FSM·MCP 도구를 만들지 않는다.
2. **핵심 workflow만 승격**: corpus가 실제로 요구하는 발견·기록·측정·판정·검증·복구의 5~8개
   outcome workflow만 TS composition root에 연결한다. 기존 51개 도구의 1:1 이식은 목표가 아니다.
   필요한 write capability는 숨기지 않고 해당 workflow 안에서 인증·승인·검증 경계로 제공한다.
3. **Effect 후속은 소비자 기준**: 선택된 workflow의 실제 composition root에 연결할 때만 PG pool/CAS
   수명을 scoped Layer로 옮긴다. 자동 write retry나 순수 domain의 Effect 전환은 하지 않는다.
4. **오라클 파리티와 동시 퇴역**: 동결 corpus와 실제 consumer parity가 green인 세로 슬라이스만
   Python 중복 구현과 겹치는 source/hash/string guard를 같은 패치에서 제거한다. 전환 전에는 전체
   동등성을 주장하지 않는다.
