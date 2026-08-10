# MCP 도구 14개 인터페이스 명세 — 2026-08-10

> ## ⚠️ 전제 정정 (2026-08-10, 같은 날)
>
> **이 문서는 "소실 복구용"으로 작성됐으나 그 전제가 틀렸다. 소스는 소실되지 않았다.**
>
> `~/CD/SYMPOSIUM/GIT/`가 Mac에서 비어 있던 것은 소실이 아니라 **dev-01 NVMe로 계획 이관**된
> 것이었다(`SYMPOSIUM/FINDINGS/git-directory-loss-2026-08-10/RESOLUTION.md`).
> `lakatotree_codex_harness_20260714`은 `dev-01:/root/CD/SYMPOSIUM/GIT/`에 HEAD `6e4ccdd`로
> 온전히 있고, `@mcp.tool` 50개가 그대로다. 아래 14개 전부 `grep "def <name>"`로 존재 확인했다.
>
> **따라서 재구현은 불필요하다.** Mac 런타임은 `~/CD/lakatotree-mcp/`(dev-01의 rsync 미러)로
> 복원해 `tools/list` 50개 응답을 확인했다.
>
> 이 문서는 **재구현 명세가 아니라 도구 레퍼런스**로 남긴다. 아래 설명은 실행 중이던 서버의
> 도구 레지스트리에서 직접 뽑은 것이라 정확하며, 특히 `cycle_budget`의 self-raisable 한계처럼
> 소스만 읽어서는 놓치기 쉬운 운영 의미론이 정리돼 있다.

## 대조

| 코드베이스 | 도구 수 |
|---|---|
| `lakatotree_codex_harness_20260714` (dev-01, HEAD `6e4ccdd`) — **Mac 런타임 정본** | **50** |
| `~/CD/lakatotree` (HEAD `506f8aa`, 2026-07-25) | **36** |
| 차이 = 이 문서가 다루는 도구 | **14** |

두 코드베이스가 갈라져 있다는 사실 자체는 유효하다. `~/CD/lakatotree`만 쓰면 아래 14개를
못 쓴다. Mac MCP는 50개짜리(`~/CD/lakatotree-mcp/`)를 가리키도록 맞춰 뒀다.

---

## 재구현 대상 14개

### 1. `create_tree` — 나무 생성 / 메타 upsert

`MERGE (t:LakatosTree {name})`. `add_node` 전에 반드시 선행(없으면 404 "나무 없음").
멱등하되 **last-write-wins** — 같은 name 재호출은 보낸 값으로 덮어쓰고, 생략 필드는 빈값 초기화.

| 인자 | 타입 | 기본 | 비고 |
|---|---|---|---|
| `name` | string | — | 필수 |
| `title`, `doc`, `hard_core`, `frontier_rule`, `ontology` | string | `""` | 비우면 `policy_warnings` 경고(차단 아님) |
| `coverage_status` | string | `"unknown"` | `unknown\|partial\|exhaustive`. `exhaustive`는 비어 있지 않은 `coverage_statement` + 빈 backlog 필요 |
| `coverage_statement` | string | `""` | scope 서술 |
| `coverage_backlog_csv` | string | `""` | 쉼표구분. REST/CLI와 패리티 |
| `assurance_tier` | string | `""` | `notebook\|receipted\|anchored`. 신규 트리 생략 시 `anchored`. **하향 선언은 409 (단조 ratchet)** |
| `attestor_dids_csv` | string | `""` | `did:key` allow-list. 선언하면 anchored tier 판결 쓰기에 write-cert 강제 |
| `require_novel_anchor` | boolean | `false` | |
| `cycle_budget` | int\|null | `null` | 아래 참조 |

**`cycle_budget` 의미론 (PROM16 루프상한)** — 재구현 시 가장 주의할 부분:

- 세는 단위는 **판결받은 노드 수**이고, 소모량은 *저장된 채점노드 count*에서 파생한다
  (인메모리 카운터 금지 — 서버 재시작에도 살아남아야 함).
- 소진되면 판결 verb가 전부 거부된다: `run_cycle`은 타입 거부(`status='budget_exhausted'`, 쓰기 0),
  3-verb 경로의 `submit_result`·`set_verdict`는 429. **verb를 갈아타는 우회는 없다.**
- 단 `add_node` / `register_prediction`은 예산 밖이다 — 0은 트리 동결이 아니라 **판결 정지**다.
- 예산 조회가 실패하면 fail-safe로 무제한(soft bypass).
- ⚠️ **self-raisable**: `assurance_tier`와 달리 단조 ratchet이 없어(last-write-wins) 소진된
  에이전트가 같은 트리에 `cycle_budget=<더 큰 값>`으로 재호출해 자기 천장을 올릴 수 있다.
  즉 이 정지는 **협조적 에이전트에만 서고 적대적 에이전트엔 안 선다.** 재구현 시 이 한계를
  없앨지(ratchet 도입) 유지할지는 설계 판단이 필요하다.

### 2. `delete_tree` — 나무 삭제 (파괴적·복구불가)

`create_tree`의 짝. 미존재=404. 노드가 있으면 `cascade=true`일 때만 전체 삭제(아니면 409 —
오타로 실제 연구트리 날리는 것 방지). 빈 나무는 `cascade` 없이 삭제 가능.

| 인자 | 타입 | 기본 |
|---|---|---|
| `name` | string | 필수 |
| `cascade` | boolean | `false` |

### 3. `consilience` — G7 재합류 연산자 (R9)

두 leaf의 in-core 3-way 병합 리포트. **무변이 GET** (`verdict_mutation=False`) — canonical화는
기존 human/admin 게이트로.

