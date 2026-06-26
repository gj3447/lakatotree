"""LakatoTree 설계감사(2026-06-25) 피드백 하네스 — 감사 발견 13건을 *엔진 자신의 R&D 백로그*로 도그푸드.

★규율(prom_honesty / selfdev 와 동일): 노드는 verdict 를 *손입력하지 않는다*. 각 발견(H1~H4, M1~M9)은
사전등록 Prediction + 독립 NovelTarget + *명명된 guard_test* 만 들고 OPEN 으로 앉는다. guard_test 는 아직
존재하지 않으므로(=결함이 안 고쳐짐) run() 은 전부 정직하게 pending(no-receipt) 을 낸다 — 가짜 green 0.
누군가 결함을 고치고 guard_test 를 tests/test_design_audit_*.py 에 착륙시키면, 그때 실 pytest receipt 에서
judge() 가 *스스로* progressive 를 생성한다. 즉 "엔진의 설계결함을, 그 결함을 고친 엔진이 채점한다"(재귀 도그푸드).

이 파일은 HARNESS.md run_cycle 의 ②하계-write(사전등록) 자리에 해당한다. ①상계-read(PROM: 어떤 OSS 를
훔쳐 어떤 기반지식으로 풀지)는 별도 PROM 도시에가 공급한다 — 각 노드 story 의 [PROM] 줄 참고.

핵심 추측(hard_core): 약속 #2("어떤 서브시스템도 자기 출력을 채점하지 않는다")는 verdict-*도출*에서만
by-construction 이 아니라 verdict-*입력*(측정·질적판단·인간승인·영수증)에서도 외부에 묶여야 한다. 메트릭
코어(verdict_source server-set-only · force_of SSOT)가 도달한 무결성을 측정/질적/승인 입력까지 밀어낸다.

감사 출처: LakatoTree design audit 2026-06-25 (8축 적대감사, HIGH 직접 라인확인).
# KG: span_lakatotree_design_audit_20260625 / LakatosTree_LakatoTree_DesignAudit_20260625
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
from dataclasses import dataclass, field

from lakatos.verdict.judge import NovelTarget, Prediction, judge

_ROOT = "<WORKSPACE>/PROJECT/PI/lakatotree"
# 감사 guard 들이 착륙할 전용 파일 패턴(아직 비어있음 = 전부 pending). 고쳐질 때마다 하나씩 green.
_RECEIPT_GLOB = "tests/test_design_audit_*.py"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 감사 guard 테스트를 돌려 {test_func: passed} 수집(self-report 아님).

    guard 파일이 아직 0개면 빈 dict → run() 이 전부 정직한 pending 을 낸다.
    """
    matches = glob.glob(os.path.join(_ROOT, _RECEIPT_GLOB))
    if not matches:
        return {}
    # -p no:randomly: dogfood 채점은 *결정론* — pytest-randomly 설치 여부와 무관히 같은 receipt(재현가능).
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {_RECEIPT_GLOB} -v --no-header -p no:cacheprovider -p no:randomly 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


@dataclass(frozen=True)
class AuditNode:
    tag: str
    severity: str                 # HIGH / MEDIUM
    parent: str | None
    evidence: str                 # 감사가 직접 확인한 file:line
    story: str                    # 무엇이 왜 결함인가 + [PROM] 어디서 무엇을 훔쳐 풀지
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_test: str = ""          # 결함이 닫혔음을 증명할 *독립* 측정(green=고쳐짐). 아직 미존재 = pending.
    prom: str = ""                # 1순위 염탐대상(PROM 도시에가 갱신)


