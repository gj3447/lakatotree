# 게이트 기본값 인벤토리 (Phase 0 산출물)

- 날짜: 2026-07-24
- 목적: "built-then-disarmed" 방지 — 모든 게이트의 기본값을 한 표로 공시하고, OFF의 정당성을 분류.
- 정책 기준: PEP 476 패턴(기본 ON + 건당 명시 opt-out), Saltzer & Schroeder fail-safe defaults, CISA secure-by-default(하드닝 필요 자체가 결함).
- drift 가드: `tests/test_gate_inventory.py` — 코드의 LAKATOS_* 플래그 전수가 이 문서에 등재됐는지 매 커밋 검사.

## A. 구조 게이트 (assurance tier 구동 — 신규 트리 기본 anchored = 기본 발동) ✅

| 게이트 | 위치 | 발동 조건 | 상태 |
|---|---|---|---|
| GATE_NOVEL_ANCHOR | `lakatos/assurance.py:32` | tier ≥ receipted | 기본 ON |
| GATE_WRITE_CERT | `lakatos/assurance.py` | tier anchored | 기본 ON |
| GATE_REPRODUCIBILITY_CEILING | `lakatos/assurance.py` | tier anchored | 기본 ON |
| GATE_REPLAY_FLOOR | `lakatos/assurance.py:58` | tier anchored | 기본 ON |
| hard-core 구조보존 (`allow_hard_core`) | AGM demote 경로 | 상시 | 기본 ON |
| CAS 409 (verdict 이중 덮어쓰기 차단) | judgement_service | 상시 | 기본 ON |

## B. env opt-in 게이트 (기본 OFF) — 판정 포함

| 플래그 | 기본값 | 하는 일 | 판정 |
|---|---|---|---|
| `LAKATOS_API_TOKEN` | 미설정 = **open(무인증)** | mutating 요청 Bearer 강제 (token_required > irreversible_attested > open 3값 사다리, `server/auth_posture.py`) | ⚠️ 의도적 절충(FE5 open-but-observable: 부팅 loud WARN + /version 공시 + open에서 파괴 verb 403 + loopback 외 bind fail-closed). 단 PROM(2026-07-24) 결론: **지금 flip 권고** — Jupyter 선례(자동생성 토큰으로 UX 비용 ~0), MLflow CVE-2026-2635("개발 도구 무인증"의 회수 사례). "외부 공개 전 flip"이 아니라 자동생성 기본값으로 open 자세 자체 소멸 권고 |
| `LAKATOS_REPLAY_EXEC` | **OFF** | producer 스크립트 재실행 활성 | ✅ 정당한 fail-closed (임의 코드 실행 = RCE 표면). 단 이것이 값소유 미착륙의 직접 원인 → Phase 1 L3에서 `LAKATOS_REPLAY_SANDBOXED` 선언 배포 한정으로 ON |
| `LAKATOS_REPLAY_SANDBOXED` | 미설정 | 샌드박스 배포 선언 시 EXEC 기본 ON 위임(GO1 flip 2단) | ✅ 정당 (명시 선언 게이트) |
| `LAKATOS_JUDGE_FRESHNESS_GATE` | **ON (2026-07-24 flip 완료)** — 명시적 거짓(`0`/`false`/`no`/`off`)만 opt-out | 판관 staleness/capability 감지(`server/engine_freshness.py:48-53`) | ✅ flip 완료(사용자 GO). 발화 시 progressive → `partial`(provisional_stale_engine) 강등 + CANONICAL 승격 409 — verdict-affecting 게이트. 발화 조건은 부팅 커밋≠디스크 HEAD(미재기동 감지, `version.py:142-152`, dirty worktree는 물발화). 참고: "비파괴 감지라 안전" 초기 판정은 오류로 정정됨(2026-07-24) |

## C. 설정 노브 (게이트 아님, 기본값 존재)

