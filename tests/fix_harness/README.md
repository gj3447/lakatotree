# FIX HARNESS — 2026-06-27 감사 수정 영수증 + 루프

이 디렉터리는 2026-06-27 멀티에이전트 감사에서 **적대적 검증을 통과한** 결함들에 대한
**RED negative-oracle 영수증**이다. 각 테스트는 결함을 *실제 코드 경로*로 재현하고
*수정 후의 올바른 동작*을 단언하므로, **지금은 RED**(버그 존재)이고 **수정이 들어오면 GREEN**이 된다.
이 프로젝트 자신의 독트린("rule changes start from RED", negative oracle, ooptdd 영수증)을 그대로 적용한 것.

## 루프 엔지니어링 (정적 영수증 → 엔진이 채점하는 사이클)
영수증만으론 "pytest 묶음"이다. 프로젝트 독트린(conjecture/verification 역할분리·receipts-not-claims·
eureka)에 맞춰 *루프*로 끌어올린다 — **엔진 자신의 `judge()` 가 감사 수정을 채점**한다(손입력 0):

- **`examples/audit_20260627_programme.py`** — 발견을 사전등록 `Prediction` + 독립 **이중가드**로 등재.
  `guard_defect`(개선축: 증상 죽음) 와 `guard_mechanism`(novel축: 메커니즘 산다)이 *서로 다른* 영수증
  비트라 `judge()` 가 판별한다: 둘 다 green → **progressive**, defect 만 → **partial**(ad-hoc 천장),
  mechanism 만/gated → **equivalent**, 미착륙 → **pending**. 단일비트면 progressive/pending 만(채점 연극).
- **`scripts/fix_loop.py`** — 재실행 가능한 한 사이클: ① measure(pytest 영수증) ② judge(엔진 verdict)
  ③ **eureka**(완료라 *주장(felt)* 한 수정 중 엔진이 progressive 로 *확증(true)* 한 비율; 나머지=환각=
  독립 mechanism 오라클/실-Neo4j 검증 필요) ④ ratchet(영수증 green=회귀 없음) ⑤ frontier(다음 OPEN).
- **`tests/test_audit_fix_programme.py`** — 위 판별력·eureka 분리를 메인 스위트에 박은 영구 가드.

```bash
python scripts/fix_loop.py        # 한 사이클: 보드 + eureka(felt/true/hallucinated) + frontier
```

## 동작 방식 (xfail-strict ratchet)
- 모든 영수증은 `@pytest.mark.xfail(strict=True)`. → **일반 `pytest tests/` 는 green 유지**(`xfailed` 로 보고).
- **RED 데모**: `bash scripts/fix_harness.sh` (= `pytest tests/fix_harness -rA --runxfail`) → 마커를 무시하고
  실제로 돌려 **버그가 진짜 실패로 드러난다**. (FAIL = 버그 미해결의 영수증.)
- 수정이 들어오면 영수증이 XPASS → `strict=True` 가 XPASS 를 hard fail 로 바꿔 **"이제 xfail 마커를 떼라"**
  고 강제한다(소리 없는 재-RED 차단).

```bash
bash scripts/fix_harness.sh                 # RED 보드(실패 = 미해결 버그)
pytest tests/fix_harness -q                 # suite-green 뷰(xfailed 보고)
LAKATOS_IT=1 bash scripts/fix_harness.sh    # #16/#17 실-Neo4j 영수증까지
```

## 영수증 목록

| # | 심각도 | 영수증 (test) | 재현 | 수정 위치 | 수정 한 줄 |
|---|---|---|---|---|---|
| **16/17** | **P1** | `test_fix_16_17_nonatomic-cas-rescore.py` | 🔶 **LAKATOS_IT 게이트**(실 Neo4j 동시 tx 필요 — 위증 없는 정직 스킵) | `server/contexts/tree/judgement_service.py:560-596` (+ `:268-304`, `evidence_claim_service.py:125-147`) | 가드 읽기 **전** 노드 쓰기락 강제: `SET e._cas=coalesce(e._cas,0)+0 WITH e WHERE (...)` (또는 verdict_source uniqueness 제약). 0행→409 유지. |
| 14 | P2(보안) | `test_fix_14_dashboard-xss-canonical-path.py` | ✅ hermetic RED | `server/dashboard_view.py:67` | `' → '.join(html.escape(p) for p in (m['canonical_path'] or []))` |
| 12 | P2(보안) | `test_fix_12_judge-script-symbol-path-escape.py` | ✅ hermetic RED | `server/contexts/tree/judgement_service.py:171-179` | `::` 분기도 plain 분기처럼 longinus 호출 **전** file_part 해석·격리(out_of_root 거부 + is_file + `_SCRIPT_MAX_BYTES`) |
| 15 | P2(보안) | `test_fix_15_reproducible-fs-walk-escape.py` | ✅ hermetic RED | `server/file_hashing.py:18` (+ `app.py:414`) | `path_sha` 진입부에서 source 경로를 artifact root 로 confine(`realpath().startswith(base)`), out-of-root 거부 + walk 크기/시간 cap |
| 7 | P2 | `test_fix_7_ontology-minmax-fail-open.py` | ✅ hermetic RED | `lakatos/ontology.py:60-64` | min/max 선언 + 값이 present-but-비숫자(`n is None`)면 위반 방출 (또는 min/max 시 type:number 암묵 강제) |
| 23 | P2 | `test_fix_23_oo-strict-fail-open.py` | ✅ hermetic RED | `lakatos/io/oo_verify.py:119, :133` | 두 except 의 `'fail_build': False` → `'fail_build': mode == 'strict'` (warn 모드는 그대로) |
| 13 | P3 | `test_fix_13_add-critique-silent-200.py` | ✅ hermetic RED | `server/contexts/tree/evidence_claim_service.py:100-106` | MERGE 쿼리에 `RETURN e.tag` 추가, `self.hist(...)` **전** 0행이면 `raise HTTPException(404, ...)` |
| 22 | P3 | `test_fix_22_cli-lineage-colon-crash.py` | ✅ hermetic RED | `lakatos/cli.py:394, :399` | 각 항목 `':' not in p` 면 `sys.exit('... path:sha')` (cli.py:301-302 패턴, MCP 가드와 동형) |
| 6 | P3 | `test_fix_6_agm-expansion-allow-hardcore.py` | ✅ hermetic RED | `server/app.py:629` | `expansion(base, _belief(req.new), allow_hard_core=req.allow_hard_core)` (다른 3개 op 와 동형) |

