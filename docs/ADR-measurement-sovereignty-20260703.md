# ADR: 재현확인(reproduction-confirmation) ≠ 값소유(value-ownership) — 측정 주장의 어휘 한계선 (2026-07-03, 측정주권 PROM AG1/R-SOV-0)

## 맥락

독립 3차원 평가(docs/lakatotree-evaluation-20260703.md, A-)와 측정주권 PROM(2026-07-03)이 같은
지점에 수렴했다: **판결-도출의 위조불가(참)와 측정값의 위조불가(거짓)가 문서에서 혼용된다.**
코드 실측(정찰 wf_48a54c6b, 앵커는 모두 실파일 검증):

- **replay 는 값을 소유하지 않는다.** `_producer_replay_for_node` 는 재유도값(`v.regenerated`)을
  서버 경계에서 폐기하고 `return v.verified` — bool 하나만 남긴다(server/app.py). 대조 대상
  recorded metric 은 이미 영속된 `e.metric_value` 를 되읽은 값이다. 즉 replay 는 "스크립트가
  그 값을 냈나"의 **재현확인**이지, 서버가 값을 재유도해 SSOT 로 삼는 **값소유**가 아니다.
- **exec 게이트는 기본 OFF, 프로세스-전역.** `LAKATOS_REPLAY_EXEC` 미설정이면 스크립트를 실행하지
  않고 None(증명불가·비차단) — OFF 배포에서 replay 는 dead path 이고 판결에 남는 유일한 흔적은
  3값 `replay_status`(not_attempted/verified/mismatch)다.
- **영수증은 client float 를 봉인·운반한다.** `:VerdictReceipt` 가 봉인하는 `RECEIPT_FIELDS` 는
  12필드(lakatos/verdicts.py)이고 **measurement_grade 류 출처등급 필드가 없다** — 진짜 외부검증
  값과 위조 float 가 같은 형식의 영수증을 받는다. `metric_value` 의 출처는 HTTP 입력
  `TestResultIn.metric_value`(client float)이며 서버가 재계산하는 경로는 없다.
- **fold 는 포인터 워크다.** `fold_receipt_chain` 은 head→prev 도달성/사이클만 검사하고 내용해시를
  재계산하지 않는다(내용+`receipt_sha` 를 함께 고친 변조는 fold 단독으로 미검출).
- **FF1 서버앵커는 sha 재유도이지 값 재계산이 아니다.** `novel_script` 앵커는 스크립트 *본문*의
  sha256 을 서버가 재유도하는 것 — `novel_measured` float 자체는 여전히 client 제공이다.

## 결정

1. **어휘를 잠근다.** *재현확인(reproduction-confirmation)* = 서버가 "그 스크립트가 그 값을
   재현했다"를 확인(replay verified bool; 게이트 ON+성공 시에만). *값소유(value-ownership)* =
   서버가 값을 재유도·봉인해 SSOT 로 소유(AG3, 미착륙). 정본 문서·docstring 은 이 구분 없이
   측정값 쪽 위조불가를 주장할 수 없다.
2. **허용 주장 한계선.** ① 판결-도출 위조불가(judge 순수함수·Lean `Rung.derived`) = 말해도 된다.
   ② 측정값 위조불가/외부성("external measurement", "위조는 닫힌다", "거짓말할 수 없다") =
   **단서 없는 현재시제 금지** — 각주·괄호로 시제(기본 설정에서/착륙 후)와 갭(client float 운반,
   measurement_grade 부재)을 명시해야 한다. ③ 미구현 집행(G-Web 재fetch 등)을 현재시제로 서술
   금지.
3. **확정 과대표현 3건을 교정한다**(2026-07-03 정찰): TOUCH_THE_SKY 재fetch 현재시제(→미구현
   명시), TOUCH_THE_SKY "거짓말할 수 없는"(→측정층 한계 각주 [^2]), README 헤드라인 "an external
   measurement"(→"a measurement lodged against it" + reproduction-confirmation, not
   value-ownership 단서). borderline 9건(README 36·53, TTS 18·100·292·309, PIDNA 17,
   verdicts.py 221 주석, UI_AND_HUMAN_LOOP 49)은 트리 coverage backlog — 전수성 주장 안 함.
4. **기계 가드로 잠근다.** `tests/fix_harness/test_ag1_rsov0_doc_honesty_20260703.py` 가
   ① 과대표현 3건의 부활(defect), ② 이 ADR 의 실재와 필수 어휘(mechanism), ③ **claim↔code
   1:1 tripwire** — ADR 이 서술한 현 한계선(RECEIPT_FIELDS 12필드에 measurement_grade 부재,
   `return v.verified`, fold 포인터 워크)이 코드에 실재함을 import/실행으로 검증한다.
   AG3/AG6 가 착륙해 코드가 바뀌면 tripwire 가 RED — **이 ADR 의 개정이 기계적으로 강제된다.**
5. **이 ADR 은 현상 동결이 아니다.** 척추(AG2 exec 경로 RCE 봉합 → DE1 submit 분해 → AG3 값소유
   keystone → AG4 재현성 분류 → AG5 attested grade+신원 → AG6 값무결 fsck+ordering → AG7 legacy
   무장해제)가 한계선을 옮길 때마다 결정 1~3 의 어휘 표가 갱신된다. 채점은
   `LakatosTree_MeasurementSovereignty_20260703` 트리.

## 보류 (user GO 대기)

- GO1 `LAKATOS_REPLAY_EXEC` 기본-ON: AG2(RCE 봉합) 선행 절대 + 도그푸드 σ0→1 실증 후 GO.
  per-tier canary 불가(프로세스-전역) — 격리는 별 프로세스/ephemeral 서버로만.
- GO2 legacy 라이브 스탬프 + resolve_tier flip / GO4 token_required posture(무인증 open-write
  37그루는 co-fundamental A-blocker — FE5 관측화가 선행).

## 상태

ACCEPTED (2026-07-03, AG1 착륙 — ADR + 교정 3건 + 가드). 가드:
`tests/fix_harness/test_ag1_rsov0_doc_honesty_20260703.py` (채점기
`judges/ag1_rsov0_doc_honesty.py`, metric=잔존 과대표현 수 3→0).
