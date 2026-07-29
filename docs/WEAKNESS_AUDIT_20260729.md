# LakatoTree 약점 감사 피드백 — 2026-07-29

> 작성: 운영 인스턴스 실측 기반 외부 피드백 (kimi-work agent, 오너 지시)
> 근거: `fsck` 전수감사(2026-07-29 실시), `lakatotree-ledger-repair` 진단 리포트(2026-07-24),
> S3 r2 판정 불일치 조사(2026-07-24), Proxmox 이전 계획서(2026-07-24), 트리 인덱스 정돈본(2026-07-29)
> 성격: 진단 + 개선 제안. 코드 변경 0건. 측정값 관련 아무것도 변경하지 않음.

---

## 요약

| # | 약점 | 심각도 | 실측 근거 |
|---|---|---|---|
| W1 | 장부 무결성 부채 (레거시 면제 누적) | 높음 | fsck: 1,702 레코드 중 findings 1,046건(61%), ERROR급 577건, skiplist 555건 |
| W2 | replay 폐쇄망 취약 — 로컬 경로 judge | 높음 | 상위 5개 트리 eureka hallucination_rate 전부 1.0 (2026-07-24) |
| W3 | 저장값 vs 재도출 불일치 (읽기 경로가 쓰기 무효화) | 높음 | NODE_STATE_DRIFT 197건; JudgeProprioception eureka flip 실측 |
| W4 | 판정의 페이로드 형식 민감 + 4축 미영속 | 중간 | S3 r2: 동일 값·delta·novel인데 4축 동봉 여부로 판정 분기; history에 축 값 없어 통시 감사 불가 |
| W5 | 삭제 불가(G1/G9)의 역설 — 찌꺼기 영구 누적 | 중간 | 디버그 잔재 14, 고아 레코드 1(목록 존재·서버 404), 중복 3쌍, placeholder 1 |
| W6 | 운영 취약성 | 중간 | nohup 기동(자동재시작 없음, 2026-07-16 다운), mutating API 무인증(AUTH POSTURE=open), PG lazy-degrade, macOS venv 이식 불가 |
| W7 | 게이트가 협조적 에이전트에만 섬 | 중간 | cycle_budget self-raisable; 예산 조회 실패 시 fail-safe 무제한 |
| W8 | 사용법 의식 부담 — 관례 하나 틀리면 측정 사망 | 중간 | closes_question 미선언 시 problem_balance=0 → 전량 hallucinated, 사후 소급 없음 |
| W9 | tier 승격의 비소급성 | 낮음 | FF1은 신규 제출에만 무장; 레거시 노드는 개별 재제출 필요 |

공통 원인: 약점 대부분이 **"정직성 강제"의 비용**이다. 거짓 green을 막는 게이트가
레거시 비소급 치유 불가 + 삭제 불가와 결합해 감사·복구·운영 부채로 쌓인다.

---

## W1. 장부 무결성 부채 — 면제(skiplist)가 치유를 대체

**실측 (2026-07-29 fsck, 읽기 전용):**

```
trees 102 / records 1702 / findings 1046 / skiplist 555
ERROR: VERDICT_WRITE_WITHOUT_TIER_RESOLVE 259
       FORCEFUL_SOURCE_WITHOUT_RECEIPT  158
       VERDICT_WITHOUT_PREREG           118
       SCRIPTED_WITHOUT_SOURCE           42
WARN : RECEIPT_ENCODING_STALE          192
       NODE_STATE_DRIFT                 197
       MEASUREMENT_REFUTED_BUT_STANDING  46
       SOURCE_TRUST_NULL                 34
```

- 대부분 G6(tier resolve 스탬프) 이전 write라 레코드 열거 면제만 가능하고 규칙 면제는 불가.
- skiplist 555건은 "고친" 것이 아니라 "감사에서 제외한" 것 — 감사 표면이 영구적으로 더러운 상태.
- `MEASUREMENT_REFUTED_BUT_STANDING` 46건: replay mismatch인데 verdict가 그대로 서 있음
  (구버전 행은 원인 미영속이라 값 불일치/실행 실패 구분도 불가).

**개선 제안:**
1. 레거시 전용 1회성 재봉인(re-seal) 마이그레이션 경로 — tier-resolve 스탬프를 사후 부여하는
   배치 verb (사람 승인 게이트 유지). ledger-repair의 run-the-receipt 선례(HSWM p1v4 r2)를
   표준 절차로 승격.
