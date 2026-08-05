# 외부 리뷰 — LakatoTree (2026-07-24)

> 리뷰어: 외부 평가자 (Claude, 사용자 의뢰). 방법: **실제 연구 세션에서 MCP를 하루 종일
> 사용하며 발견한 엔진 거동을 receipts로 기록**(이 프로젝트 자신의 "receipts, not claims"
> 독트린을 리뷰에 적용). 대상 = 실행 중 백엔드(:55170) + MCP verbs + `longinus_audit`.
> 결론 한 줄: **판결 규율은 의도대로 강하게 작동한다(자기보고 eureka 거부·abandon 발화가 정확).
> 그러나 (1) provenance-tier 갭이 "측정했으나 미앵커"를 "측정실패"와 동일하게 0으로 집계해
> 건강한 프로그램을 degenerating으로 오독하게 만들고, (2) 정직한 자기정정(retraction)에
> 양(+)의 크레딧 경로가 없어 오류제거가 퇴화로 찍힌다.** 그 외 마이너 4건.

이 리뷰의 대상은 **엔진 자체**다. 연구 도메인 데이터/좌표/내부 인프라는 일절 포함하지 않는다.

---

## A. 실측 관찰 (receipts)

세션 중 실제 MCP 응답에서 그대로 인용.

### A-1. `assurance_tier=legacy` → 측정치가 client-float로 남아 fertility/eureka가 0 (HIGH, reporting)

**증상**: `legacy` tier 트리에서 `tree_metrics`가 다음을 반환:
```
fertility.confirmed 0/N · eureka true_rate 0.0 · hallucination 1.0 (N/N measurement_failed)
· anchored 0/N · psr 0.0 → lakatos_status: 다수 degenerating
```
FF1 server-anchoring가 tier gate에 걸려 **미적용**이면, 노드가 실제 측정 결과를 담고 있어도
novel metric이 "client float"로 남아 `anchored_ratio=0`이 되고, 그 결과 fertility·eureka가
전부 0으로 집계된다.

**왜 문제인가**: 이 0들은 **"측정이 없다/틀렸다"가 아니라 "측정이 서버앵커링을 못 받았다"**를
뜻한다. 그런데 `eureka hallucination 1.0`·`degenerating`은 전자(측정실패)와 **동일한 시그널로
표면화**된다. 실제로 측정 규율을 지키는 프로그램이 순전히 tier/부기(bookkeeping) 갭 때문에
"인식적 퇴화"로 오독된다. `receipts, not claims`를 표방하는 엔진에서, receipt가 있어도
tier 때문에 claim처럼 0으로 떨어지는 것은 아이러니다.

**제안**:
- `tree_metrics`가 **`measured_but_unanchored`를 `measurement_failed`와 별도 카운트**로 노출.
  eureka `hallucination`은 후자에만 기여해야 한다.
- `legacy` tier에서 degeneration/eureka를 보고할 때 **tier 캐비앗을 payload에 동봉**
  ("fertility=0 partly due to unanchored-on-legacy, not measurement absence").
- legacy→anchored **마이그레이션 경로/명령**을 문서화(어떻게 기존 client-float metric을
  서버앵커로 승격하는가). CONTRIBUTING의 "fake green 금지" 정신과 정합하는 유일한 출구.

### A-2. 정직한 자기정정(retraction)에 양의 크레딧 경로 부재 (HIGH, judgement semantics)

**반례(최소)**: 프로그램이 자신의 이전 노드 X(거짓으로 판명된 protective-belt 주장)를
correcting 노드 X'로 대체한다. X'는 X를 반증하고 더 좁고 검증가능한 주장을 세운다.
엔진은 이 X'를 **rejection/equivalent(비진보)**로 채점하고, `consecutive_nonprogressive`가
증가하여 abandon 신호가 깊어진다.

**왜 문제인가**: Popper/Lakatos에서 **반증된 protective-belt를 제거하는 것은 그 자체로 진보**
(오류내용 감소 = 진리근접). 그러나 현재 엔진에서 "틀린 걸 고쳤다"는 stagnation과 **구별 불가**하게
degenerating을 심화시킨다. 결과적으로 **정직한 자기정정을 하는 프로그램일수록 트리 지표가
나빠진다** — 규율을 지키는 행위에 페널티가 걸리는 역인센티브.

**제안** (CONTRIBUTING §"judgement rules 변경은 issue 먼저" 준수 — 이건 제안이지 패치 아님):
- `corroborated_retraction`(또는 `content_decreasing_progressive`) 시그널 신설: 정정 노드가
  (a) 부모의 특정 주장을 **명시적으로 반증**하고 (b) **새 검증가능 예측**을 등록하면,
  abandon 카운터를 리셋하되 progressive와는 구분되는 별도 라벨로.
- 최소한 **"honest retraction"이 stagnation과 동일하게 abandon을 심화시키지 않도록** 분기.
- 반드시 gameable하지 않게: (b) 새 사전등록 예측 없는 단순 철회는 크레딧 0 유지.