- criss-cross(NCA 2개 이상)는 가상조상(standing 비활성)으로 처리
- 비양립은 conflict *데이터* `{target, base, side1, side2}`로 반환 (`clean=false`여도 병합은 완료)
- `credence=true`면 `union_credence` 동봉 — 같은 타깃 확증 dedup, 음의 증거 양측 누적.
  **BF>1 무타깃 확증은 422 fail-closed** (레거시 트리는 `pred_closes`가 빈값인 경우가 흔해 기본 `false`)
- `report_sha` = canonical JSON sha256 앞 16자

| 인자 | 타입 | 기본 |
|---|---|---|
| `name`, `leaf1`, `leaf2` | string | 필수 |
| `credence` | boolean | `false` |

### 4. `eureka` — 노드별 measurement-grade eureka

`felt`(novel 등록) vs `true`(확증 + substantial BF + 순문제폐쇄) vs
`hallucinated`(felt ∧ ¬true, the false aha). 판결 seam 산출.
standing(promotion)은 **별도 층**이다.

| 인자 | 타입 |
|---|---|
| `name`, `tag` | string, 필수 |

### 5. `fsck` — R6 전수감사 (비변이)

전 트리(또는 `tree` 지정) 노드 record를 fsck 단일 체커로 스캔. `counts`로 부패 분포,
`emit_skiplist=true`로 면제 후보(record content-sha) 방출 → 사람 검토 후 git 커밋.

| 인자 | 타입 | 기본 |
|---|---|---|
| `tree` | string | `""` (전체) |
| `emit_skiplist` | boolean | `false` |

### 6. `graph` — 시각 트리 GUI 데이터 척추 (E Phase 1)

node(색/klass 본류·퇴행·생존/클릭 패널) + edge(`BRANCHED_FROM`) + frontier +
agenda(human-in-the-loop 안건). 프론트엔드(Phase 2)가 이걸 렌더.

| 인자 | 타입 |
|---|---|
| `name` | string, 필수 |

### 7. `heuristic` — MSRP 연구정책

negative heuristic(hard core 보호 / redirect) + positive heuristic(다음 실험 생성:
`ABANDON` 퇴행가지 / `PUSH` 진보전선 / `PROBE` 미검 hard-core / `PRIORITIZE` 문제압).

| 인자 | 타입 | 기본 |
|---|---|---|
| `name` | string | 필수 |
| `leaf` | string | `""` = 정본 leaf |

### 8. `node_receipts` — G1 `:VerdictReceipt` 체인 + head 포인터

R5 공개 읽기표면. lineage `rebuild_verify`(동명이인·데이터 계보용)와 **다른 물건**이다.

| 인자 | 타입 |
|---|---|
| `name`, `tag` | string, 필수 |

### 9. `verify_verdict` — 체인 fold 재유도 vs 캐시 대조

**캐시 신뢰 금지, 재유도가 판관.** 부패는 500이 아니라 열거 finding
(`RECEIPT_CHAIN_MISMATCH`)으로 반환. `ok:false` = 변조/드리프트 → 즉시 조사 대상.

| 인자 | 타입 |
|---|---|
| `name`, `tag` | string, 필수 |

### 10. `series` — 프로그램 시계열 진단 (#5)

정본경로 verdict 시퀀스의 진보/퇴행 경향. `diagnostic_only` — **verdict 권위 없음**.

| 인자 | 타입 | 기본 |
|---|---|---|
| `name` | string | 필수 |
| `leaf` | string | `""` |

### 11. `trust` — eigentrust 글로벌 출처신뢰

트리의 실 인터넷 관측 그래프에 전이적 신뢰 고유벡터(P6 배선).
`coverage.mode` = `graph_propagated` / `seed_dominated` / `uniform_unlearned`로
현 데이터 두께를 정직 표기.

| 인자 | 타입 |
|---|---|
| `name` | string, 필수 |

### 12–14. Laudan 연구전통 3종 (전부 `diagnostic_only`, hard core 불침범)

**`tradition`** — 조회. `ontology` / `methodology` / `exemplars` + `commitments`.
인자: `name`.

**`tradition_set`** — 선언/갱신. 인자: `name`, `spec_json`.
`spec_json` = `{tradition_id, name, commitments[{commitment_id, kind, statement, revisability}],
ontology_commitments[], methodology_rules[], exemplars[], ...}`

**`tradition_appraise`** — commitment 수정 진단.
결과: `same_tradition_revision` / `tradition_drift` / `different_programme_candidate`.
`identity_boundary`도 **후보**일 뿐이고 hard-core는 LakatosGate/AGM 경유로 확정한다.

| 인자 | 타입 | 기본 |
|---|---|---|
| `name`, `commitment_id` | string | 필수 |
| `operation` | string | `"modify"` |
| `compatibility_claim`, `reason` | string | `""` |

---

## 두 코드베이스를 합칠 때의 순서 제안

재구현은 불필요하지만, `~/CD/lakatotree`(36개)와 harness(50개)를 정리할 일이 생기면:

1. **`create_tree` / `delete_tree`** — 나머지 전부의 전제조건. 없으면 새 트리를 못 만든다.
2. **`verify_verdict` / `node_receipts` / `fsck`** — 무결성 계층. 기존 데이터 보호용.
3. **`graph` / `series` / `heuristic`** — 진단·시각화. 판결 권위 없어 위험 낮음.
4. **`consilience` / `eureka`** — 판결 seam 관련. 의미론이 가장 미묘하니 마지막.
5. **`trust` / `tradition*`** — 부가 진단.

## 관련

- 인시던트 기록: `SYMPOSIUM/FINDINGS/git-directory-loss-2026-08-10/`
- 인프라 지도: `SYMPOSIUM/docs/INFRA_MAP_2026-08-10.md`
- 이 명세의 회수 시각: 2026-08-10, 삭제된 서버 프로세스 PID 43018 생존 중