2. skiplist 크기를 tree_metrics/first-class 지표로 노출 — 면제 누적이 보이게.
3. replay 실패 시 원인(replay_failure_class) 영속을 구버전 행에도 백필.

## W2. replay 폐쇄망 취약 — judge가 로컬 경로면 측정 전멸

**실측 (2026-07-24 장부 진단, 상위 5개 트리):**

| 트리 | tier | replay 상태 | eureka (felt/true/halluc) |
|---|---|---|---|
| HSWM_20260719 (43노드) | notebook | mismatch 7+ / not_attempted 1+ | 10 / 0 / 10 |
| HSWM_SolidMultiAgent (34노드) | notebook | not_attempted 22 (전량) | 20 / 0 / 20 |
| BhgmanCeilingPierce (10노드) | receipted | mismatch 6 (전량) | 3 / 0 / 3 |
| JudgeProprioception (10노드) | anchored | not_attempted 7 (전량) | 4 / 0 / 4 |
| CHU_Ruliad (10노드) | notebook | mismatch 3 (전량) | 2 / 0 / 2 |

인과 사슬: judge 스크립트가 서버 replay 폐쇄망 밖(로컬 절대경로·로컬 import·빈 script_sha)
→ `measurement_grade=client_asserted`(L0) → novel 서버앵커 부재(anchored_ratio 0.0, 5개 중 4개 트리)
→ `novel_unconfirmed + bf_marginal` → eureka 전멸.

**가장 중요한 판결이 가장 낮은 등급**: CeilingPierce의 hard-core 유일 committed 증거
(pred-32b-repin-5arm, p=0.0078)가 L0. receipted tier인데 채점 6노드 전량 L0.

**개선 제안:**
1. submit 시점에 script 참조의 이식성 검사 — 로컬 절대경로/외부 import 감지 시
   WARN 또는 (receipted+ tier에서) 거부. self-contained 번들 또는 서버 수명주기 경로만 허용.
2. `pred_script_sha=null`(예측 시 스크립트 미동봉) 제출에 대한 경고 — HSWM novel 10건
   전멸의 직접 원인.
3. LLM-judge(dgx ollama 등)용 결정론 캐시/원시 JSONL 재채점 경로를 replay 폐쇄망 안에 표준 제공.

## W3. 저장값 vs 재도출 불일치 — 읽기 경로가 쓰기를 무효화

**실측:**
- `NODE_STATE_DRIFT` 197건 — persisted node_state ≠ derived state.
- JudgeProprioception: 노드 봉인값은 `eureka_true=true`(BF=6.0)인데 메트릭 재유도는
  전량 `hallucinated`(reason: measurement_failed). **노드에 true로 써 있는 eureka가
  읽기 경로에서 뒤집히는** 현상 실측. 이 트리가 바로 "판관 자기정체성"을 연구하는
  트리라는 점이 아이러니.

**개선 제안:**
1. 봉인된 판정(sealed verdict)과 재도출 판정의 권위 순서를 명문화 — 현재는 읽기마다
   다른 답이 나올 수 있어 장부 신뢰의 근간이 흔들림.
2. drift 감지를 fsck WARN이 아니라 write 시점 검증으로 전진 배치.

## W4. 판정이 페이로드 형식에 민감 + 4축 미영속

**실측 (S3 r2 조사, 2026-07-24):** 값(0.4458)·delta(−0.0542)·novel(true)이 완전히 같은데
원본은 `degenerating`(4축 동봉, ≥1 False), r2 복구본은 `progressive_unverified`(4축 생략).
엔진 규칙은 동일 — 출력이 입력 "형식"에 갈린다. 게다가 history의 test_result 페이로드는
4축 값과 게이트 사유(missing 리스트)를 기록하지 않아 **통시적 판정 감사 불가** —
"원본이 어느 축을 False로 냈는지" 영구 복구 불가로 확정됨.

**개선 제안:** (S3 리포트 §5.4 재확인) history test_result 페이로드에 lakatos 4축 +
게이트 사유를 포함. 판정 입력의 완전 영속이 장부의 최소 조건.

## W5. 삭제 불가(G1/G9)의 역설 — 찌꺼기 영구 누적