# 루트 추측(채점 대상 아님) + 13개 OPEN 결함 노드. parent 로 cross-cutting 클러스터를 표현.
AUDIT_NODES: tuple[AuditNode, ...] = (
    AuditNode(
        tag="receipt_binding_hardcore", severity="ROOT", parent=None,
        evidence="README #2 / verdicts.py:149-163(force_of SSOT) / schemas.py:14(server-set-only)",
        story="하드코어 추측: 자기채점 차단(약속 #2)이 verdict-도출에서만이 아니라 verdict-입력(측정·질적·승인·"
              "영수증)에서도 외부에 묶여야 한다. 메트릭 코어의 by-construction 규율을 주변부 입력까지 확장한다. "
              "(루트 — 채점 안 함)",
    ),

    # ───────────────────────── HIGH (입력 self-report 클러스터) ─────────────────────────
    AuditNode(
        tag="H1_qualitative_self_report", severity="HIGH", parent="receipt_binding_hardcore",
        evidence="schemas.py:104-116(lakatos_*/ce_* bool, 짝 sha 없음) → judgement_service.py:250-285,306",
        story="질적 verdict(초과경험내용·하드코어보존)가 영수증 없는 client bool 로 progressive↔degenerating 을 "
              "토글하고 무조건 verdict_source='scripted' 를 상속해 canonical floor 까지 흐른다. 메트릭 축의 "
              "measured_sha 강제와 비대칭. [PROM] T4(AGM)+T5(독립 grader): 질적 bool→형식 결정/독립 Argument.",
        prediction=Prediction(metric_name="qualitative_axis_accepts_self_report", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="질적 self-report verdict 는 canonical floor 통과 차단(inconclusive-tier)",
                              closes_question="q-h1-qualitative-self-report"),
        novel_target=NovelTarget(metric_name="qualitative_self_report_blocked_from_floor",
                                 direction="higher", threshold=1.0),
        guard_test="test_qualitative_self_report_does_not_reach_canonical_floor",
    ),
    AuditNode(
        tag="H2_human_verdict_floor_bypass", severity="HIGH", parent="receipt_binding_hardcore",
        evidence="schemas.py:52(client bool) → judgement_service.py:90-93 → spine.py:172,178",
        story="client boolean human_verdict 1비트가 CANONICAL floor 를 연다 — 서버가 KG 에 실제 human "
              "Argument(actor≠작성자)가 있는지 대조하지 않는다(event_from_argument 존재하나 floor 미배선). "
              "[PROM] T5: in-toto/Sigstore 인간 attestation + event_from_argument 배선.",
        prediction=Prediction(metric_name="floor_trusts_client_human_bit", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="floor 의 has_human 은 KG 영속 human Argument 존재쿼리로만 충족",
                              closes_question="q-h2-human-attestation"),
        novel_target=NovelTarget(metric_name="floor_human_requires_persisted_argument",
                                 direction="higher", threshold=1.0),
        guard_test="test_human_verdict_floor_requires_real_kg_argument",
    ),
    AuditNode(
        tag="H3_judge_script_sha_client", severity="HIGH", parent="receipt_binding_hardcore",
        evidence="judgement_service.py:306,313(sha=r.script_sha) / 비교 :231-232(둘 다 client) / longinus.py 미연결",
        story="judge_script_sha 가 client 제출값이고 서버가 r.script 파일에서 재계산하지 않는다 → '어느 스크립트가 "
              "채점했나' 영수증이 문자열 신뢰. Longinus 209심볼 바인딩이 judge_script 와 연결돼 있지 않다. "
              "[PROM] T1(내용주소·서버 재해시)+T2(CPG 심볼 실존검증).",
        prediction=Prediction(metric_name="judge_script_sha_not_server_recomputed", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="submit 가 r.script 를 hashlib 로 재계산·대조(불일치 422)",
                              closes_question="q-h3-receipt-integrity"),
        novel_target=NovelTarget(metric_name="judge_script_bound_to_existing_symbol",
                                 direction="higher", threshold=1.0),
        guard_test="test_judge_script_sha_recomputed_server_side",
    ),
    AuditNode(
        tag="H4_demote_hardcore_unguarded", severity="HIGH", parent="receipt_binding_hardcore",
        evidence="agm.py:153-161(allow_hard_core 부재, contraction 미수행) / app.py:639-642",
        story="demote_canonical 이 hard_core 를 allow_hard_core 게이트 없이 credence 강등(다른-id 우회, KG 영속). "
              "docstring 은 'AGM revision/Levi identity'인데 contraction 호출이 없다(형식정직성 overclaim). "
              "[PROM] T4: AGM contraction success/consistency 공준 + TweetyProject Levi 구현.",
        prediction=Prediction(metric_name="demote_lacks_hard_core_gate", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="hard_core old 강등은 allow_hard_core 없으면 HardCoreProtected raise",
                              closes_question="q-h4-hardcore-protection"),
        novel_target=NovelTarget(metric_name="hard_core_demote_raises_without_consent",
                                 direction="higher", threshold=1.0),
        guard_test="test_demote_canonical_protects_hard_core",
    ),

    # ───────────────────────── MEDIUM 클러스터 ─────────────────────────
    AuditNode(
        tag="M1_rebuild_self_report_measure", severity="MEDIUM", parent="H3_judge_script_sha_client",
        evidence="cli.py:167-168,375(echo metric=0, 단일 template) / rebuild.py:67",
        story="rebuild 의 '외부측정'이 재실행 스크립트 self-report stdout + 손입력 기대값 — recipe step별 producer 무시 "
              "→ 동어반복. measurement 와 producer 미분리. [PROM] T3: OpenLineage facet·DVC·reproducible-builds.",
        prediction=Prediction(metric_name="rebuild_single_template_not_recipe", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="rebuild 가 recipe step별 producer 사용 + 기대값을 KG 에서 끌어옴",
                              closes_question="q-m1-repro-measure"),
        novel_target=NovelTarget(metric_name="rebuild_measure_independent_of_producer",
                                 direction="higher", threshold=1.0),
        guard_test="test_rebuild_uses_recipe_producers_and_kg_expected",
    ),
    AuditNode(
        tag="M2_harness_silent_swallow", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="harness.py:83-86(상태검사 0) / harness_run.py:24-25",
        story="run_cycle 이 서버 채점거부(404/422/409)를 조용히 삼킨다 — verdict=None 인데 exit 0 + stands=True. "
              "fail-loud 가 빌드(BuildFailed)에만. [PROM] T7: durable execution(Temporal/langgraph) 실패전파.",
        prediction=Prediction(metric_name="run_cycle_swallows_judge_rejection", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="error 키/verdict=None 시 JudgeRejected raise + prov 기록",
                              closes_question="q-m2-fail-loud"),
        novel_target=NovelTarget(metric_name="run_cycle_loud_fails_on_reject",
                                 direction="higher", threshold=1.0),
        guard_test="test_run_cycle_loud_fails_on_judge_reject",
    ),
    AuditNode(
        tag="M3_unconfirmed_counted_as_hit", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="metrics.py:71,223 + verdicts.py:65-70(PROGRESS_VERDICTS) / heuristic.py:215",
        story="Laudan 퇴행규칙이 미확증 progressive_conditional/former_canonical 을 prediction_hit 으로 인정 → "
              "degenerating 프로그램 생존 + bandit 보상 오염. [PROM] T8: bandit 보상 무결성·confirmed-novel 정의.",
        prediction=Prediction(metric_name="unconfirmed_progress_counted_as_hit", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="prediction_hits 는 confirmed-novel 만(CONFIRMED_NOVEL_PROGRESS)",
                              closes_question="q-m3-confirmed-novel-only"),
        novel_target=NovelTarget(metric_name="unconfirmed_conditional_chain_abandons",
                                 direction="higher", threshold=1.0),
        guard_test="test_unconfirmed_progressive_conditional_chain_should_abandon",
    ),
    AuditNode(
        tag="M4_raises_question_unmaterialized", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="쓰기측 RAISES_QUESTION grep 0건 / writer.py:83 / laudan.py:130",
        story="RAISES_QUESTION 엣지 writer 가 0개 → 라이브 KG 에서 opened 가 항상 0 → problem_balance(closed-opened) "
              "붕괴. 테스트가 monkeypatch dict 로 결함을 가린다. [PROM] T3: graphiti temporal KG·writer round-trip.",
        prediction=Prediction(metric_name="node_question_edges_unmaterialized", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="open_question 을 (e)-[:RAISES_QUESTION]->(q) 로 materialize",
                              closes_question="q-m4-problem-balance"),
        novel_target=NovelTarget(metric_name="opened_nonzero_after_kg_roundtrip",
                                 direction="higher", threshold=1.0),
        guard_test="test_raises_question_writer_roundtrip_opened_nonzero",
    ),
    AuditNode(
        tag="M5_rescore_toctou", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="judgement_service.py:229-230(read self.kg) vs 304-328(write self.kg_tx, WHERE 재가드 없음)",
        story="재채점 락 비원자(TOCTOU): read 와 write 가 별개 session. register_prediction 은 원자가드 있는데 "
              "submit 만 비일관 → 동시 submit 이중채점. [PROM] T6: omd write-set lease/fencing + Neo4j MERGE 원자성.",
        prediction=Prediction(metric_name="rescore_lock_nonatomic_toctou", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="submit SET 에 WHERE vsrc<>'scripted' 원자가드(0행=409)",
                              closes_question="q-m5-atomic-rescore"),
        novel_target=NovelTarget(metric_name="concurrent_submit_double_score_blocked",
                                 direction="higher", threshold=1.0),
        guard_test="test_concurrent_submit_does_not_double_score",
    ),
    AuditNode(
        tag="M6_posthoc_prediction", severity="MEDIUM", parent="H3_judge_script_sha_client",
        evidence="judgement_service.py:196-208(무조건 SET) / judge.py:93-95(PredictionLocked dead) / pred_registered_at write-only",
        story="사후예측 방지가 절차적: register_prediction 무제한 SET, PredictionLocked 서버경로 dead, "
              "registered_at write-only → 측정값 보고 prediction 재맞춤 가능. [PROM] T1: Rekor 투명성로그·RFC3161 TSA.",
        prediction=Prediction(metric_name="prediction_mutable_until_scored", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="등록 후 미채점 노드의 pred 재SET 은 409 + measured_at>registered_at 검증",
                              closes_question="q-m6-temporal-novelty"),
        novel_target=NovelTarget(metric_name="prediction_locked_after_registration",
                                 direction="higher", threshold=1.0),
        guard_test="test_prediction_locked_rejects_post_measurement_edit",
    ),
    AuditNode(
        tag="M7_ci_no_sorry_unenforced", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="ci.yml:96(lake build만) / Pidna.lean:12·README:45('sorry=0' 문구) / Lean sorry=warning",
        story="CI 가 sorry=0 를 실강제 안 함(Lean 에서 sorry 는 warning, lake build exit 0). 현재 sorry=0 이나 "
              "회귀가드 공백 — 문서가 강제 안 되는 보증을 약속. [PROM] T7: mathlib4 no-sorry CI·set_option warningAsError.",
        prediction=Prediction(metric_name="ci_does_not_enforce_no_sorry", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="CI grep 'uses sorry'→exit1 또는 set_option warningAsError true",
                              closes_question="q-m7-formal-ci-hygiene"),
        novel_target=NovelTarget(metric_name="lean_sorry_fails_build",
                                 direction="higher", threshold=1.0),
        guard_test="test_ci_fails_on_lean_sorry",
    ),
    AuditNode(
        tag="M8_doubt_resolution_actor", severity="MEDIUM", parent="receipt_binding_hardcore",
        evidence="claim.py:133-144(_resolved_doubt_ids, actor 무검사) / evidence_claim_service.py:149-176",
        story="claim doubt-resolution 이 actor 독립성 미검사 → 자기 의문을 자기 resolve 로 닫고 claim 을 세울 수 있다. "
              "[PROM] T5: 직무분리(SoD/NIST RBAC)·Dung 논증 actor 모델.",
        prediction=Prediction(metric_name="doubt_resolution_ignores_actor_independence", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="resolve actor==raiser/작성자면 해소 불인정",
                              closes_question="q-m8-actor-independence"),
        novel_target=NovelTarget(metric_name="self_resolved_doubt_does_not_stand",
                                 direction="higher", threshold=1.0),
        guard_test="test_self_resolved_doubt_does_not_clear_standing",
    ),
    AuditNode(
        tag="M9_external_readback_off", severity="MEDIUM", parent="M1_rebuild_self_report_measure",
        evidence="oo_verify.py:27-29(저자 TODO: '같은 프로세스 자기응답=영수증 연극') / marquez_sink.py:14-17",
        story="외부 readback(oo/Marquez) positive 왕복이 default OFF → 같은 프로세스 자기응답 대조. LTDD trace 적재 "
              "검증이라 verdict 본체는 아님. [PROM] T3: Pact 계약테스트·tracetest·OpenLineage 왕복 CI 고정.",
        prediction=Prediction(metric_name="external_readback_roundtrip_off", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="외부 백엔드 1개로 write→독립 read→compare 양성왕복 CI 고정",
                              closes_question="q-m9-readback-contract"),
        novel_target=NovelTarget(metric_name="independent_readback_confirms_receipt",
                                 direction="higher", threshold=1.0),
        guard_test="test_external_readback_positive_roundtrip_ci",
    ),

    # ════════════════ 완성-후 적대감사 2026-06-26 (13/13 완성 후 깨기 시도가 찾은 잔여) ════════════════
    #   13건 런타임 revert-proof + vacuous 0 확정 직후, "완벽하냐?"에 적대 감사로 답하다 발견.
    #   같은 결함 클래스(TOCTOU·client 자기보고)가 *형제 코드경로*에 남아 있었다.
    AuditNode(
        tag="H5_set_verdict_canonical_toctou", severity="HIGH", parent="M5_rescore_toctou",
        evidence="judgement_service.py:181(read self.kg)→:213(floor)→:225(write, WHERE old.tag<>$tag 만)",
        story="set_verdict CANONICAL 승격이 비원자 TOCTOU — floor 를 read-snapshot 으로 판정한 뒤 별개 세션 write 가 "
              "스냅샷 재검증 없이 CANONICAL 을 박는다. M5 는 submit 만 닫고 set_verdict 는 열어둠(감사문서 자인-연기). "
              "동시 submit/반박 critique 가 끼면 stale floor-pass 로 승격. [PROM] M5 의 단일-statement WHERE 원자가드 미러.",
        prediction=Prediction(metric_name="set_verdict_canonical_nonatomic_toctou", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="CANONICAL write 가 스냅샷(verdict/source/qsr/논증집합) 원자 CAS — 변하면 0행 409",
                              closes_question="q-h5-set-verdict-atomic"),
        novel_target=NovelTarget(metric_name="set_verdict_canonical_atomic_cas",
                                 direction="higher", threshold=1.0),
        guard_test="test_set_verdict_canonical_409_on_concurrent_change",
    ),
    AuditNode(
        tag="H9_verdict_cas_class_lock", severity="HIGH", parent="H5_set_verdict_canonical_toctou",
        evidence="tests/test_design_audit_h9.py (AST: 모든 verdict-전이/scripted SET 은 첫-SET-이전 가드 동반)",
        story="클래스 봉인(인스턴스 아님): H5/H7/M5/M12 가 verdict-mutating write 를 하나씩 원자 CAS 화했으나 *미래* "
              "무가드 전이가 TOCTOU/self-report 를 부활시킨다. AST 클래스-커버 테스트 — server/·lakatos/ 의 모든 Cypher "
              "에서 verdict 를 CANONICAL/former_canonical 로 전이하거나 verdict_source='scripted' 채점하는 SET 은 *같은 "
              "쿼리의 첫 SET 이전* 에 스냅샷 재검증 가드를 동반. 무가드 전이=RED. + verdict_source server-set-only 단언. "
              "'완벽=클래스 by-construction 불가능+재발 자동 RED' 의 verdict-write 판.",
        prediction=Prediction(metric_name="unguarded_verdict_transition_reintroducible", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="스냅샷 재검증 없는 verdict-전이 write 는 클래스 테스트가 RED 로 차단(4사이트 보장)",
                              closes_question="q-h9-verdict-cas-class-lock"),
        novel_target=NovelTarget(metric_name="verdict_transition_cas_enforced_by_class_test",
                                 direction="higher", threshold=1.0),
        guard_test="test_every_verdict_transition_write_has_cas_guard",
    ),
    AuditNode(
        tag="H7_add_critique_demote_toctou", severity="HIGH", parent="H5_set_verdict_canonical_toctou",
        evidence="evidence_claim_service.py:127(read)→:142(무가드 SET former_canonical) / H5 는 승격만 CAS",
        story="add_critique 자동강등이 비원자 TOCTOU — H5 의 거울쌍. 비판 등재 후 스냅샷 읽어 reconcile_standing "
              "으로 강등 결정한 뒤 별개 세션 write 가 스냅샷 재검증 없이 former_canonical SET. H5 는 set_verdict "
              "*승격* 만 잠갔고 이 *강등* 방향은 미러 안 됨. 동시 재승격/새 critique 가 read→write 에 끼면 stale 강등. "
              "[PROM] H5 의 스냅샷 CAS 를 강등 경로로 미러(verdict-mutating write 원자성 통일 — verdict_cas 초크포인트 예고).",
        prediction=Prediction(metric_name="add_critique_demote_nonatomic_toctou", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="강등 write 가 스냅샷(verdict+논증지문) 원자 CAS — 변하면 0행, stale 강등 skip",
                              closes_question="q-h7-demote-atomic"),
        novel_target=NovelTarget(metric_name="add_critique_demote_atomic_cas",
                                 direction="higher", threshold=1.0),
        guard_test="test_add_critique_demote_skipped_on_concurrent_change",
    ),
    AuditNode(
        tag="H6_novel_sha_client_independence", severity="HIGH", parent="H3_judge_script_sha_client",
        evidence="judgement_service.py:364(measured_sha=r.script_sha, novel_sha=r.novel_sha 둘 다 client) / judge.py:134",
        story="novel 독립성(measured_sha≠novel_sha)을 client 값으로 판정 — novel 측은 서버가 한 번도 재계산 안 함. "
              "client 가 novel_sha 를 measured 와 다른 임의 문자열로 보내 '독립'을 위조 → partial 을 progressive 로 "
              "승격. H3('서버가 sha 의 판관')가 정작 progressive 를 빚는 게이트에서 뚫림. [PROM] H3 의 _recompute_script_sha "
              "를 novel 축까지 확장(novel_script 본문 재유도) — 양측 서버앵커일 때만 독립.",
        prediction=Prediction(metric_name="novel_independence_trusts_client_sha", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="독립은 양측 서버재계산 sha 가 다를 때만 — client novel_sha 한 줄로 못 산다",
                              closes_question="q-h6-novel-sha-anchor"),
        novel_target=NovelTarget(metric_name="novel_independence_server_anchored",
                                 direction="higher", threshold=1.0),
        guard_test="test_client_novel_sha_string_does_not_buy_independence",
    ),
    AuditNode(
        tag="H8_self_vouch_af", severity="HIGH", parent="M8_doubt_resolution_actor",
        evidence="evidence_claim_service.py:_assemble_af(by collect 후 폐기) + judgement_service 인라인 AF(by 무시) / argue.py",
        story="standing 을 좌우하는 Dung AF 조립이 Argument 의 by(actor)를 버려, 작성자가 자기 doubt 를 자기 "
              "rebuttal 로 막아 verdict standing 을 유지(self-vouch)할 수 있었다. M8 은 claim_standing 경로만 "
              "닫았고 set_verdict floor·add_critique 강등의 AF 조립은 by 무시. [PROM] argue.assemble_af 정본으로 "
              "수렴 — 방어 엣지의 두 actor 가 같으면 AF 진입 차단(3 호출부 통일). 작성자vs방어자 독립=Sybil 천장.",
        prediction=Prediction(metric_name="af_assembly_ignores_actor_self_vouch", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="self-defense 엣지(attacker by==target by)는 AF 진입 못 함(자기 doubt 자기 rebuttal 무효)",
                              closes_question="q-h8-actor-independent-af"),
        novel_target=NovelTarget(metric_name="self_defense_edge_dropped_from_af",
                                 direction="higher", threshold=1.0),
        guard_test="test_self_rebuttal_does_not_defend_verdict",
    ),
    AuditNode(
        tag="M13_inline_af_class_lock", severity="MEDIUM", parent="H8_self_vouch_af",
        evidence="tests/test_design_audit_m13.py (AST: grounded_extension 호출 함수는 assemble_af 동반 강제)",
        story="클래스 봉인(인스턴스 아님): H8 은 3 호출부를 assemble_af 로 수렴했으나 *미래 인라인 AF* 가 클래스를 "
              "재발시킬 수 있다. AST 클래스-커버 테스트 — server/·lakatos/ 의 grounded_extension 호출 함수는 반드시 "
              "actor-aware assemble_af 도 호출. 위반시 commit 에서 RED → self-vouch 회귀를 사람이 아니라 CI 가 잡는다. "
              "'완벽=클래스를 by-construction 불가능 + 재발 자동 RED' 의 구현.",
        prediction=Prediction(metric_name="inline_af_assembly_reintroducible", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="grounded_extension 인라인 호출(assemble_af 미동반)은 클래스 테스트가 RED 로 차단",
                              closes_question="q-m13-af-class-lock"),
        novel_target=NovelTarget(metric_name="inline_af_banned_by_class_test",
                                 direction="higher", threshold=1.0),
        guard_test="test_no_inline_af_assembly_actor_independence",
    ),
    AuditNode(
        tag="M10_rebuild_cli_collapse", severity="MEDIUM", parent="M1_rebuild_self_report_measure",
        evidence="cli.py:376(cmd_for=lambda st: a.cmd_template, st 무시) + rebuild.py(measurer_separated=measure_out is not None)",
        story="M1 엔진수정은 kind='measurement' 출력만 신뢰하지만, *실제 재실행 유일 surface* CLI rebuild-run 이 "
              "모든 step 에 단일 --cmd-template 를 먹여(st 무시) producer step==measurement step → 측정자=생산자 "
              "붕괴(M1 결함이 surface 에서 부활). measurer_separated 영수증은 그래도 True 라 붕괴를 조용히 숨김. "
              "[PROM] 분리를 kind 라벨이 아니라 *명령 구별* 로 판정(엔진, 모든 surface) + CLI --measure-cmd.",
        prediction=Prediction(metric_name="rebuild_cli_single_template_collapse", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="measurement 명령==producer 명령이면 measurer_separated=False(엔진 판정) + CLI --measure-cmd 라우팅",
                              closes_question="q-m10-cli-measurer-separation"),
        novel_target=NovelTarget(metric_name="rebuild_collapse_detected_by_command_distinctness",
                                 direction="higher", threshold=1.0),
        guard_test="test_collapsed_measurer_command_is_not_separated",
    ),
    AuditNode(
        tag="M11_marquez_readback_off", severity="MEDIUM", parent="M9_external_readback_off",
        evidence="marquez_sink.py:19(ship=POST status 만) + adapters.py:332(send_openlineage…POST) / oo_verify 만 왕복",
        story="M9 수정(oo_verify.assert_positive_roundtrip)은 oo 백엔드에만 write→독립read→compare 왕복을 뒀고, "
              "M9 발견이 *직접 인용한* Marquez(marquez_sink)는 여전히 POST fire-and-forget — 독립 GET readback "
              "없이 '예외없음/200=배송됨'(M9 가 닫으려던 그 실패모드). 한 백엔드는 닫고 다른 백엔드는 연 비대칭. "
              "[PROM] oo_verify 의 OoRoundtripStore/assert_positive_roundtrip 를 Marquez HTTP 경로로 동형 차용.",
        prediction=Prediction(metric_name="marquez_fire_and_forget_no_readback", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="Marquez 경로도 ship→독립 readback GET→compare 왕복 + drop 이빨(항상 ON)",
                              closes_question="q-m11-marquez-readback"),
        novel_target=NovelTarget(metric_name="marquez_independent_readback_confirms_run",
                                 direction="higher", threshold=1.0),
        guard_test="test_marquez_positive_roundtrip_independent_readback",
    ),
    AuditNode(
        tag="H10_qual_backed_client_sha", severity="HIGH", parent="H6_novel_sha_client_independence",
        evidence="judgement_service.py:437 qual_backed=bool(r.novel_sha and ce_novel_corroborated) — raw client novel_sha",
        story="client-receipt 클래스 슬라이스(H1↔H6 잔여): H1 의 질적-backing 판정이 H6 가 위조가능함을 증명한 raw "
              "client r.novel_sha 를 그대로 신뢰 — client 가 novel_sha='아무거나'+ce_novel_corroborated=True 로 "
              "qual_backed=True 를 만들어 self-report 표식을 회피, 영수증 없는 질적 progressive 가 CANONICAL floor 를 연다. "
              "[PROM] H6 의 서버앵커 novel_server_sha 로 바인딩 — client 문자열로 질적-backing 못 산다. "
              "(ce_novel_corroborated 자체=construct-validity 라 client 판단으로 남음 — 천장.)",
        prediction=Prediction(metric_name="qual_backing_trusts_client_novel_sha", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="질적-backing 은 서버앵커 novel_server_sha 가 있을 때만 — client novel_sha 문자열 무효",
                              closes_question="q-h10-qual-backing-anchor"),
        novel_target=NovelTarget(metric_name="qual_backing_server_anchored",
                                 direction="higher", threshold=1.0),
        guard_test="test_client_novel_sha_string_does_not_back_qualitative_claim",
    ),
    AuditNode(
        tag="M12_former_canonical_source", severity="MEDIUM", parent="H5_set_verdict_canonical_toctou",
        evidence="judgement_service.py:229(SET old.verdict='former_canonical', source 누락) vs app.py:603/certify.py",
        story="set_verdict 의 former_canonical 강등이 verdict_source='engine' 누락 → old 가 'admin' source 유지. "
              "다른 모든 강등경로는 engine 명시. force_of('former_canonical','admin')는 여전히 SELF_REPORT 라 집계 "
              "결과 불변(minor)이나 '엔진 강등 vs 인간 admin' provenance 귀속이 이 경로만 틀림. [PROM] 강등경로 정합.",
        prediction=Prediction(metric_name="former_canonical_demotion_source_divergent", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="강등 SET 이 old.verdict_source='engine' 귀속(타 강등경로와 정합)",
                              closes_question="q-m12-demotion-provenance"),
        novel_target=NovelTarget(metric_name="former_canonical_attributed_to_engine",
                                 direction="higher", threshold=1.0),
        guard_test="test_former_canonical_demotion_attributes_engine_source",
    ),
)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). guard 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in AUDIT_NODES:
        if n.prediction is None:                                   # 루트 추측
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        if n.guard_test not in rc:                                 # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: {n.guard_test}"))
            continue
        # 결함이 닫혔다고 주장하는 guard 가 green이면: improvement=0(hole closed), novel=guard 통과 → judge 채점
        improved_metric = 0.0 if rc.get(n.guard_test, False) else n.prediction.baseline_value
        novel_measured = 1.0 if rc.get(n.guard_test, False) else 0.0
        v = judge(n.prediction, improved_metric, n.novel_target, novel_measured)
        out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent,
                        verdict=v.verdict, status="CLOSED" if v.verdict == "progressive" else "OPEN",
                        novel=v.novel, improved=v.improved, reason=v.reason))
    return out