| 플래그 | 기본값 | 용도 |
|---|---|---|
| `LAKATOS_BIND_HOST` | 필수(fail-loud 검증, `auth_posture.py:67-98`) | 바인드 주소 + listener override 금지 |
| `LAKATOS_PG_HOST` / `LAKATOS_PG_PORT` / `LAKATOS_PG_USER` / `LAKATOS_PG_PASSWORD` / `LAKATOS_PG_DB` / `LAKATOS_PG_DSN` | localhost 등 | PG 백킹(lazy degrade, 선택) |
| `LAKATOS_MONGO_URI` | mongodb://localhost:27017 | Mongo 백킹 |
| `LAKATOS_RAW_ROOT` | repo 루트 | raw 산출물 루트(재현 해시 경계) |
| `LAKATOS_FSCK_SKIPLIST` | docs/data/fsck_skiplist.json | skiplist 경로 오버라이드 |
| `LAKATOS_ENGINE_RULE_FLOOR` | docs/data/engine_rule_floor.json | floor 파일 오버라이드 |
| `LAKATOS_SCRIPT_ROOTS` | 빈 문자열 | replay 허용 스크립트 루트 allowlist |
| `LAKATOS_REPLAY_AS_MB` / `LAKATOS_REPLAY_FSIZE_MB` / `LAKATOS_REPLAY_CPU_S` | 2048/512/300 | replay rlimit 상한 |
| `LAKATOS_ANCHOR_NEO4J_URI` / `LAKATOS_ANCHOR_NEO4J_USER` / `LAKATOS_ANCHOR_NEO4J_PASSWORD` | bolt://localhost:7687 / neo4j / (로컬) | OTS 일일 앵커 KG 접속 (`scripts/ots_daily_anchor.py`) |
| `LAKATOS_ANCHOR_CYPHER_SHELL` | cypher-shell | OTS 앵커용 cypher-shell 경로 오버라이드 |
| `LAKATOS_ANCHOR_OUTBOX` | docs/data/ots_anchors | OTS 앵커 사이드카 outbox 디렉토리 |
| `LAKATOS_ANCHOR_CALENDARS` | a.pool,b.pool.opentimestamps.org | OTS 캘린더 풀 CSV (2-풀 정족) |
| `LAKATOS_REPLAY_CACHE_ROOT` | `$XDG_STATE_HOME/lakatotree/replay-artifacts/v1` (기본 `~/.local/state/...`) | replay 불변 아티팩트 스냅샷 캐시 루트 (PR#15 lx3-remediation, `lakatos/replay_artifacts.py:22-29`) |

## D. 테스트 티어 플래그 (운영 무관)

`LAKATOS_IT`(통합 티어), `LAKATOS_KG_LIVE`(라이브 KG), `LAKATOS_TEST_CID`, `LAKATOS_SERVER_LOG`, `LAKATOS_SERVER_ENV`, `LAKATOS_GIT_SRC`, `LAKATOS_PYTHON`, `LAKATOS_ENV_FILE`, `LAKATOS_SERVER`(examples 서버 URL).

참고: `LAKATOS_PRODUCER`, `LAKATOS_LOCATIONS`는 env가 아니라 모듈 상수(`lakatos/io/adapters.py`, `lakatos/engine.py`)라 인벤토리 대상 밖.

## E. 코드 구조 게이트 (env 없음) — 미발동 잔여

| 게이트 | 위치 | 상태 |
|---|---|---|
| writer SCRIPTED_VERDICTS 화이트리스트 | `server/contexts/tree/writer.py:68-74` (`_reject_scored`) | ✅ **이미 봉합됨**(prom-honesty/1, 적대감사 2026-06-20/21) — add_node:105 + bulk:282 모두 차단, 어휘=scripted ∪ engine ∪ PROGRESS(CANONICAL 포함), 구조/행정 어휘만 노드 작성 허용. 영수증 `tests/fix_harness/test_git_absorption_g1_verdict_overwrite.py`. ※초기 인벤토리의 "미폐쇄" 판정은 stale 문서(OPS handoff 06-20) 기반 오류로 2026-07-24 정정 |
| `should_abandon()` 서버 배선 | EXTAUDIT #7 | ❌ 호출 0 — 자동 잠금 없음(인간 verdict 필요, 라카토스 철학상 논쟁적 — 재정의 대상) |
| `PredictionLocked` / `check_registration` | `judge.py` | ❌ dead code (M6) — 사전등록 잠금 미발동 |

## 요약 판정

- 기본 배포 실발동 게이트: **A 표 전부(6종)** — EXTAUDIT의 "3개"보다 늘어난 것은 tier 기본값(anchored) 덕.
- 설계 결정 필요 1건: auth — 아래 PROM 결론(2026-07-24): **지금 Jupyter 방식 flip 권고**(자동생성 토큰 영속 저장). 상세는 대화 로그/PROM 노트 참조.
- flip 완료 2건: ① `LAKATOS_JUDGE_FRESHNESS_GATE` 기본 ON(2026-07-24, 사용자 GO) ② writer verdict 게이트 — 신규 작업 아닌 기존 봉합(prom-honesty/1) 확인으로 종결.
- 정당한 OFF 2건: REPLAY_EXEC(RCE 회피), REPLAY_SANDBOXED(선언 게이트).