**실측 (2026-07-29 인덱스 정돈):**
- extaudit 디버그 잔재 14개 — 메타 폐기표기 완료했으나 물리 삭제는 증거불멸 불변식으로 봉인,
  `list_trees`에 영구 노출.
- 고아 레코드 1: `LakatosTree_RoleLayoutProbe_1784736533` — 목록엔 뜨지만
  get_tree/metrics 모두 404. **서버 측 목록 인덱스 찌꺼기** (데이터 아님).
- 중복 3쌍(HSWM_LargerAI, L3ReadProbe, MapleLineage — 마지막은 정본 미결), placeholder 1.
- 102개 중 실질 활성은 ~80개.

**개선 제안:**
1. 목록 인덱스 정비 verb — 실체 없는 인덱스 레코드를 식별·제거(데이터 삭제 아님, 인덱스 복구).
2. `list_trees`에 `include_deprecated=false` 기본 필터 — 삭제 원칙을 지키면서 가독성 확보.

## W6. 운영 취약성

**실측 (이전 계획서 2026-07-24 기준):**
- nohup 기동, 자동재시작 없음 → 2026-07-16 다운 사건 실재(복구 산출물이 별도 트리).
- **mutating API 무인증(AUTH POSTURE=open)** — LAN 바인딩 전 LAKATOS_API_TOKEN 필수.
- PG 미가동으로 history append lazy-degrade (best-effort).
- macOS venv 이식 불가 → 이전 시 의존성 drift 가능 (uv.lock 고정 필요).
- 접속 체인: client → ssh → stdio 브리지 → 127.0.0.1:55170. 단일 장애점 다수.

## W7. 게이트가 협조적 에이전트에만 섬

- `cycle_budget`은 assurance_tier와 달리 단조 ratchet이 없음 — 소진된 에이전트가 같은 트리에
  `create_tree(cycle_budget=<더 큰 값>)`을 다시 불러 **자기 천장을 스스로 올릴 수 있다**.
  정지는 협조적 에이전트에만 서고 적대적 에이전트엔 안 선다(코드 주석이 스스로 인정).
- 예산 조회 실패 시 fail-safe로 **무제한**(soft bypass) — 조회 계층 장애가 곧 게이트 해제.

**개선 제안:** budget에도 assurance_tier식 단조 ratchet(하향 409) 적용 검토.
fail-open 기본값을 트리 정책으로 명시 선택 가능하게.

## W8. 사용법 의식 부담 — 관례 하나 틀리면 측정 사망

- `closes_question`을 register 시점에 선언하지 않으면 채점 시 problem_balance=0
  → eureka 전량 hallucinated 공회전. **사후 closure 소급집계 없음**(false-부양 방지 seam).
- "submit 후 close" 관례 하나만 지켜도 balance 0. 올바른 사용법을 모르는 제출은
  측정이 구조적으로 죽는다.

**개선 제안:** submit 시점에 "이 예측은 closes_question 미선언이라 eureka가 죽는다"
경고를 응답에 포함 — 사후 발견이 아니라 사전 차단.

## W9. tier 승격의 비소급성

- tier를 올려도 레거시 노드는 치유되지 않음(FF1은 신규 제출에만 자동 무장).
  CeilingPierce가 receipted 승격 후에도 novel anchored_ratio 0.0인 것이 실측 증거.
- 레거시 노드는 개별 재제출이 필요 → 복구 비용이 노드 수에 선형.

---

## 우선순위 제안

1. **W2-1 (submit 시 이식성 검사)** — 신규 오염 유입 차단. 비용 최저/효과 최대.
2. **W4 (history 4축 영속)** — 한 줄 스키마 확장으로 통시 감사 불가 영역 해소.
3. **W3-1 (봉인 vs 재도출 권위 명문화)** — 장부 신뢰 근간.
4. **W1-1 (레거시 재봉인 배치)** — ERROR 577건의 실질 감축 경로.
5. **W5-1 (인덱스 정비 verb)** — 고아 레코드 제거.
6. W7·W8 — 게이트 정책 강화 + 사전 경고.

## 철칙 준수

- 본 피드백은 읽기 전용 실측에 근거. KG/DB/트리/노드 쓰기 0건, 판결 변경 0건.
- 측정값 관련 아무것도 변경하지 않음.
- 인용 수치는 전부 2026-07-29 fsck 출력 / 2026-07-24 장부 리포트 원문에서 전재.