# ── PROM 도시에(docs/DESIGN_AUDIT_PROM_20260625.md) 1순위 염탐 포인터 — 무작정 가지 말고 먼저 훔칠 곳 ──
#    핵심: 13건 다수는 LakatoTree repo *안에* 정답 패턴 존재. 외부 필수 fetch 는 TweetyProject(AGM oracle) 1개.
_PROM_REFS: dict[str, str] = {
    "H1_qualitative_self_report":   "judgement_service.py:250-260 + heuristic.py:81 negative_heuristic(touched∩hard_core 도출값화) · simple-evals/deepeval 블라인드 grader 분리",
    "H2_human_verdict_floor_bypass": "judgement_service.py:110-148 + GIT/phoenix annotation 모델(annotator_kind+user_id FK) → KG 'Argument(actor≠author)' 존재쿼리 · in-toto DSSE",
    "H3_judge_script_sha_client":   "longinus.py:27-38(정규식→python ast SymbolResolver) + bhgman longinus_sha256_daemon(서버 재계산 완본) · harness.py:111 sha코드를 서버로 이동",
    "H4_demote_hardcore_unguarded": "agm.py revision/HardCoreProtected 이미 존재 → demote_canonical 을 revision(contradicts=[old],allow_hard_core)로 재작성 · TweetyProject oracle(fetch #1)",
    "M1_rebuild_self_report_measure": "rebuild.py:66-67(measurer==producer) + lineage.py kind='measurement' Derivation + adapters.py OpenLineage measurer 별개 RunEvent · reprotest 변주2회",
    "M2_harness_silent_swallow":    "harness.py:145-148(_submit_and_judge 응답 무검사) → self._http가 (status,body) 반환·4xx/verdict=None raise · GIT/langgraph _retry(raise=default)",
    "M3_unconfirmed_counted_as_hit": "fertility.py:22 novel_confirmed 게이트(이미 정답) → metrics.py:71 prediction_hits 를 confirmed 로 승격 · Beta-Bernoulli reward 무결성",
    "M4_raises_question_unmaterialized": "writer.py:223-241(RAISES_QUESTION write=0,read=3) → link_raised_questions writer 추가 · graphiti bi-temporal · laudan.py 불가침(공급층 결함)",
    "M5_rescore_toctou":            "omd/omd_server/core.py:858-972(단일 임계구역+fence+멱등) + register_prediction:195-215(정답 단일-statement WHERE 가드) 답습",
    "M6_posthoc_prediction":        "judge.py:93-95 dead PredictionLocked 연결 + register 는 judged_at/registered_at IS NULL 일때만 SET(immutable) · OSF frozen+amendment·RFC3161",
    "M7_ci_no_sorry_unenforced":    "ci.yml:84-97(bare lake build) → Pidna.lean set_option warningAsError true + 핵심정리 #print axioms allow-list · mathlib4 반면교사",
    "M8_doubt_resolution_actor":    "claim.py:124-144(_resolved_doubt_ids actor 무대조) + argue.py:21-37 self-attack 제외 · NIST RBAC SoD",
    "M9_external_readback_off":     "_vendor/ooptdd/backends/conformance.py(이미 진짜 ship→독립query→compare 왕복) → MarquezBackend 확장 · Pact actor 분리 · CI hermetic ON",
}


