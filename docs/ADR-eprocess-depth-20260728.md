# ADR — e-process 심화 3건 + engine-rule floor 정책 (2026-07-28)

> 배경: S9 e-process 흡수(679b9c4)는 코어+challenger 병행까지 착지. PROM16
> (`prom16-lakatotree-advancement-20260728`) 정찰이 남긴 심화 3건과 floor 정책을 여기서 결정.

## D1. stack 4층 vote (eprocess_vote 추가) — **DEFER**

- 제안: `lakatos/programme/stack.py` votes 에 e-process 층 추가.
- 결정: **보류.** `STACK_QUORUM=2`(grounding) 의 "3층 중 2" 의미론이 "4층 중 2"로 바뀌는
  정족수 정책 변경이다. challenger 병행 출력(tree_metrics.eprocess)로 실트리 K=3 대비
  판정 일치율을 먼저 실측한 뒤(수 주 데이터), 일치/불일치 패턴을 근거로 재론한다.
- 재론 트리거: watchdog 시계열에 eprocess/laudan 신호 불일치 사례 ≥5건 누적 시.

## D2. calibration 경로 receipt-gate 비대칭 — **FIX (본 커밋)**

- 실측: `programme_service.calibration` 은 KG raw `novel_confirmed` 를 읽어 무영수증
  self-report 결과가 판관 보정 측정을 오염시켰고, `ORDER BY` 부재로 반환 순서도 비결정.
- 수리: FORCEFUL(scripted/engine) 판정 노드만 + `ORDER BY e.judged_at, e.tag` 결정론 정렬
  + 응답 note 에 게이트 명시. (tree_metrics 경로는 neutralize 가 이미 게이트 — 이 수리로
  두 경로의 의미론이 정렬된다.)

## D3. 판관 credence wealth ledger — **DEFER**

- 제안: 판관 credence 예보를 betting wealth 로 채점(e-process 를 forecaster 평가로 확장).
- 결정: **보류.** D2 수리로 정화된 (pred_credence, outcome) 스트림이 선행 데이터 요건.
  ECE(0.2211 과신 실측)의 표시-only 상태는 유지 — 강제 게이트화는 표본 확대 후.

## D4. engine_rule_floor entries 정책 — **빈 배열 유지 (최엄격)**

- 질문: 구 판관 sha(pre-PR#15)를 floor 에 등재해 기존 노드의 L3 읽기 자격을 회복할 것인가.
- 결정: **등재하지 않는다.** PR#15(lx3-remediation)는 replay-authority 의 실보안 수정을
  포함 — 그 수정 이전 판관을 "오늘도 신뢰"로 선언하는 것은 부정직하다. 기존 노드는 L2 캡이
  옳은 상태이며, L3 가 필요한 주장은 현행 엔진 재제출(run the receipt)로 회복한다.
  등재는 향후에도 *알려진 결함 없는* 판관 sha 에 한해 사람 검토 커밋으로만.
- 과거 실증 기록: `scripts/probe_l3_readpath_live.py`는 T1 예측 앵커와 서버 시각을 T2처럼
  사용하던 당시 경로에서 읽기 표면 L3를 관측했다. 현재 계약에서는 그 결과를 L3 증거로
  인정하지 않는다. 서명되고 verdict receipt에 묶인 독립 T2 앵커가 아직 없으므로 submit과
  영구 읽기 표면 모두 `temporal_witness=False`로 fail-closed하며 최대 L2다. L3 회복은 현행
  엔진 재제출만으로 충분하지 않고, T1≤T2를 검증할 receipt-bound T2 구현과 새 실증이 필요하다.

# KG: plan-lktadv-p4-eprocess-s9-20260728 / plan-lktadv-p3-val-l3-readpath-20260728
