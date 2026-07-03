"""LakatoTree git-흡수(2026-07-02) 도그푸드 하네스 — git 엔진 소스 해부가 도출한 인프라 불변식 10건(G1~G10)을
엔진 자신의 R&D 백로그로 등재.

선행: examples/frontier_fix_20260626_programme.py 가 6건(FF1~FF6)을 이중가드로 닫는 척추를 세웠다. 이 하네스는
같은 척추 위에, "라카토트리 엔진이 git 엔진의 어디를 닮아야 하나"를 묻는 흡수 프로그램을 올린다.

출처: git 소스(github.com/git/git @ e9019fc, <WORKSPACE>/PROJECT/PI/GIT/git) 8-서브시스템 17-에이전트 해부
(objects/refs/fsck/merge-ort/receive-pack/porcelain/commit-graph/gc; 기제주장 8건 소스대조 적대검증 6 CONFIRMED/
2 OVERSTATED→교정). 추가로 GitNexus 콜그래프(41,064노드/92,918엣지, PI/GIT/git/.gitnexus)로 초크포인트
*전수성*을 구조검증(M0). git 코드구조 1,172 심볼+1,478 CALLS 를 공유 consumer KG(GitSource_git_e9019fc)에 적재,
초크포인트 6개는 ABSORPTION_ANCHOR 로 해당 G-노드에 연결.

★조직 테제: git 은 정직을 *감사*해서가 아니라, 저장층에서 부정직이 *구조적으로 표현 불가능*하고 porcelain 층에서
정직이 *최저가*라서 신뢰된다. 라카토트리는 현재 역상(가변 verdict SET · 카운트 미러검증 · default-OFF 보증 ·
정직경로 최고가). 흡수는 정밀하다: git 은 인프라 불변식만 기여하고, 판결 권위는 라카토스 judge 층에 남는다
(docs/REFERENCE_COMPARISON.md: "외부 시스템은 증거·수송이지 판사가 아니다"). git 엔 판사가 없다 — 의도된 설계다.

★규율(frontier_fix 와 동일): 노드는 verdict 를 손입력하지 않는다. 각 흡수는 사전등록 Prediction + 독립 NovelTarget +
*명명된 이중 가드*만 들고 OPEN 으로 앉는다. guard 미착륙 = 정직한 pending(가짜 green 0).

★★ 이중가드(FG-2 교정 계승): 흡수당 두 개의 *독립* 오라클 —

    guard_defect    → 개선축(measured)     : git 이 구조로 막는 그 결함이 라카토트리에서 *죽었나* (음성 오라클)
    guard_mechanism → novel축(novel_measured): git 에서 흡수한 *메커니즘이 실재하나* (양성 오라클)

    defect닫힘 ∧ mechanism존재  → progressive  (진짜 흡수)
    defect닫힘 ∧ mechanism없음  → partial      (우회만 막고 git-메커니즘 없음 = ad-hoc 땜빵, 천장)
    defect열림 ∧ mechanism존재  → equivalent   (메커니즘 이식했으나 결함 여전 = 미완 흡수 적발)
    둘 다 미착륙               → pending(no-receipt)

첫 RED 영수증은 이미 착륙: tests/fix_harness/test_git_absorption_g1_verdict_overwrite.py 가 S3 결함(add_node
블랭킷 SET 이 scripted verdict 를 덮어씀)을 *실제 writer 경로*에서 xfail(strict) 로 재현 = 하네스에 이빨.

# KG: GitSource_git_e9019fc --DISSECTED_FOR--> LakatosTree_GitAbsorption_20260702
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
# 흡수 guard 들이 착륙할 전용 파일 패턴(아직 대부분 비어있음 = pending). 흡수될 때마다 하나씩 green.
_RECEIPT_GLOB = "tests/test_git_absorption_*.py"
# 첫 RED 영수증(G1 결함 재현)은 fix_harness 의 xfail-strict 래칫에 산다 — suite-green 유지, --runxfail 로 RED 데모.
_RED_RECEIPT_GLOB = "tests/fix_harness/test_git_absorption_*.py"
_TREE = "LakatosTree_GitAbsorption_20260702"
_GIT = "git@e9019fc (github.com/git/git, <WORKSPACE>/PROJECT/PI/GIT/git)"


def receipt() -> dict[str, bool]:
    """외부 측정 = repo .venv pytest 로 흡수 guard 테스트를 돌려 {test_func: passed} 수집(self-report 아님).

    guard 파일이 아직 0개면 빈 dict → run() 이 전부 정직한 pending 을 낸다.
    """
    matches = glob.glob(os.path.join(_ROOT, _RECEIPT_GLOB))
    if not matches:
        return {}
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {_RECEIPT_GLOB} -v --no-header -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


@dataclass(frozen=True)
class AbsorptionNode:
    tag: str
    rank: int                     # 실행 순서(gap심각도 x 기제적합도 x 비용); 0 = 루트/메타
    parent: str | None
    git_mechanism: str            # 흡수 대상 git 기제
    git_anchor: str               # git 소스 file:line (해부가 인용, 소스대조 검증)
    gitnexus: str                 # GitNexus 콜그래프 전수성 확인(M0) — 있으면
    lakatos_gap: str              # 닫는 라카토트리 갭(S3/S4/S5/P1/P3/NO-MERGE/read-model/identity/storage)
    story: str                    # 무엇을 왜 흡수 + git 은 어떻게 그걸 구조로 강제하나
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(git-mechanism present) — *독립* metric
    guard_defect: str = ""        # 개선축 음성 오라클(green=결함 죽음)
    guard_mechanism: str = ""     # novel축 양성 오라클(green=git-메커니즘 산다)
    anti: str = ""                # anti-absorption: 베끼면 안 되는 git 패턴 + 이유


# 루트 테제(채점 안 함) + 10개 흡수 노드(G1~G10) + M0 구조검증 메타(이미 완료 = 즉시 채점 가능).
NODES_SPEC: tuple[AbsorptionNode, ...] = (
    AbsorptionNode(
        tag="thesis", rank=0, parent=None,
        git_mechanism="(조직 테제)", git_anchor=_GIT, gitnexus="",
        lakatos_gap="(전체)",
        story="git 은 감사가 아니라 구조로 신뢰된다 — 이름=내용(odb/source-loose.c:614-621), 발행=first-write-wins "
              "단일 게이트(object-file.c:408-472), 삭제=포인터만(builtin/prune.c:84-109), 파생구조는 느리게는 "
              "답해도 틀리게는 안 함(commit-graph.c), 무인자 기본값이 빈 기록 거부(builtin/commit.c:482-495). "
              "라카토트리는 역상. 흡수는 인프라 불변식만; 판결 권위는 judge 층에 남긴다(git 엔 판사가 없다=의도된 설계). "
              "(루트 — 채점 안 함)",
    ),

    # ───────────── 코어(무결성): G1 이 나머지의 기반 ─────────────
    AbsorptionNode(
        tag="G1_immutable_verdict_receipts", rank=1, parent="thesis",
        git_mechanism="hash-before-write + first-write-wins 발행 + collision hard-error + freshen-not-rewrite",
        git_anchor="odb/source-loose.c:614-621; object-file.c:408-472,343-397,68-88",
        gitnexus="finalize_object_file_flags 호출자 정확히 4(loose/stream/quarantine-migrate/rename 래퍼) — 발행 단일게이트 전수확인",
        lakatos_gap="S3(verdict-erasure hatch, writer.py:81-89 블랭킷 SET) + storage(가변 in-place)",
        story="git 객체는 이름이 곧 내용이라 'update' 동사가 API 에 없고, 발행은 link(2) EEXIST 로 first-write-wins, "
              "재제출은 mtime 만 bump(freshen). 라카토트리는 반대 — writer.add_node 가 e.verdict 를 무가드 블랭킷 SET "
              "(verdict_source WHERE 없음)해 기존 scripted 'rejected'(NodeIn.verdict 기본 'proof')로 덮어써 BF 1/6 을 "
              "지운다. 흡수: verdict 를 노드 속성에서 불변 :VerdictReceipt(receipt_sha=sha256(canonical JSON), "
              "prev_receipt_sha 체인=reflog 증인)로 이관, 노드는 current_receipt_sha 포인터만 CAS 로 전진, 블랭킷 SET 삭제.",
        prediction=Prediction(metric_name="verdict_overwrite_replay_success", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="scripted verdict 는 어떤 노드-쓰기로도 덮이지 않는다(내용주소 불변 영수증+포인터 CAS)",
                              closes_question="q-g1-immutable-receipts"),
        novel_target=NovelTarget(metric_name="receipt_chain_rederivation_pass", direction="higher", threshold=1.0),
        guard_defect="test_add_node_cannot_overwrite_scripted_verdict",
        guard_mechanism="test_current_verdict_is_fold_over_receipt_chain",
        anti="git 의 미인증 committer identity 는 베끼지 않는다 — 영수증의 actor 는 요청 principal 에 묶는다(G10).",
    ),
    AbsorptionNode(
        tag="G2_version_supervised_serving", rank=2, parent="thesis",
        git_mechanism="산출물이 생산자 신원을 지님(trailer-checksum) + liveness-probed lock 하 배경 upkeep, 실패는 latch",
        git_anchor="commit-graph.c:2220-2221,2758-2777; builtin/gc.c:718-783,1700-1828",
        gitnexus="",
        lakatos_gap="S5(단일 무감독 uvicorn 이 6커밋 stale 코드 서빙, /version 없음, master 138커밋 뒤)",
        story="git 산출물(commit-graph)은 자기 생산 커밋 checksum 을 trailer 로 지녀 stale 을 자백하고, gc 는 pid+host "
              "lockfile+liveness 하에 돌며 실패를 latch 해 다음 실행을 막는다. 흡수: 서버가 기동 시 git HEAD sha+트리 "
              "해시를 /version 에 노출+모든 영수증에 스탬프, systemd 러너가 태스크 테이블을 lock+latch 로 돌리고, "
              "배포프로브가 /version vs 브랜치팁 diff. 이것 없이는 다른 모든 흡수가 prod 에서 검증 불가(최저비용·선결).",
        prediction=Prediction(metric_name="serving_sha_drift_undetected", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="서빙 프로세스의 코드 신원(sha)이 /version 으로 관측가능 + stale 이 배포프로브에 걸린다",
                              closes_question="q-g2-version-serving"),
        novel_target=NovelTarget(metric_name="supervisor_stale_latch_oracle", direction="higher", threshold=1.0),
        guard_defect="test_served_code_sha_is_observable_at_version_endpoint",
        guard_mechanism="test_maintenance_runner_latches_on_failure_and_lock",
        anti="git 의 무음 skip-on-contention/volume-triggered auto-gc 는 베끼지 않는다 — 인식적 행동을 자동 트리거하지 않고 표현 upkeep 만 스케줄.",
    ),
    AbsorptionNode(
        tag="G3_one_verb_honest_cycle", rank=3, parent="thesis",
        git_mechanism="무인자 as-is commit(amortized index) + 빈 기록 거부 + 트랜잭션 롤백 + advice.* + incore trial",
        git_anchor="builtin/commit.c:482-495,1780-1783; advice.c:43-98; merge-ort.h:86,100-101",
        gitnexus="",
        lakatos_gap="P3(정직경로 3-verb+스크립트 vs admin note 1-verb; 06-28 이후 scripted verdict 0)",
        story="git 이 세계를 이긴 건 해싱이 아니라 porcelain 경제학 — 무인자 커밋이 index 를 기본 스테이징으로 삼아 "
              "거의 공짜, 빈 커밋은 거부, 훅은 opt-in, 4xx 마다 advice 가 다음 명령을 가르친다. 라카토트리는 정직경로가 "
              "*최고가*라 신규 트리 전부가 판결기제를 우회(admin note). 흡수: run_cycle 을 봉인된 1-verb(사전등록→채점→"
              "제출→영수증 한 트랜잭션, 실패시 신규노드 0 롤백)+증거 스테이징+측정없음 거부+note 는 명시 강등 플래그로만"
              "(경제학 역전)+4xx advice 레지스트리+dry_run 인메모리 채점. credence 최저(행동 의존, q_adoption_metric_confound).",
        prediction=Prediction(metric_name="note_only_new_tree_ratio", direction="lower",
                              baseline_value=1.0, noise_band=0.25,
                              novel_prediction="정직경로가 note 경로보다 클라이언트 호출 수 엄격히 적다(기계적) → 신규 트리 영수증 커버리지 상승",
                              closes_question="q-g3-one-verb-cycle"),
        novel_target=NovelTarget(metric_name="cycle_rollback_atomicity_oracle", direction="higher", threshold=1.0),
        guard_defect="test_honest_cycle_costs_fewer_calls_than_note_path",
        guard_mechanism="test_run_cycle_rolls_back_to_zero_nodes_on_any_failure",
        anti="git 의 --no-verify(훅 우회)는 베끼지 않는다 — 보증게이트를 우회하는 off-switch 금지; advice 는 suggest-only(execute 아님).",
    ),
    AbsorptionNode(
        tag="G4_kg_mirror_content_verify", rank=4, parent="G1_immutable_verdict_receipts",
        git_mechanism="quarantine-then-migrate ingest + verify=레코드별 내용 재유도(카운트 아님) + 내용해시 체인",
        git_anchor="builtin/receive-pack.c:2354,2100-2116; commit-graph.c:2764-2914; midx.c:1043-1048",
        gitnexus="migrate_one(tmp-objdir.c) = 격리→검증→이주 단계, ABSORPTION_ANCHOR→G4",
        lakatos_gap="S4(sync 가 verdict_source/judged_at/node_state 미export, 카운트 verify, hand-written engine_scored=true 10건)",
        story="git 은 수신 객체를 tmp objdir 에 격리해 connectivity+fsck 통과 후에만 migrate 하고, verify 는 레코드별 "
              "내용을 진실 저장소에서 재유도한다(카운트 아님). 라카토트리 KG sync 는 hand-authored python 모듈을 "
              "source-of-truth 로 삼아 provenance 를 떨구고 카운트만 verify — 공유 KG 에 아무도 attest 안 한 "
              "engine_scored=true 가 산다. 흡수: 엔진 DB=ODB, 배치는 staging importBatch 로 격리, verify=행별 내용 sha "
              "재유도, 100% 일치시만 원자 재라벨, engine_scored 는 검증 배치에만 exporter 가 파생기록(손기록 불가).",
        prediction=Prediction(metric_name="mirror_tamper_verify_green", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="변조된 미러 행은 내용 sha 재유도로 verify RED + provenance 튜플 전량 export",
                              closes_question="q-g4-mirror-verify"),
        novel_target=NovelTarget(metric_name="mirror_row_sha_rederivation_ratio", direction="higher", threshold=1.0),
        guard_defect="test_tampered_mirror_row_fails_content_verify",
        guard_mechanism="test_mirror_exports_full_provenance_and_rederives_per_row",
        anti="'hand-edited 모듈에 진실이 있다'를 검증하지 않는다 — 그건 틀린 ODB 를 대조하는 것(현 sync 의 근본오류).",
    ),
    AbsorptionNode(
        tag="G5_single_metric_projector", rank=5, parent="thesis",
        git_mechanism="파생값을 한 곳에서 한 번 계산+동결 어휘 + plumbing(기계계약)/porcelain(렌더) 분리 + verify=재유도",
        git_anchor="merge-ort.c:4513-4581,588-593; Documentation/git.adoc:304-307; commit-graph.c:2764-2914",
        gitnexus="",
        lakatos_gap="read-model drift(fertility: tree_metrics=canonical-path vs leaderboard=all-nodes; 아키텍처 감사 유일 HIGH)",
        story="git 은 각 파생값을 한 정본 순서로 한 번 계산하고 출력 어휘를 동결하며(merge-ort conflict 어휘), plumbing 은 "
              "기계용 안정계약·porcelain 은 plumbing 에서 렌더한다. 라카토트리는 fertility 를 두 표면이 다르게 계산해 "
              "같은 트리에 모순값을 준다. 흡수: 파생 메트릭 전부 metrics.py 단일 생산자로, 스코프명 동결(fertility."
              "canonical_path vs .all_nodes), tree_metrics=plumbing/leaderboard=porcelain(렌더만), rebuild_verify 에 "
              "표면간 내용 diff, import-linter 로 server/* 의 메트릭 계산 금지. 이 백로그 자신의 메트릭 신뢰의 전제.",
        prediction=Prediction(metric_name="cross_surface_fertility_divergence", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="한 트리의 한 메트릭은 모든 표면에서 동일값(또는 다른 스코프명으로 명시 분리)",
                              closes_question="q-g5-single-projector"),
        novel_target=NovelTarget(metric_name="single_projector_import_contract", direction="higher", threshold=1.0),
        guard_defect="test_fertility_agrees_across_metrics_and_leaderboard",
        guard_mechanism="test_import_linter_forbids_metric_compute_outside_canonical_module",
        anti="git 의 commit-graph '없으면 없는 값' 대신 우리는 '없으면 느린 경로 재계산'(0/500 금지) — stale-degrades-not-lies 를 강화.",
    ),
    AbsorptionNode(
        tag="G6_assurance_tier_dispatch_table", rank=6, parent="G1_immutable_verdict_receipts",
        git_mechanism="per-verb precondition 비트를 한 commands[] 테이블에 선언+단일 디스패치 강제 + FATAL 비강등 + per-OID skiplist",
        git_anchor="git.c:529-685,479-506; fsck.h:23-104; fsck.c:176-226; builtin/receive-pack.c:2046-2064",
        gitnexus="",
        lakatos_gap="P1(require_novel_anchor/LAKATOS_REPLAY_EXEC/API token 전부 default-OFF; per-tree tier 없음)",
        story="git 은 verb 별 전제조건을 한 테이블에 선언하고 단일 run_builtin 이 핸들러 전 일괄검사한다(핸들러가 잊을 수 "
              "없음 = S3 의 핸들러별 비일관 장르 제거). fsck 는 FATAL 비강등+per-OID skiplist. 흡수: 트리 생성시 "
              "assurance_tier(exploratory/standard/precious) 선언, verb×gate 비트 테이블, 단일 래퍼가 tier×bits 검사, "
              "구조 코어(G1 CAS·prereg 409)는 *모든 tier 무조건*(git 의 default-OFF 를 정확히 반전 — P1 증명: 선택적 "
              "보증은 영원히 꺼짐), 하드코어 검사 FATAL, legacy 는 노드 content-hash skiplist 로만 면제(규칙 면제 불가), "
              "tier 는 get_tree/metrics/leaderboard 에 공시.",
        prediction=Prediction(metric_name="ungated_verdict_write_full_standing", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="tier 별 게이트가 단일 디스패치서 강제 + 구조코어는 무조건 + 하드코어 강등 시도 거부",
                              closes_question="q-g6-assurance-tier"),
        novel_target=NovelTarget(metric_name="tier_floor_rejection_oracle", direction="higher", threshold=1.0),
        guard_defect="test_no_mutating_verb_writes_verdict_below_tier_floor",
        guard_mechanism="test_structural_core_unconditional_and_hardcore_demote_rejected",
        anti="git 의 default-OFF 경계검사(transfer.fsckObjects 기본 off)는 *반전* 흡수 — 구조코어 gate 는 켜짐이 기본.",
    ),

    # ───────────── 프론티어: 최고 이론수익 ─────────────
    AbsorptionNode(
        tag="G7_consilience_operator", rank=7, parent="G9_prune_pointer_death",
        git_mechanism="merge-ort: 세 트리→한 트리 순수함수, 재귀 가상조상, conflict=stages[3] 데이터, incore-then-switch, 결정론",
        git_anchor="merge-ort.c:5303-5391,5006-5016,4513-4581,588-593; merge-ort.h:12-27,86",
        gitnexus="merge_incore_recursive 호출자 3(merge-tree/remerge-diff/구API 어댑터) — incore 진입 최소, ABSORPTION_ANCHOR→G7",
        lakatos_gap="NO-MERGE(PIDNA §3.3 '재합류의 정량조건' OPEN; kuhn.py supersession 은 이벤트지 병합 아님)",
        story="merge-ort 는 두 트리+공통조조상에서 결정론적 순수 병합을 낸다 — criss-cross 는 가상조상 재귀구성, "
              "conflict 는 실패가 아니라 stages[3] 데이터. 라카토트리엔 재합류 연산자가 없다(PIDNA 가 OPEN 으로 남김). "
              "흡수: consilience.py — 두 가지 leaf+최근접 BRANCHED_FROM 조상 A, 가상조상은 standing-불활성 레코드, "
              "hard-core/verdict-target 별 3-way 규칙(비양립=conflict 를 open_question/rival-standing *데이터*로, clean="
              "false 여도 병합완료). **핵심**: 병합 credence≠max — UNION verdict 시퀀스를 기존 bayes.branch_credence 에 "
              "fold 하면 target-keyed max-BF dedup 이 '양쪽 같은타깃 확증=1회'를 이미 구현 → PIDNA 미정 조건이 도출됨. "
              "verdict_mutation=False(incore→리포트→human/admin 게이트).",
        prediction=Prediction(metric_name="consilience_credence_shortcut", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="병합 credence 는 max 지름길이 아니라 UNION 시퀀스 fold(중복확증 dedup·양측 부정 누적)로만 계산",
                              closes_question="q-g7-consilience"),
        novel_target=NovelTarget(metric_name="merge_determinism_incore_oracle", direction="higher", threshold=1.0),
        guard_defect="test_merged_credence_is_not_max_shortcut",
        guard_mechanism="test_consilience_is_deterministic_incore_conflict_as_data",
        anti="git rerere(과거 해소 자동재생)·유사도 target 동일성은 베끼지 않는다 — 독립 확증을 credence 안에서 무음 붕괴시킴(하드제약).",
    ),
    AbsorptionNode(
        tag="G8_lakatos_fsck", rank=8, parent="G1_immutable_verdict_receipts",
        git_mechanism="단일 체커(fsck_object)를 오프라인 감사+pack ingest+loose ingest 에 동일 컴파일, 경계 at-least-as-strict",
        git_anchor="fsck.c:1254-1280,106-115; builtin/fsck.c:420; builtin/index-pack.c:936-959; builtin/receive-pack.c:174-191",
        gitnexus="fsck_object 호출자 정확히 3(builtin/fsck·index-pack·unpack-objects) — 단일 체커 테제 전수확인",
        lakatos_gap="storage(tolerant reader 불완전: source_trust=None 이 tree_metrics 500) + S5(서빙 자기감사 부재)",
        story="git 은 fsck_object 한 체커를 감사·pack ingest·loose ingest 에 동일 컴파일해 경계에서 거부하지 나중에 "
              "발견하지 않는다. 라카토트리의 tolerant reader 는 불완전 — None source_trust 가 metrics 를 500 낸다. "
              "흡수: audit/fsck.py 순수 체커, 열거 check-id(VERDICT_WITHOUT_PREREG/SCRIPT_SHA_MISMATCH/RECEIPT_SHA_"
              "MISMATCH/FORCE_OF_INCONSISTENT/MIXED_JUDGED_AT_TYPE/SOURCE_TRUST_NULL) 각 FATAL/ERROR/WARN, 동일 "
              "callable 이 fsck verb(전수감사)+writer pre-commit 양쪽서 실행, 엄격성 비트 직렬화로 audit==ingest 양방향 "
              "(git 의 ingest⊇audit 비대칭보다 강하게 — OVERSTATED 교정). fsck-clean≠판결축복(fsck 는 구조만).",
        prediction=Prediction(metric_name="tolerant_reader_500_on_corrupt_state", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="부패 상태(None trust·mixed type)는 500 이 아니라 열거 check-id 감사발견으로 표면화",
                              closes_question="q-g8-lakatos-fsck"),
        novel_target=NovelTarget(metric_name="corruption_injection_detection_ratio", direction="higher", threshold=1.0),
        guard_defect="test_corrupt_node_state_yields_finding_not_500",
        guard_mechanism="test_same_checker_runs_at_boundary_and_audit_bidirectional",
        anti="git identity attestation 은 fsck 범위 밖(우리도 동일) — fsck 는 구조 무결성만, 판결/정체성은 다른 층.",
    ),
    AbsorptionNode(
        tag="G9_prune_pointer_death", rank=9, parent="G1_immutable_verdict_receipts",
        git_mechanism="단일 삭제 게이트(unreachable AND aged) + over-inclusive 루트(reflog=GC root) + '(was <oid>)' 복구영수증",
        git_anchor="builtin/prune.c:84-109; reachable.c:299-355; builtin/branch.c:334-337; reflog.c:370-402",
        gitnexus="mark_reachable_objects 호출자 정확히 2(prune·reflog-expire) — 물리소거 게이트만 스윕 소비, ABSORPTION_ANCHOR→G9",
        lakatos_gap="S3 canonical 전이 + Laudan 폐기 의미론; G7 이 요구하는 비파괴 기반",
        story="git 삭제는 포인터만 죽인다 — 도달가능은 절대 수집 안 되고(reflog 도 GC root), 브랜치 삭제는 '(was <oid>)' "
              "복구영수증을 남기며, 물리소거는 두 시스템이 다른 시각에 행동(unreachable AND grace)해야 가능. 흡수: "
              "demote/prune/delete_tree 는 포인터(canonical 상태)만 조작·노드/영수증 불변, CANONICAL 이동은 G1 CAS+"
              "복구영수증, 스케줄 스윕이 {활성루트·research_events(=reflog root)·prereg 잠금·영수증체인}서 걸어 engine "
              "verdict_source 노드 전부 도달성 단언, 물리소거는 단일 게이트+서버강제 grace(플래그·note 로 0 불가), "
              "recency 는 서버 트랜잭션 시각(client mtime 금지). rejected·부정 영수증 영구 append-only.",
        prediction=Prediction(metric_name="prune_evidence_loss", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="폐기/demote 는 포인터만 죽이고 영수증은 grace 뒤 도달가능 유지(증거 손실 0)",
                              closes_question="q-g9-prune-pointer-death"),
        novel_target=NovelTarget(metric_name="reachability_sweep_orphan_free", direction="higher", threshold=1.0),
        guard_defect="test_demote_and_prune_never_destroy_receipts",
        guard_mechanism="test_reachability_sweep_keeps_engine_verdicts_reachable",
        anti="git 의 bare-prune TIME_MAX 기본·client mtime 은 베끼지 않는다 — 영수증 복제본 0 이라 grace 는 서버강제, 시각은 서버 tx.",
    ),
    AbsorptionNode(
        tag="G10_write_certificates", rank=10, parent="G6_assurance_tier_dispatch_table",
        git_mechanism="push cert: 서명 blob 이 곧 명령목록(cert+plain=프로토콜 에러) + stateless HMAC nonce + 서버유도 authorship",
        git_anchor="builtin/receive-pack.c:2179-2199,644-670,793-840",
        gitnexus="",
        lakatos_gap="identity(author/by/actor 미인증 client 문자열, Sybil-open) + S4 attestation 종단강화",
        story="git push cert 는 서명 blob 이 유일 명령원(cert+plain 동시=에러 → sign-X-execute-Y 불가), 서버발행 HMAC "
              "nonce 를 상수시간 비교, author 를 서명에서 유도한다. 라카토트리 identity 는 미인증 문자열(Sybil). 흡수: "
              "write-cert={signer,pushee,nonce,명령행: node_id old_receipt_sha new_receipt_sha}, 서버가 cert 에서만 "
              "명령 파싱, 서명·nonce 검증, cert 를 내용주소 증거로 저장, author 를 서명서 유도. 강제는 G6 tier 체인 "
              "안에서(anchored/precious 는 cert 요구) — git 의 advisory GIT_PUSH_CERT_STATUS 는 P1 실패라 반전. "
              "키 후보: p333 Ed25519 DID==PeerId(q_signer_key_substrate). G6+G3 후에만(먼저면 default-OFF 무덤).",
        prediction=Prediction(metric_name="actor_spoof_write_accepted", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="anchored/precious tier 쓰기는 서명 cert 없이 거부 + author 는 client 문자열 아닌 서명서 유도",
                              closes_question="q-g10-write-certificates"),
        novel_target=NovelTarget(metric_name="cert_binding_refusal_oracle", direction="higher", threshold=1.0),
        guard_defect="test_spoofed_actor_write_rejected_at_anchored_tier",
        guard_mechanism="test_author_derived_from_signature_not_client_string",
        anti="git 의 advisory cert(GIT_PUSH_CERT_STATUS-for-hooks, export-and-hope)는 베끼지 않는다 — 정확히 P1 실패; 강제는 서버측 tier 게이트.",
    ),

    # ───────────── 메타: 구조 전수성 검증(이미 완료 = 즉시 채점 가능) ─────────────
    AbsorptionNode(
        tag="M0_gitnexus_structural_xcheck", rank=0, parent="thesis",
        git_mechanism="(GitNexus 콜그래프 전수성 교차검증)",
        git_anchor="PI/GIT/git/.gitnexus (41,064노드/92,918엣지, GitNexus 1.6.x tree-sitter C)",
        gitnexus="초크포인트 5+1 전수확인: finalize_object_file_flags(4)·fsck_object(3)·ref_transaction_commit(24)·mark_reachable_objects(2)·merge_incore_recursive(3)·migrate_one",
        lakatos_gap="(방법론 — 흡수설계의 전수성 근거)",
        story="워크플로 눈-검증(인용 지점이 그렇게 동작한다)에 더해, GitNexus 콜그래프로 *전수성*(그 지점 말고 다른 "
              "경로가 없다)을 구조검증. S3 같은 탈출구는 늘 '다른 경로'라 흡수설계엔 이게 핵심 증거. 이 노드의 "
              "mechanism 은 이미 완료(공유 KG 에 GitSource_git_e9019fc + 초크포인트 6 ABSORPTION_ANCHOR 적재) → guard "
              "착륙시 즉시 progressive. defect 축 = '흡수설계가 눈-검증만이라 전수성 미확인'이 닫혔나.",
        prediction=Prediction(metric_name="absorption_anchors_unverified_for_exhaustiveness", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="각 초크포인트 흡수앵커가 콜그래프 호출자 전수집합으로 검증됨(우회경로 부재 구조확인)",
                              closes_question="q-m0-structural-xcheck"),
        novel_target=NovelTarget(metric_name="chokepoint_caller_set_exhaustive_in_kg", direction="higher", threshold=1.0),
        guard_defect="test_absorption_anchor_has_no_unaccounted_caller_path",
        guard_mechanism="test_chokepoint_anchors_present_in_shared_kg",
        anti="GitNexus C 지원은 import 해석 없는 이름 매칭 — static 동명함수 앨리어스 가능성을 단서로 명시(정밀도 높으나 100% 아님).",
    ),
)


def _score(n: AbsorptionNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)와 novel(novel축)이 *다른* 측정에서 온다(이중가드)."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value
    novel_measured = 1.0 if mech_present else 0.0
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, rank=n.rank, parent=n.parent,
                verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 두 가드 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_SPEC:
        if n.prediction is None:                                       # 루트 테제
            out.append(dict(tag=n.tag, rank=n.rank, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:                                                   # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, rank=n.rank, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, bool, bool, str]]:
    """이중가드가 by-construction 으로 판별함을 증명 — judge() 가 4-칸을 낸다(단일비트면 progressive/pending 만)."""
    probe = next(n for n in NODES_SPEC if n.tag == "G1_immutable_verdict_receipts")
    cases = [(True, True), (True, False), (False, True), (False, False)]
    return [(f"defect={dc}, mech={mp}", dc, mp, _score(probe, dc, mp)["verdict"]) for dc, mp in cases]


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: AbsorptionNode) -> dict:
    pred = n.prediction
    comment = f"[rank {n.rank}] {n.story}  (git {n.git_anchor})"
    if n.gitnexus:
        comment += f"  [GitNexus] {n.gitnexus}"
    if n.anti:
        comment += f"  [anti-absorption] {n.anti}"
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=comment,
        limitation=(f"novel!=개선 (judge 독립 이중가드): improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "조직 테제 — 채점 안 함"),
        algorithm="git-absorption" if pred else "thesis",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in NODES_SPEC]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"[rank {n.rank}] {n.tag}: {n.prediction.novel_prediction} "
              f"(guards: defect={n.guard_defect} / mechanism={n.guard_mechanism}; git {n.git_anchor})")
    for n in NODES_SPEC if n.prediction is not None
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"git-absorption guard receipt: {landed}/{len(rc) or 0} green ({_RECEIPT_GLOB})")
    print(f"RED 영수증(결함 재현, xfail-strict): {_RED_RECEIPT_GLOB}\n")
    rows = run(rc)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    n_closed = sum(1 for r in rows if r["status"] == "CLOSED")
    for r in sorted(rows, key=lambda r: (r["rank"] if r["rank"] else 99, r["tag"])):
        if r["status"] == "ROOT":
            tail = "(테제·루트)"
        elif r["verdict"].startswith("pending"):
            tail = r.get("note", "")
        else:
            tail = f"novel={r.get('novel')} improved={r.get('improved')} — {r.get('reason')}"
        print(f"  [rank {r['rank']}] {r['tag']:38} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in NODES_SPEC if n.prediction is not None)
    print(f"\n총 {n_findings} 흡수: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0). 흡수하고 두 guard 착륙시키면 자동 채점.")
    print("\n이중가드 판별력 증명 (_discrimination_demo) — 단일비트 하네스는 progressive/pending 만:")
    for label, _dc, _mp, verdict in _discrimination_demo():
        print(f"  {label:28} → {verdict}")
    print(f"\nKG 거울: {_TREE}  (git 소스구조: GitSource_git_e9019fc)")
