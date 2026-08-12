# lakatotree-ts FSM 설계 v0 — 결정 기록

> 기계 정본: [`../spec/lakatos-node-fsm.v0.json`](../spec/lakatos-node-fsm.v0.json) (fsm-spec/v1,
> validate_fsm OK) · 트레이스: [`../spec/lakatos-node-fsm-traces.v0.json`](../spec/lakatos-node-fsm-traces.v0.json)
> (21 케이스 OK — 전 전이·전 가드-false·전 머신 invalid-event 행사). 산문은 설명 뷰이며 충돌 시 기계 파일이 이긴다.
> 근거: grounding 연구 wf_4dc04615 (영속층/정전 5프로그램/보증 사다리/토폴로지 4-리더).

## 1. 형식 선택 — 왜 이 모양인가

- **FSM이 정직한 최소 모델인 범위**: 저장되는 수명주기 — 금지 전이가 실재한다 (사전등록 없는 판정,
  소급 질문 폐쇄, 저자 자가판정, terminal 후 이벤트). 이벤트 소싱 재생과 정확히 일치.
- **직교 머신 5개** (단일 곱 머신 아님): judgment(3) × standing(3) × question(2) × bundle(3) × tree(2).
  판정 이력과 standing 포인터는 독립적으로 변한다 — 철회된 노드도 영수증 사슬은 온전하다.
  교차 조정은 어댑터 큐의 명시적 이벤트로만 (직접 타영역 전이 금지).
- **VAL(L0~L3)·인증은 FSM에서 의도적으로 제외** — 정본 규칙(verdicts.py:365-370): 보증 레벨은
  저장 라벨이 아니라 **읽기 시점 파생 판정**. 상태로 저장하는 순간 SLSA 규칙 위반.
  → FLR 배치: **F** = 이 파일의 전이. **L** = VAL·인증·standing 도출(봉인 필드 위 순수 파생,
  4치: 지지/반증/충돌/미지 — dead-σ: 부재≠반증). **R** = 프런티어·아웃박스·재검증 흐름.
- 영구 머신 3개(judgment/standing/question)는 final 없음이 정직하다: 연구 기록은 종결되지 않는다
  (재판정 CAS 승계·복권·재개방) — 삭제는 포인터 죽음뿐.

## 2. 권위 테이블 (run-fsm.v1 관례 계승)

| 이벤트 | actor_role | 가드 |
|---|---|---|
| PREDICTION_REGISTERED / RESULT_SUBMITTED / REJUDGE_SUBMITTED | author(에이전트) | is_author, supersedes_matches_head(CAS) |
| BUNDLE_SHA_VERIFIED | anchor_verifier(서버) | sha_matches |
| ENGINE_RULE_STALE / REFRESHED | engine_auditor(fsck) | is_engine_auditor |
| QUESTION_CLOSED | judgment_seam(엔진) | from_judgment_seam — 소급 폐쇄 봉쇄 |
| STANDING_RETRACTED / REINSTATED / TREE_ARCHIVED / QUESTION_REOPENED | human_owner | is_human_owner |

**측정주권이 스키마에 각인됨**: 어떤 이벤트에도 verdict 필드가 없다 — 저자는 측정(value+bundle_sha)을
제출하고 판정은 리듀서 안의 순수 judge가 도출한다. 위조 가능 지점 자체가 표현 불가.

## 3. 안전 속성 (기계 파일 §safety_properties, 트레이스로 행사됨)

author-cannot-judge · no-verdict-without-prereg · prereg-immutable(C1 해시-인과 봉인) ·
cas-only-pointer-moves(G1 필수 CAS) · no-retro-question-closure(problem-balance seam) ·
bundle-fail-closed(seal-don't-point) · assurance-not-stored · retraction-preserves-records(Eilu-va-Eilu).

## 4. 저장 아키텍처 계승 (grounding 확정 사실)

기존 엔진의 3-스토어 모델을 TS 어댑터로 계승한다: **Neo4j=진실(KG 그래프·영수증 사슬·리스)** /
**PG=append-only 감사 투영(history 이벤트로그, he-sha 안정 ID, 트랜잭셔널 아웃박스, ON CONFLICT 멱등)** /
**Mongo=자유형 산출물**. 추가: **콘텐츠 주소 증거 번들 스토어**(evidence-bundle 머신이 그 수명주기) —
경로 앵커의 호스트 종속을 sha 주소로 대체(이번 세션 실측 결함 ②⑥의 봉합). 단일 writer 펜스
(advisory lock + RuntimeWriterLease CAS)와 정본 캐넌 제약(불변 영수증·필수 CAS 포인터·버전드 정준
인코딩·레코드별 재도출 검증·정직 경로 최저가)은 전부 상속 —
[`GROUNDING_2026-08-11.md`](GROUNDING_2026-08-11.md)의 제약 47건이 요구사항 원장.

## 5. 완료 기록과 다음 경계

FSM-CONFORM, LEDGER-SPLIT, JUDGE-PURE 시나리오는 구현·검증이 끝난 완료 이력이다. PG 이벤트로그와
번들 CAS 어댑터도 구현됐지만 런타임 composition root에는 아직 배선되지 않았다. 이 결정 기록은
별도 작업 큐를 소유하지 않으며 후속 순서는 [`MAP.md` §7](../../MAP.md#7-다음-단계-ts-로드맵)에서 관리한다.
