"""LakatoTree 2026-06-27 감사 수정 — self-dogfood programme (엔진이 *자기 수정*을 채점).

이 파일은 `tests/fix_harness/` RED 영수증을 *루프 엔지니어링*으로 끌어올린다. 정적 pytest 묶음이 아니라,
2026-06-27 멀티에이전트 감사가 찾은 결함들을 **사전등록 예측 + 독립 이중가드**로 등재하고 **엔진 자신의
judge() 가 verdict 를 생성**한다(손입력 0). 프로젝트의 핵심 독트린 — "누구도 자기 출력을 채점 못 한다" —
을 *감사 수정 자체에* 적용한다(design_audit_20260625 · frontier_fix_20260626 와 동일 척추).

★ 이중가드 (FG-2 교정 — frontier_fix_20260626_programme.py 의 핵심):
    guard_defect    → 개선축(measured)     : 결함/우회가 *죽었나* (음성 오라클; fix_harness 의 xfail 영수증)
    guard_mechanism → novel축(novel_measured): 수정 *메커니즘이 산다* (양성 오라클; 같은 영수증의 비-xfail 가드)
  두 축이 *서로 다른* 테스트(영수증의 다른 비트)라서 judge() 가 진짜로 판별한다:
    defect닫힘 ∧ mech존재  → progressive  (진짜 fix: 증상 죽음 + 독립 메커니즘 산다)
    defect닫힘 ∧ mech없음  → partial      (증상만 막은 패치 = 라카토스 ad-hoc 천장; 독립 메커니즘 오라클 부재)
    defect열림 ∧ mech존재  → equivalent   (메커니즘 건강하나 구멍 여전 = 미착륙/gated)
    둘 다 미착륙           → pending(no-receipt)
  단일 비트(개선=novel 한 테스트)면 judge() 는 progressive/pending 만 → 채점력 0 의 연극. 이 하네스는 그걸 피한다.

★ eureka (felt vs true — 환각 가드, lakatos/eureka.classify):
    felt        = 이 수정을 "완료"라 *주장*(claimed)했는가          🔵 아하 신호(신뢰불가)
    true        = felt ∧ 엔진이 progressive 로 *확증*(외부 영수증)   🔴 외부 red 통과
    hallucinated= felt ∧ ¬true (완료 주장했으나 엔진 미확증 = 단일오라클/gated)  ← 봉인해야 할 환각
  의미: "완료라 느낀" 수정 중 엔진이 progressive 로 확증한 비율 = true_rate. 나머지(partial/equivalent)는
  "felt 이나 not true" — 독립 메커니즘 오라클이나 실-Neo4j 검증이 더 필요하다는 *정직한* 신호.

실행:  python examples/audit_20260627_programme.py    (또는 루프: python scripts/fix_loop.py)
# KG: span_lakatotree_audit_fix_20260627 / LakatosTree_AuditFix_20260627
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lakatos.eureka import classify          # felt / true / hallucinated
from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 외부 측정 표면: fix_harness 영수증 + h9(verdict-write CAS 클래스 — #16/#17 의 mechanism 가드).
_RECEIPT_PATHS = "tests/fix_harness tests/test_design_audit_h9.py"
_TREE = "LakatosTree_AuditFix_20260627"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 영수증을 돌려 {test_func: passed} 수집(self-report 아님).

    xfail(미해결 결함)은 PASSED 가 아니므로 guard_defect 미착륙 = 정직한 OPEN. 수정+마커제거 시 PASSED
    → defect 닫힘. mechanism 가드(비-xfail 양성 오라클)는 오늘도 PASSED → 메커니즘 산다.
    """
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {_RECEIPT_PATHS} -v --no-header -p no:randomly -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR|XFAIL|SKIPPED)\b", line)
        if m:
            name, passed = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and passed
    return res


@dataclass(frozen=True)
class AuditNode:
    tag: str
    severity: str                 # P0 / P1 / P2 / P3 / ROOT
    parent: str | None
    claimed: bool                 # 이 수정을 "완료"라 주장하는가 (eureka felt)
    evidence: str                 # file:line
    story: str
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(mechanism) — *독립* metric
    guard_defect: str = ""        # 음성 오라클(green=결함 죽음)
    guard_mechanism: str = ""     # 양성 오라클(green=메커니즘 산다) — *다른* 테스트