# ── KG 거울용(sync_lakatos_programme_to_kg.py 단일 진실) — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: AuditNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=f"[{n.severity}] {n.story}  (근거 {n.evidence})"
                + (f"  [PROM 1순위] {_PROM_REFS[n.tag]}" if n.tag in _PROM_REFS else ""),
        limitation=(f"novel!=개선 (judge P2 독립): improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "하드코어 추측: 입력 영수증 바인딩"),
        algorithm="design-audit-fix" if pred else "conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in AUDIT_NODES]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"[{n.severity}] {n.tag}: {n.prediction.novel_prediction} (guard: {n.guard_test}; 근거 {n.evidence})")
    for n in AUDIT_NODES if n.prediction is not None
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"감사 guard receipt: {landed}/{len(rc) or 0} green (tests/test_design_audit_*.py)\n")
    rows = run(rc)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    n_closed = sum(1 for r in rows if r["status"] == "CLOSED")
    for r in rows:
        if r["status"] == "ROOT":
            tail = "(추측·루트)"
        elif r["verdict"].startswith("pending"):
            tail = r.get("note", "")
        else:
            tail = f"novel={r.get('novel')} improved={r.get('improved')} — {r.get('reason')}"
        print(f"  [{r['severity']:6}] {r['tag']:34} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in AUDIT_NODES if n.prediction is not None)
    print(f"\n총 {n_findings} 결함: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0). 고치고 guard 착륙시키면 자동 채점.")
    print("KG 거울: LakatosTree_LakatoTree_DesignAudit_20260625")
