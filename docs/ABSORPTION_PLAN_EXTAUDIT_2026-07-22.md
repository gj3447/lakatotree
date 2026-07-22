# EXTAUDIT 흡수 개발 플랜 — 하네스 표준 정합 + OSS 메커니즘 이식 (2026-07-22)

> 발단: 2026-07-22 3-방향 적대감사(판정엔진 코드 / 영수증 레이어 / 라이브 1,193노드 전수) → 7급소.
> 급소는 SelfDev 트리에 정식 등재됨: Dung doubt 7건(`crit-extaudit-20260722-*`) + frontier 질문 7건(`q-extaudit-*-20260722`).
> 하네스 4축 진단 판정: **"built-then-disarmed"** — Constrain 장치는 존재하나 기본값이 꺼져 있음.
> 기본 배포에서 실발동 게이트 = CAS 409 + GATE_NOVEL_ANCHOR + hard-core 구조보존 3개뿐.

## 원칙 (THEORY.md §7 준수)

**오픈소스는 adapter/메커니즘 포팅, hard core(`LakatosGate + critique + replayability`)는 내부 규칙.**
통째 의존 0 — 서명 경로 외부의존 0 결정(`q_signer_key_substrate`, write_cert.py)과 충돌하는 도입 금지.
클론 둥지: `SYMPOSIUM/GIT/lakatotree_absorption_20260722/` (in-toto / opentimestamps-client / slsa / dvc / rekor).

## 급소 → 흡수 매핑 (4 스펙 요약)

| 급소 | OSS | 이식 메커니즘 | 기각/보류 |
|---|---|---|---|
| #3 측정 재현 | **DVC** | ① `force_of_row` grade-gate: `client_asserted`+무replay → INCONCLUSIVE (라벨 아닌 등급이 힘 결정) ② replay 기본 ON (`LAKATOS_REPLAY_SANDBOXED=1` 선언 시 unset=ON — RCE 보안계약 유지) ③ `:MeasurementLock` v1 (cmd+deps서버해시+params+env_sha+outs 관측값 봉인, dvc.lock 전사) ④ lock_key run-cache (재검증 비용 노드당 1회) | DVC 코드 import 없음, 구조만 |
| #2 역할분리 | **in-toto** | ① owner-서명 research_layout ≠ functionary 키 (4-키 기하학) ② verb별 pubkeys + distinct-DID threshold (같은 DID 중복서명=1 계상, Sybil 봉쇄) ③ materials/products/byproducts/env 해시 = link 전사 (receipt v3, 후속) ④ discard-then-threshold fail-closed ⑤ layout expires. 첫 구멍: **register_prediction에 cert 훅 자체가 없음** | securesystemslib 의존 기각 (did:key 유지) |
| #1 시간증인 | **OTS + rekor** | ① 1차 = RFC3161 TSA 2-quorum (즉시·pinned cert 오프라인 재검증 — c1verify witness 모델 정합) ② 2차 = OTS 비동기 강화 (pending→비트코인 확정, outbox+크론) ③ **양끝 앵커**: anchor(pred_sha,T1)+anchor(verdict_sha,T2) → 서버 시계 무신뢰로 백데이트 봉쇄 ④ 앵커는 봉인 sha 밖 사이드카(`:TemporalAnchor`+`.tsr` 파일) — 순환 회피, 소급 강등 0 | rekor 통째 기각 (solo box 자기증인=독립성 0 + Go 5-서비스) |
| #5 등급 동봉 | **SLSA** | ① VAL L0-L3 read-time 순수 도출 (저장 금지 — 저장=자기신고) ② 표면 강제 `progressive@L2(replay_verified)`, bare verdict 방출 금지 가드 ③ L0 basis 세분(replay_refuted=양성반증 ≠ no_receipt=부재) ④ 기존 1,193노드 마이그레이션 0 (입력 필드 전부 기저장) | L3은 temporal witness 전까지 도달 불가 (정직) |
| #4 어휘 범주오류 | 내부 | 노드 verdict에서 programme 어휘 분리 → series/branch 레벨 `programme_status` (스키마 재설계, 게이트로 못 풂) | — |
| #6 해석 미봉인 | 내부 | `comment`/`note`를 RECEIPT_FIELDS 봉인에 포함 (v3 bump) — 사후 승리서사 변조 차단 | — |
| #7 hardcore 불사 | 내부 | `should_abandon()` 서버 배선 (현재 server/ 호출 0건) + abandon override 기록 (AGM `programme_shift_candidate` 패턴 모방) | 자동 잠금은 사용자 verdict 필요 (라카토스 철학상 논쟁적) |

## 슬라이스 로드맵 (Constrain 회복량/비용 순)

| # | 슬라이스 | 상태 |
|---|---|---|
| S1 | `force_of_row` grade-gate (DVC 변경점1) — 파일 1, 함수 1, 파급 전체 | **본 커밋** |
| S2 | replay 기본 ON (SANDBOXED 2단) + dev_server_restart.sh env + 문서 개정 (ag1 골든 동시) | 다음 |
| S3 | VAL 도출함수 + standing() 표면 배선 (SLSA 슬라이스1) | 다음 |
| S4 | comment/note 봉인 (receipt v3, RECEIPT_FIELDSET_LINEAGE 승계) | |
| S5 | should_abandon 서버 노출 + override 기록 | |
| S6 | role-aware cert allowlist (`lakatos/layout.py` + register_prediction cert 훅) | |
| S7 | RFC3161 temporal anchor (GATE_TEMPORAL_ANCHOR, openssl ts 로컬 픽스처) | |
| S8 | `:MeasurementLock` + run-cache / OTS 강화 / receipt v3 materials·products / VAL L3 개방 | |

각 슬라이스 = SelfDev 트리 사전등록(judge script sha) → RED 이중가드 → 구현 → 채점(judge()만) + ooptdd 영수증.
S1은 `q-extaudit-replay-default-on-20260722`의 (b)안을 닫는다.

## 스펙 상세 출처

4개 흡수 스펙 전문과 하네스 4축 진단 전문은 본 세션 산출물 — 요지는 위 표에 결정화, 근거 파일:라인은
각 스펙이 인용한 소스 repo(클론 둥지)와 lakatotree 코드에 있음. 재도출 가능(클론 sha 고정, shallow HEAD 2026-07-22).