### A-3. `longinus_bindings.json` line-hint 계통적 drift (MEDIUM, maintenance)

**증상**: `longinus_audit` → `235/235 passed`, `l4_drift: []`, `l6_drift: []` (심볼소멸·시그니처
변경 없음 = PASS). 그러나 바인딩의 **~40%가 `line_drift: true`**, 힌트가 실제 라인과 크게 어긋남:
```
verdicts.receipt_content_sha  line 427  hint 293  (Δ134)
verdicts.fold_receipt_chain   line 503  hint 369  (Δ134)
metrics._eureka_layer         line 296  hint 288
mcp_server.submit_result      line 354  hint 327
```
L4/L6가 아니라 PASS로 처리되지만, **line hint가 계통적으로 낡아** "binding is live"의 정밀도가
서서히 침식된다. 힌트가 충분히 밀리면 향후 진짜 이동을 오탐/미탐할 여지.

**제안**: `longinus_audit --refresh-hints`(또는 CI 유지보수 태스크)로 hint를 주기적으로 재동기화.
현재는 `line_drift: true`가 정보로만 남고 자동 치유 경로가 없다.

### A-4. `get_tree`가 MCP 토큰 한도 초과, summary/pagination 모드 없음 (MEDIUM, API)

**증상**: 20노드 트리에서 `get_tree` → **66,641자**, MCP 결과 한도 초과로 파일 덤프 강제
("exceeds maximum allowed tokens ... saved to ...txt"). 노드가 늘수록 MCP 경로로 트리를
읽는 것이 불가능해진다(파일+jq 우회 필요).

**제안**: `get_tree`에 **projection/summary 모드**(예: `fields=`, `metrics_only=true`) 또는
**pagination**. 최소한 노드당 verdict/lakatos_status만 반환하는 경량 뷰. (`tree_metrics`가
일부 대체하나, 노드별 raw verdict+frontier를 한 번에 훑는 경량 경로가 없다.)

### A-5. `add_node` name/tag 반전 = footgun (LOW, ergonomics)

`add_node(name=<TREE_NAME>, tag=<NODE_ID>)` — `name`이 **생성 대상 노드가 아니라 트리**,
`tag`가 노드 id. 직관과 반대라 반복적으로 헷갈린다(사용자 노트에도 "직관 반대"로 기록됨).
`register_prediction`/`submit_result`도 동일. **제안**: `tree=` alias 수용, 또는 트리명이
`tag`로 들어오면 명확한 에러.

### A-6. abandon 신호가 성공 payload 안에 묻힘 (LOW, UX)

`add_node`가 `abandon_signal.fired=true` + `policy_warnings:["ABANDON_SIGNAL_IGNORED"]`를
반환하면서 **쓰기는 성공**한다(설계상 non-blocking은 타당). 다만 성공 응답 안에 섞여 놓치기 쉽다.
**제안**: 마이너 — 경고를 더 두드러지게, 또는 `strict` 모드 옵션.

---

## B. 잘 작동하는 것 (긍정 receipts)

- **자기보고 eureka 거부가 정확**: node-level `eureka_true=8`(self-report)이 external-anchor
  부재로 metrics에서 downgrade됨 → 엔진이 self-vouch를 안 세준다. 규율의 핵심이 실제로 산다.
- **abandon 발화가 정당**: `consecutive_nonprogressive≥3`·`prediction_hits 0`에서 정확히 발화.
  서사 노드만 쌓는 것을 거부하고 "사전등록 측정을 내놓으라"고 요구 — 의도대로.
- **prereg gate가 실효**: `register_prediction`이 `pred_receipt_sha`를 발급하고 사후채점을
  차단(submit 전 등록 강제). 측정 정직의 앵커로 기능.
- **longinus L4/L6 무결**: 심볼소멸·시그니처변경 0 — 코드↔KG 바인딩의 핵심 무결성은 지켜짐.

---

## C. 우선순위 요약

| # | 이슈 | 심각도 | 종류 |
|---|---|---|---|
| A-1 | legacy tier → 측정치 미앵커가 fertility/eureka 0으로 집계, degenerating 오독 | HIGH | reporting |
| A-2 | 정직한 retraction에 양의 크레딧 경로 없음 → 자기정정이 퇴화로 찍힘 | HIGH | judgement |
| A-3 | longinus line-hint 계통 drift, 자동 치유 없음 | MED | maintenance |
| A-4 | get_tree 토큰 초과, summary/pagination 부재 | MED | API |
| A-5 | add_node name/tag 반전 footgun | LOW | ergonomics |
| A-6 | abandon 경고가 성공 payload에 묻힘 | LOW | UX |

A-1·A-2는 CONTRIBUTING의 "judgement rules 변경 = issue 먼저" 대상 — 본 문서는 제안(관찰)이며,
패치 전 별도 이슈로 최소 반례·의도 시맨틱·fake-green 구분 테스트를 명시할 것을 권한다.