def _P(metric: str, novel: str, q: str) -> Prediction:
    return Prediction(metric_name=metric, direction="lower", baseline_value=1.0, noise_band=0.0,
                      novel_prediction=novel, closes_question=q)


def _N(metric: str) -> NovelTarget:
    return NovelTarget(metric_name=metric, direction="higher", threshold=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# 노드: 루트 추측 + 21 결함(수정 10 claimed + OPEN 11). verdict 는 judge() 가 생성(손입력 0).
# ─────────────────────────────────────────────────────────────────────────────
AUDIT_NODES: tuple[AuditNode, ...] = (
    AuditNode(
        tag="audit_20260627_root", severity="ROOT", parent=None, claimed=False,
        evidence="2026-06-27 멀티에이전트 감사(12 finder×차원 → 적대검증 27/28 생존) + 수정 하네스",
        story="하드코어 추측: 표준 게이트(pytest/lake/lint-imports/coverage)가 green 인 성숙 코드베이스의 잔여 "
              "결함은 게이트가 못 잡는 곳(모델↔구현 간극·동시성 원자성·무인증 보안·fail-open·선언만-한-게이트)에 "
              "산다. 각 결함은 사전등록 예측+독립 이중가드로 등재되고 엔진 judge() 가 채점한다(루트 — 채점 안 함).",
    ),

    # ───── 동시성/원자성 ─────
    AuditNode(
        tag="FIX16_17_nonatomic_cas", severity="P1", parent="audit_20260627_root", claimed=True,
        evidence="judgement_service.py:560(submit)·:287(승격) · evidence_claim_service.py:131(강등)",
        story="Neo4j READ_COMMITTED 에서 WHERE-가드 'CAS' 가 비원자 → lost-update 이중채점. 수정: 가드 읽기 전 "
              "eager `SET _cas=coalesce(_cas,0)+0 WITH .. WHERE` 로 노드 쓰기락 선점(3 사이트). race 자체는 실-Neo4j "
              "(LAKATOS_IT) 필요 → defect 가드 gated(skip); mechanism 은 h9 CAS-클래스 가드(eager-lock 관용구 인식).",
        prediction=_P("verdict_write_cas_nonatomic", "가드 술어가 노드 쓰기락 하에서 평가돼 동시 재채점이 0행→409", "q-16-cas"),
        novel_target=_N("eager_lock_before_guard_present"),
        guard_defect="test_concurrent_submit_exactly_one_409",                  # gated(LAKATOS_IT) → 로컬 미착륙
        guard_mechanism="test_every_verdict_transition_write_has_cas_guard"),    # h9 — eager-lock 메커니즘 산다

    # ───── 보안(무인증 서버 표면) ─────
    AuditNode(
        tag="FIX14_dashboard_xss", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="dashboard_view.py:67",
        story="canonical_path 만 html.escape 누락 → 저장형 XSS. 수정: 각 원소 html.escape. (단일 증상 오라클 — "
              "독립 mechanism 오라클 부재 → 엔진이 partial 천장: 정직한 ad-hoc 표식.)",
        prediction=_P("dashboard_canonical_path_unescaped", "canonical_path 노드 태그가 렌더 시 이스케이프된다", "q-14-xss"),
        novel_target=_N("dashboard_escape_mechanism"),
        guard_defect="test_canonical_path_tag_is_escaped"),
    AuditNode(
        tag="FIX12_script_symbol_escape", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="judgement_service.py:171-179 (_isolate_script_file 공용화)",
        story="judge-script 'file::symbol' 분기가 FF4 경로격리/size-cap 우회(임의 .py sha 오라클). 수정: 두 분기 "
              "공용 `_isolate_script_file`. defect=symbol 분기도 out_of_root 거부 / mechanism=plain 분기 격리 산다.",
        prediction=_P("script_symbol_branch_bypasses_isolation", "::분기도 평이경로와 *대칭*으로 격리(out_of_root 거부)", "q-12-iso"),
        novel_target=_N("shared_isolate_script_file"),
        guard_defect="test_symbol_form_out_of_root_must_also_be_rejected",
        guard_mechanism="test_plain_out_of_root_absolute_is_rejected"),
    AuditNode(
        tag="FIX15_fs_walk_escape", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="file_hashing.py:18 (raw_root confinement) · app.py:415",
        story="path_sha 가 임의/거대 경로를 walk·hash(DoS+content read). 수정: raw_root()(LAKATOS_RAW_ROOT, 기본 "
              "repo 루트) 밖 거부. defect=reproducible 이 out-of-root 안 walk / mechanism=path_sha confinement 산다.",
        prediction=_P("path_sha_walks_arbitrary_paths", "out-of-root source 경로는 거부(walk/hash 안 함)", "q-15-walk"),
        novel_target=_N("raw_root_confinement"),
        guard_defect="test_reproducible_for_node_does_not_walk_out_of_root_source",
        guard_mechanism="test_path_sha_refuses_out_of_root_directory"),

    # ───── 정직성/정확성 (수정됨) ─────
    AuditNode(
        tag="FIX7_ontology_minmax", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="ontology.py:60-64",
        story="min/max 가 비숫자 값에 fail-open(문자열로 우회). 수정: min/max 선언+비숫자면 fail-closed 위반. "
              "defect=비숫자 위반 / mechanism=숫자 게이팅 산다.",
        prediction=_P("ontology_minmax_fail_open", "min/max 선언 + 비숫자 값 → 위반(fail-closed)", "q-7-onto"),
        novel_target=_N("numeric_gating_alive"),
        guard_defect="test_non_numeric_string_must_violate_bare_minmax",
        guard_mechanism="test_numeric_values_still_gate_correctly"),
    AuditNode(
        tag="FIX23_oo_strict_fail_open", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="oo_verify.py:119,133",
        story="oo strict 도착게이트 fail-open(예외→fail_build=False). 수정: except 가 fail_build=mode=='strict'. "
              "defect=strict 예외→빌드실패 / mechanism=warn 모드 여전히 swallow(스코프 보존).",
        prediction=_P("oo_strict_except_fail_open", "strict 모드는 ship/verify 예외도 빌드실패로", "q-23-oo"),
        novel_target=_N("warn_mode_still_swallows"),
        guard_defect="test_strict_verify_raise_fails_build",
        guard_mechanism="test_warn_mode_still_swallows_raise"),
    AuditNode(
        tag="FIX13_add_critique_404", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="evidence_claim_service.py:100-106",
        story="add_critique 가 없는 노드에 200+history(fail-loud 위반). 수정: RETURN e.tag + 0행이면 hist 전 404. "
              "(단일 증상 오라클 → partial 천장.)",
        prediction=_P("add_critique_silent_200", "없는 노드 critique 는 404(history 미기록)", "q-13-crit"),
        novel_target=_N("critique_fail_loud_mechanism"),
        guard_defect="test_critique_on_missing_node_raises_404_and_writes_no_history"),
    AuditNode(
        tag="FIX22_cli_colon_crash", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="cli.py:394,399",
        story="lineage-record/manifest-verify 가 ':' 없는 입력에 IndexError. 수정: ':' 검증 후 sys.exit(2 사이트). "
              "defect=lineage-record 깔끔 종료 / mechanism=manifest-verify 깔끔 종료(다른 사이트).",
        prediction=_P("cli_colon_indexerror", "':' 없는 입력은 IndexError 아니라 깔끔한 SystemExit", "q-22-cli"),
        novel_target=_N("manifest_verify_also_guarded"),
        guard_defect="test_lineage_record_no_colon_input_exits_cleanly",
        guard_mechanism="test_manifest_verify_no_colon_current_sha_exits_cleanly"),
    AuditNode(
        tag="FIX6_agm_expansion_consent", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="app.py:629",
        story="agm expansion 이 allow_hard_core 무시(동의 무효). 수정: expansion 에 forward. "
              "defect=동의 시 덮어쓰기 성공 / mechanism=동의 시 409 안 남.",
        prediction=_P("agm_expansion_ignores_consent", "expansion 도 allow_hard_core 동의를 존중", "q-6-agm"),
        novel_target=_N("consent_forwarded_no_409"),
        guard_defect="test_expansion_with_consent_overwrites_hard_core",
        guard_mechanism="test_expansion_consent_does_not_raise_409"),

    # ───── OPEN (RED 영수증 착륙 — 아직 미수정; guard_defect 는 xfail, mechanism 은 green) ─────
    AuditNode(
        tag="OPEN1_canonical_floor_externality", severity="P2", parent="audit_20260627_root", claimed=False,
        evidence="spine.py:167-189 · judge.py:98-110 · app.py:395",
        story="CANONICAL floor 가 judge_receipt 단독으로 열린다 — 측정값은 재실행 안 되는 미검증 client float. "
              "fix(a): 외부앵커 측정 없으면 reproducible/human 요구. defect=미검증 측정에 floor 닫힘 / mechanism="
              "reproducible=True 면 정당히 열림(판관 존재).",
        prediction=_P("canonical_floor_unverified_measurement", "외부앵커 없으면 judge_receipt 단독으로 CANONICAL floor 안 열림", "q-1-floor"),
        novel_target=_N("external_or_human_receipt_required"),
        guard_defect="test_canonical_floor_must_close_on_unverified_client_measurement",
        guard_mechanism="test_judge_receipt_predicate_is_the_floor_signal"),
    AuditNode(
        tag="OPEN3_noise_band_maxes_bayes", severity="P2", parent="audit_20260627_root", claimed=False,
        evidence="bayes.py:57-72 · metrics.py:58,141",
        story="noise_band 누락/0 → effect-size 포화 → 최대 BF(marginal<big 무력화, abandonment 약화). fix: "
              "noise_band<=0 약한증거. defect=trivial delta 가 max BF 못 빚음 / mechanism=선언 시 marginal<big 산다.",
        prediction=_P("noise_band_zero_maxes_bayes", "noise_band 미선언/0 은 최대 효과크기 가중을 받지 않는다", "q-3-noise"),
        novel_target=_N("effect_size_separates_when_declared"),
        guard_defect="test_zero_noise_band_trivial_delta_must_not_mint_max_bayes_factor",
        guard_mechanism="test_declared_noise_band_separates_marginal_from_big"),
    AuditNode(
        tag="OPEN4_branch_credence_nan", severity="P3", parent="OPEN3_noise_band_maxes_bayes", claimed=True,
        evidence="bayes.py:116-120",
        story="branch_credence 가 odds overflow 시 NaN((0,1] 위반, should_abandon fail-toward-retain). fix: log-odds/"
              "clamp. defect=overflow 가 유한 포화 / mechanism=overflow 전 (0,1] 유한.",
        prediction=_P("branch_credence_nan_overflow", "branch_credence 는 overflow 에도 유한값 in (0,1]", "q-4-nan"),
        novel_target=_N("finite_in_unit_interval"),
        guard_defect="test_overflow_must_saturate_finite_not_nan",
        guard_mechanism="test_below_overflow_returns_finite_in_unit_interval"),
    AuditNode(
        tag="OPEN5_heuristic_probe_deadwired", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="heuristic.py:144-153 · programme_service.py:184-189",
        story="PROBE 'already-probed' 제외가 dead-wired(hard_core 미토큰화 단일 blob). fix: 토큰화. defect=가지당 "
              "per-assumption probe / mechanism=토큰화 입력서 억제 산다.",
        prediction=_P("heuristic_probe_deadwired", "heuristic_view 가 가정별 PROBE 를 내고 blob 누설 안 함", "q-5-probe"),
        novel_target=_N("suppression_works_when_tokenized"),
        guard_defect="test_heuristic_view_emits_per_assumption_probes",
        guard_mechanism="test_probe_moves_suppression_works_on_tokenized_input"),
    AuditNode(
        tag="OPEN8_research_import_substring", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="research_import.py:51-61 · trust.py:103-130",
        story="_source_type substring URL 매칭(spoof 가능; trust.py 가 host-boundary 로 고친 것). fix: host 경계 "
              "재사용. defect=spoof host 미분류 / mechanism=정상 vendor host 분류 산다.",
        prediction=_P("research_import_substring_spoof", "spoof host 는 권위 vendor/primary 로 분류 안 됨", "q-8-spoof"),
        novel_target=_N("legit_host_still_classified"),
        guard_defect="test_spoof_host_not_classified_as_authoritative_vendor",
        guard_mechanism="test_legit_vendor_host_still_classified"),
    AuditNode(
        tag="OPEN9_rebuild_no_measurer", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="rebuild.py:64,78-97",
        story="측정 스텝 부재 시 'rebuildable' 이 producer 자기보고서 발급(M1 미강제). fix: measurer_separated 요구. "
              "defect=measurer 없으면 bare rebuildable 금지 / mechanism=분리 측정자 있으면 구별 산다.",
        prediction=_P("rebuild_no_independent_measurer", "독립 measurer 없으면 'rebuildable' 발급 금지", "q-9-rebuild"),
        novel_target=_N("measurer_separated_distinguishes"),
        guard_defect="test_no_measurer_must_not_yield_bare_rebuildable",
        guard_mechanism="test_measurer_separated_flag_distinguishes_independent_measurer"),
    AuditNode(
        tag="OPEN10_marquez_presence_only", severity="P2", parent="audit_20260627_root", claimed=True,
        evidence="marquez_verify.py:68-75,95-97,141-156",
        story="Marquez roundtrip compare 가 presence-only(부분 ingest 손실 탐지 불가). fix: count 대조(oo 미러). "
              "defect=부분 드롭→RED / mechanism=full roundtrip green.",
        prediction=_P("marquez_presence_only_compare", "Marquez 왕복이 부분 ingest 손실을 RED 로 잡는다", "q-10-marquez"),
        novel_target=_N("full_roundtrip_green"),
        guard_defect="test_marquez_partial_drop_must_flag_loss",
        guard_mechanism="test_marquez_full_roundtrip_is_green"),
    AuditNode(
        tag="OPEN2_promotion_decision_no_floor", severity="P3", parent="OPEN1_canonical_floor_externality", claimed=True,
        evidence="spine.py:133-143",
        story="promotion_decision() 가 floor 게이트 없는 dead code(재배선 시 receipt-0 CANONICAL). fix: 삭제 또는 "
              "synthesize 위임. defect=receipt-0 차단 / mechanism=synthesize floor 가 막음.",
        prediction=_P("promotion_decision_no_floor", "promotion_decision 도 no_receipt_for_canonical floor 를 진다", "q-2-deadcode"),
        novel_target=_N("synthesize_floor_blocks_receipt0"),
        guard_defect="test_promotion_decision_carries_no_receipt_floor",
        guard_mechanism="test_synthesize_promotion_floor_blocks_receipt0_canonical"),
    AuditNode(
        tag="OPEN24_measure_drops_exit_code", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="harness.py:152,156",
        story="_measure 가 judge_cmd 종료코드 버림(크래시 judge 의 metric 수용). fix: exit≠0 raise(build_gate 대칭). "
              "defect=non-zero judge 거부 / mechanism=build_gate 가 이미 종료코드 게이트.",
        prediction=_P("measure_drops_exit_code", "judge_cmd 가 non-zero 면 metric 수용 거부(raise)", "q-24-measure"),
        novel_target=_N("build_gate_exit_check_exists"),
        guard_defect="test_measure_must_reject_nonzero_judge_exit",
        guard_mechanism="test_build_gate_rejects_nonzero_exit"),
    AuditNode(
        tag="OPEN21_cli_observation_fields", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="cli.py:186-196 · mcp_server.py:442-485",
        story="CLI observation 이 rival/theory/longinus 증거 필드 미지원(MCP/REST 비대칭). fix: 인자 추가·forward. "
              "defect=rival/theory 인자 수용 / mechanism=기존 url/trust 인자 파싱 산다.",
        prediction=_P("cli_observation_missing_fields", "CLI observation 이 rival/theory/longinus 증거 인자를 노출", "q-21-cli-obs"),
        novel_target=_N("existing_trust_fields_parse"),
        guard_defect="test_observation_subparser_exposes_rival_theory_evidence_args",
        guard_mechanism="test_observation_subparser_parses_existing_trust_fields"),
    AuditNode(
        tag="OPEN18_pydantic_unpinned", severity="P3", parent="audit_20260627_root", claimed=True,
        evidence="requirements.txt · server/app.py:31 외 3",
        story="server 가 pydantic 직접 import 하나 requirements.txt 미고정(다음 'requirements 불완전'). fix: ==핀. "
              "defect=pydantic ==핀 존재 / mechanism=server 4 모듈이 실제 import(비-vacuity).",
        prediction=_P("pydantic_unpinned", "requirements.txt 가 pydantic 을 ==로 고정한다", "q-18-pin"),
        novel_target=_N("server_imports_pydantic_directly"),
        guard_defect="test_requirements_pins_pydantic_exactly",
        guard_mechanism="test_server_modules_import_pydantic_directly"),
)


def _score(n: AuditNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)과 novel(novel축)이 *다른* 측정에서 온다."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value
    novel_measured = 1.0 if mech_present else 0.0
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, severity=n.severity, parent=n.parent, claimed=n.claimed,
                verdict=v.verdict, improved=v.improved, novel=v.novel,
                defect_closed=defect_closed, mech_present=mech_present, reason=v.reason)