🔶 = 정직 스킵(실 백엔드 필요, 위증 없음) · ✅ = 외부 의존 없이 RED 관측 완료

## 진행 상태 (2026-06-27 — 적용 완료)

엔진이 채점한 수정 현황(`python scripts/fix_loop.py`): **progressive 15 · partial 2 · frontier 3**.

| 영수증 | 상태 |
|---|---|
| #2 #4 #5 #6 #7 #8 #9 #10 #12 #15 #18 #21 #22 #23 #24 (**15개**) | ✅ **FIXED → progressive** — 소스 수정 + 영수증 영구 green 회귀(xfail 제거), 엔진이 이중가드로 progressive 채점 |
| #13 #14 (**2개**) | ✅ **FIXED → partial** — 수정·green 이나 단일 증상 오라클 → 엔진이 partial 천장(독립 mechanism 오라클 추가 시 progressive) |
| #1 (P2) | ✅ **FIXED → progressive** (honest-exposure, 전용 PR) — floor 가 `measurement_externally_anchored` 노출(judge_receipt 단독=False). '위조불가 영수증' 과대표현 봉합, *거동 불변* |
| #3 (P2) | ✅ **FIXED → progressive** (전용 PR) — noise_band 부재→약증거('부재 ≠ 선언-0') |
| #16/#17 (P1) | 🔶 **PATCHED(gated)** — eager-lock 3 사이트 적용 + h9 CAS-클래스 가드 통과. **race 자체는 `LAKATOS_IT`(실 Neo4j) 영수증 필요** → 로컬 eureka 는 felt-but-not-true |

**수정 후 전체 스위트**: `pytest tests/` → **1402+ passed / 13 skipped / 0 failed**(고정·랜덤 순서). lint-imports 3/3, 커널 커버리지 ≥95% green.

### 남은 *깊은* frontier (버그가 아니라 아키텍처 결정)
- **#1 외부성 *강제*(option-a) + producer replay**: 본 PR 은 측정 외부성을 *정직히 노출*(거동 불변)했다. 모든
  CANONICAL 에 외부앵커를 *강제*(option-a)하면 엔진의 문서화된 승격 거동(judge_receipt floor)을 바꿔 11개 floor
  테스트가 영향 — 중심 시맨틱 변경이라 maintainer 결정 + 마이그레이션. forge 의 *근본* 봉합은 producer replay
  (스크립트 재실행으로 metric_value 검증, app.py:395 미구현)이 필요하다. honest-exposure 가 그 전까지 간극을 가린다.

### #15 root 정책 (적용됨)
`server/file_hashing.path_sha` 가 `raw_root()`(= `LAKATOS_RAW_ROOT` env, 미설정 시 repo 루트) 밖 경로를
거부(None)한다. repo 밖 데이터를 쓰는 배포는 **`LAKATOS_RAW_ROOT` 를 그 데이터 루트로 설정**해야
out-of-repo source 의 재현성 검증이 동작한다(미설정 시 repo 루트 밖 source 는 None=증명불가로 처리 —
fail-safe, CANONICAL 위조는 막되 합법 검증은 env 로 복구).

### #16/#17 검증 방법 (실 Neo4j)
```bash
LAKATOS_IT=1 bash scripts/fix_harness.sh   # testcontainers Neo4j 로 동시 2-writer race 영수증 실행
```

### 수정 전 RED 보드 (참고)
```
13 failed, 2 passed, 2 skipped  (bash scripts/fix_harness.sh)
```
- **13 failed** = hermetic 영수증 = 미해결 버그 (#12·#13·#14·#15×2·#22×2·#23×2·#6×2·#7×2)
- **2 passed** = 의도된 control/scope 가드 (#12 plain-path 거부 control, #23 warn-mode 스코프 가드)
- **2 skipped** = #16/#17 (LAKATOS_IT 미설정 — 실 Neo4j 필요)
