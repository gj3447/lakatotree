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

## 갱신 (AG3/R-SOV V1 값소유 착륙 — 한계선 한 칸 이동, 2026-07-03)

척추(결정 5)대로 AG3 가 착륙하며 위 맥락의 두 한계선이 옮겨졌다:

- **measurement_grade 봉인 완료.** `RECEIPT_FIELDS` 는 이제 **13필드**(measurement_grade 추가,
  lakatos/verdicts.py) — 서버-재유도값(`server_regenerated`)과 client-운반값(`client_asserted`)이
  *다른* receipt_sha 를 든다. 진짜검증≠위조가 형식으로 갈린다.
- **값소유 치환 코드 착륙(SCOPED).** `server.contexts.tree.judgement_policy.resolve_measurement`
  가 submit 시 서버 replay 가 `verified ∧ regenerated 존재`인 부분집합에서만 `v.regenerated` 를
  SSOT `metric_value` 로 치환한다(SCOPED — 외부/반증값[regenerated=None] 파괴 금지). 치환값은 client
  와 tol(1e-9) 내라 verdict 는 불변, 바뀌는 건 값의 *출처*다(서버가 자기 bits 소유).
- **ordering 역전 교정(AG6/V4 선행분 흡수).** 신규노드는 submit 시점 `e.metric_value=None` 이라
  persisted 조회 replay(`_producer_replay_for_node`)가 항상 not_attempted 로 죽었다. AG3 는
  `_producer_replay_submit` 로 *들어온*(incoming) script/result_path/metric_value 를 직접 replay 해
  seal 전에 소유한다 — replay_status·값소유가 신규노드에서 라이브가 됐다.

**여전한 한계선(새 tripwire 대상):** `LAKATOS_REPLAY_EXEC` 기본 **OFF** 라 `_producer_replay_submit`
는 None 을 돌려주고 라이브 grade 는 여전히 `client_asserted` — **값소유는 코드완료·라이브미발효**
(dead-σ)다. `return v.verified`(canonical 승격 floor 의 bool replay)와 fold 포인터 워크는 불변.
라이브 값소유(σ0→1)는 **GO1**(exec 기본-ON, AG2 RCE 봉합 선행+도그푸드 실증 후 user GO) 대기.

## 갱신 (AG4/R-SOV V2 재현성 천장, 2026-07-03)

anchored tier 게이트(`assurance.GATE_REPRODUCIBILITY_CEILING`, submit_test_result×anchored)를 무장하고
`judgement_policy.apply_verdict_demotes` 가 **재현성이 구조적으로 반증**(`_reproducible_for_node` is
**False**: lineage dangling / 비-source root)된 progressive 노드를 **partial(reproducibility_refuted)로
천장**한다 — 하드 409 아님(값 보존), CANONICAL 은 못 열되. ★핵심 dead-σ 규율 **불가 None ≠ 불일치
False**: 재현성이 *불가*(None: result_path 없음/sha 미검증=증명불가)면 **천장 안 함**(부재≠반증) — 현
라이브 노드는 전부 result_path='' → None → **무회귀**(1582 green). 천장≠거부. 이 천장은 AG3 값소유가
소유하지 *못한* 값(외부/비재현)의 CANONICAL 진입을 구조적으로 막아 측정 정직 표면을 넓힌다.

## 갱신 (AG5/R-SOV V3 attested 측정등급, 2026-07-03)

비평 재프레이밍(신원 open-write=co-fundamental)에 따라 measurement_grade 를 **3단 provenance 사다리**로
정직화: `server_regenerated`(서버 재유도) > **`attested`**(allow-list 신원 서명) > `client_asserted`
(무서명). `judgement_policy.resolve_measurement(attested=)` 이 유효 write-cert(G10 인프라의
`attested_by_did`)가 붙은 값을 `attested` 로 봉인한다 — 값은 여전히 client 지만 익명이 아니라 신원에
묶여(비부인) receipt_sha 에 인코딩된다. `server_regenerated` 가 `attested` 를 이긴다(재유도 > 서명).
★dead-σ 안전: `attested` 는 서명이 실재할 때만 — 무-attestor 트리(대다수)는 그대로 `client_asserted`
(**무회귀 1586 green**).

**미착륙(q-rsov5 OPEN, FE5 선행):** IDENT 의 *enforcement* 절반 — 비가역 verb(carve/CANONICAL승격/
delete) 서명 *강제* + cert `verb` 판별자(sign-X-execute-Y 봉인)는 미착륙이다. `set_verdict` 는 아직
cert 를 받지 않고, verb-게이팅은 `FE5 auth_posture` 관측화(open-but-observable, 부팅거부 아님)를 선행으로
둔다. 본 슬라이스는 attested *grade* 사다리만 닫는다(q-rsov5a). YAGNI: cert `verb` 필드는 소비 verb
(canonical 게이트)가 착륙할 때 함께 — 소비자 없는 서명-blob 확장은 하지 않는다.

## 갱신 (FE5 auth_posture 관측화 — AG5-IDENT 선행, 2026-07-03)

비평 #1(무인증 open-write=co-fundamental A-blocker)이 지목한 *보이지 않던* 자세를 관측화했다.
`server/auth_posture.py`(순수·무 DB)가 쓰기 인증 자세를 **3값 사다리**로 분류: `token_required`
(LAKATOS_API_TOKEN 설정) > `irreversible_attested`(AG5-IDENT 착륙 시 live, 현재 dead 슬롯) > `open`
(무토큰=무인증 mutating, 현 기본). `/version` 이 `auth_posture` 를 공시하고(G2 stale 공시와 동일 표면),
`_lifespan` 이 open 부팅에 loud WARN 한다. ★확정결정 **open-but-observable**: 무토큰 부팅을 *거부하지
않되*(dead-σ: 키 없는 배포를 409/부팅거부로 잠그지 않음) 관측가능하게 만든다. 이 관측화가 AG5-IDENT
(비가역 verb 서명강제)의 명시적 선행조건이다.

## 상태

ACCEPTED (2026-07-03, AG1 착륙 — ADR + 교정 3건 + 가드). **AG3/R-SOV V1 + AG4/R-SOV V2 착륙으로 갱신**
(2026-07-03: measurement_grade 봉인 + 값소유 치환 코드[dead-σ] + 재현성 천장[구조반증 False→partial,
불가 None 무회귀]). 가드: `tests/fix_harness/test_ag1_rsov0_doc_honesty_20260703.py` (채점기
`judges/ag1_rsov0_doc_honesty.py`, metric=잔존 과대표현 수 3→0; claim↔code tripwire 는 AG3 한계선으로
재조준). AG3 가드: `tests/fix_harness/test_ag3_rsov3_value_ownership_20260703.py`
(채점기 `judges/ag3_rsov3_value_ownership.py`). AG4 가드:
`tests/fix_harness/test_ag4_rsov4_reproducibility_ceiling_20260703.py`
(채점기 `judges/ag4_rsov4_reproducibility_ceiling.py`). AG5 가드:
`tests/fix_harness/test_ag5_rsov5_attested_grade_20260703.py`
(채점기 `judges/ag5_rsov5_attested_grade.py`).