def _status(verdict: str) -> str:
    return {"progressive": "CLOSED", "partial": "CLOSED(partial)"}.get(verdict, "OPEN")


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 두 가드 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in AUDIT_NODES:
        if n.prediction is None:                                   # 루트 추측
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent, claimed=n.claimed,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:                                               # 영수증 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent, claimed=n.claimed,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        row = _score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False))
        row["status"] = _status(row["verdict"])
        out.append(row)
    return out


def _eureka_input(row: dict, n: AuditNode) -> dict:
    """row(judge 결과) → eureka.classify 입력. felt = 우리가 '완료'라 주장(claimed). true = 엔진 progressive 확증."""
    progressive = row["verdict"] == "progressive"
    return {
        "novel_registered": n.claimed,                 # 🔵 felt = 완료 주장
        "novel_confirmed": progressive,                # 🔴 외부 확증
        "verdict": row["verdict"],
        "delta": (0.0 - n.prediction.baseline_value) if row.get("improved") else 0.0,
        "noise_band": n.prediction.noise_band,
        "source_trust": 1.0,
        "closed": 1 if progressive else 0,
        "opened": 0,
    }


def eureka_board(rows: list[dict]) -> dict:
    """claimed(완료 주장) 수정에 대한 felt/true/hallucinated. hallucinated = 완료라 felt 했으나 엔진 미확증."""
    by_tag = {n.tag: n for n in AUDIT_NODES}
    verdicts = []
    detail = []
    for r in rows:
        n = by_tag.get(r["tag"])
        if n is None or n.prediction is None:
            continue
        ev = classify(_eureka_input(r, n), require_promotion=False)
        verdicts.append(ev)
        if ev.felt:
            detail.append((r["tag"], r["verdict"], "true" if ev.true else "HALLUCINATED",
                           "" if ev.true else f"reasons={list(ev.reasons)}"))
    felt = sum(1 for v in verdicts if v.felt)
    true = sum(1 for v in verdicts if v.true)
    hall = sum(1 for v in verdicts if v.hallucinated)
    return {
        "felt": felt, "true": true, "hallucinated": hall,
        "true_rate": round(true / felt, 3) if felt else 0.0,
        "hallucination_rate": round(hall / felt, 3) if felt else 0.0,
        "detail": detail,
    }


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
NODES = [
    dict(tag=n.tag, verdict="canonical_stage", parent=n.parent,
         comment=f"[{n.severity}] {n.story}  (근거 {n.evidence})",
         algorithm="audit-fix" if n.prediction else "conjecture",
         questions=[n.prediction.closes_question] if n.prediction else [])
    for n in AUDIT_NODES
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"audit-fix 영수증: {landed} green / {len(rc)} collected  ({_RECEIPT_PATHS})\n")
    rows = run(rc)
    for r in rows:
        if r["status"] == "ROOT":
            tail = "(추측·루트)"
        elif r["verdict"].startswith("pending"):
            tail = r.get("note", "")
        else:
            tail = (f"defect_closed={r['defect_closed']} mech={r['mech_present']} "
                    f"novel={r.get('novel')} improved={r.get('improved')}")
        claim = "claimed" if r.get("claimed") else "open   "
        print(f"  [{r['severity']:4}] {claim} {r['tag']:34} → {r['verdict']:18} {r['status']:16} {tail}")
    n_find = sum(1 for n in AUDIT_NODES if n.prediction is not None)
    n_prog = sum(1 for r in rows if r["verdict"] == "progressive")
    n_part = sum(1 for r in rows if r["verdict"] == "partial")
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    print(f"\n총 {n_find} 결함: progressive {n_prog} · partial {n_part} · OPEN {n_open}. "
          f"verdict 전부 judge() 생성(손입력 0).")
    eb = eureka_board(rows)
    print(f"\neureka(완료 주장한 수정의 외부확증): felt {eb['felt']} · true {eb['true']} · "
          f"hallucinated {eb['hallucinated']}  → true_rate {eb['true_rate']} / halluc_rate {eb['hallucination_rate']}")
    for tag, verdict, kind, why in eb["detail"]:
        mark = "✓" if kind == "true" else "✗"
        print(f"    {mark} {tag:34} {verdict:18} {kind:12} {why}")
    print(f"\nKG 거울: {_TREE}")
