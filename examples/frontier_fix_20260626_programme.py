"""LakatoTree frontier-fix(2026-06-26) 피드백 하네스 — 심층점검이 찾은 *다음 frontier* 6건을 엔진 자신의 R&D 백로그로 도그푸드.

선행: examples/design_audit_20260625_programme.py 가 13건(H1~H8/M1~M12)을 닫았다. 그 13건을 런타임
revert-proof 로 다시 깨려고 77-에이전트 적대점검(2026-06-26)을 돌렸더니, 닫힌 fix 들이 *submit-측 유도*에
escape hatch 를 남겼고 커널이 ground-truth 로 신뢰하는 입력(judge 의 cross-metric novel_measured)은 그대로
영수증 없는 client float 였다. 이 하네스는 그 6건을 등재한다.

★규율(design_audit_20260625 와 동일): 노드는 verdict 를 손입력하지 않는다. 각 발견은 사전등록 Prediction +
독립 NovelTarget + *명명된 guard_test* 만 들고 OPEN 으로 앉는다. guard 미착륙 = 정직한 pending(가짜 green 0).

★★ FG-2 교정(이 하네스의 존재이유 중 하나 = 우선순위 #6): 선행 하네스 run() 은 improved 와 novel 을 *같은*
pytest 비트 하나에서 유도해(design_audit_20260625_programme.py run() ≈426-427) judge() 가 progressive 외에는
낼 수 없었다 — "엔진이 자기를 채점"의 재귀가 부분적 연극이었다(채점력 0, guard 적대성에 100% 의존).
이 하네스는 발견당 *독립 이중 가드*를 둔다:

    guard_defect    → 개선축(measured)     : client 우회/결함이 *죽었나* (음성 오라클)
    guard_mechanism → novel축(novel_measured): 서버 재유도/독립조달 *메커니즘이 있나* (양성 오라클)

두 축이 서로 다른 테스트(receipt 의 다른 비트)라서 judge() 가 *진짜로 판별*한다:

    defect닫힘 ∧ mechanism존재  → progressive  (진짜 fix)
    defect닫힘 ∧ mechanism없음  → partial      (우회만 막고 서버유도 없음 = 라카토스 ad-hoc 땜빵)
    defect열림 ∧ mechanism존재  → equivalent   (메커니즘 추가했으나 구멍 여전 = 미완 fix 적발)
    둘 다 미착륙               → pending(no-receipt)

이로써 "client 제출값=주장(defect축), 서버 재유도/독립조달값=판관(mechanism축)" 독트린이 점수 *구조*에
박힌다 — 우회를 지우기만 한 패치는 결코 progressive 가 못 된다(partial 천장). _discrimination_demo() 가
이 4-칸을 합성 receipt 로 증명한다(이 하네스가 FG-2 를 반복하지 않음을 by-construction 으로).

심층점검 출처: LakatoTree deep-dive 2026-06-26 (77 agent/4.1M tok, 확정 28/기각 10, HIGH 직접 라인확인).
# KG: span_lakatotree_frontier_fix_20260626 / LakatosTree_FrontierFix_20260626
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
# frontier-fix guard 들이 착륙할 전용 파일 패턴(아직 비어있음 = 전부 pending). 고쳐질 때마다 하나씩 green.
_RECEIPT_GLOB = "tests/test_frontier_fix_*.py"
_TREE = "LakatosTree_FrontierFix_20260626"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 frontier-fix guard 테스트를 돌려 {test_func: passed} 수집(self-report 아님).

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
class AuditNode:
    tag: str
    severity: str                 # HIGH / SECURITY / MEDIUM / ROOT
    parent: str | None
    evidence: str                 # 점검이 직접 확인한 file:line
    story: str                    # 무엇이 왜 결함인가 + [PROM] 어디서 무엇을 훔쳐 풀지
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(server-mechanism) — *독립* metric
    guard_defect: str = ""        # 개선축 측정: 결함/우회가 닫혔음을 증명하는 *음성* 오라클(green=우회 죽음)
    guard_mechanism: str = ""     # novel축 측정: 서버 재유도/독립조달 메커니즘 존재 *양성* 오라클(green=메커니즘 산다)
    prom: str = ""                # 1순위 염탐대상(대부분 이미 로컬 — deep-dive 가 정답패턴 식별)


# 루트 추측(채점 대상 아님) + 6개 OPEN frontier 노드.
AUDIT_NODES: tuple[AuditNode, ...] = (
    AuditNode(
        tag="receipt_binding_v2_hardcore", severity="ROOT", parent=None,
        evidence="deep-dive 2026-06-26 / judge.py(verdict 도출 by-construction) vs submit 유도(soft spot)",
        story="하드코어 추측(v2): 약속 #2(자기채점 차단)는 verdict-*도출*에선 by-construction(verdict_source "
              "server-set-only · force_of SSOT · Lean Rung.derived)이나, 직전 감사가 닫은 H1~H4 의 *submit-측 "
              "유도*에 client-제어 escape hatch 가 남았고 커널이 ground-truth 로 신뢰하는 입력(judge 의 "
              "cross-metric novel_measured)은 영수증 없는 client float 다. H3 가 judge_script_sha 에 한 '서버가 "
              "sha 의 판관'을 나머지 client-신뢰 입력(novel 측정·질적 sha·인간 actor)과 dead-on-wired 경로"
              "(eigentrust)·자기채점 하네스에 마저 민다. 불변식: **client 제출값=주장, 서버 재유도/독립조달값=판관.** "
              "(루트 — 채점 안 함)",
    ),

    # ───────────── HIGH: 커널이 신뢰하는 입력의 현실 바인딩 (thesis 의 머리) ─────────────
    AuditNode(
        tag="FF1_cross_metric_novel_client_float", severity="HIGH", parent="receipt_binding_v2_hardcore",
        evidence="judge.py judge() (≈127 novel=corroborated, ≈134 noindep 는 same-metric 만 발동) / novel_measured←schemas.py:102 TestResultIn→submit_test_result(≈369 ...novel_measured=r.novel_measured)",
        story="judge 의 sha-독립성 게이트(noindep)는 novel_target.metric_name==pred.metric_name 일 때만 발동한다. "
              "*다른* metric 의 NovelTarget(=dogfood/실프로그램 다수)은 novel=novel_target.corroborated(novel_measured) "
              "로만 확증되고 sha/영수증이 무관 — '진보'를 빚는 external measurement 가 client 가 POST 한 float 하나다. "
              "H6 의 서버 sha 재유도가 정작 progressive 를 빚는 cross-metric 게이트엔 안 닿는다(thesis 의 머리). "
              "[PROM] H3 longinus._recompute_script_sha 를 novel 축으로 확장(novel_script 본문 서버 재유도) "
              "또는 NovelTarget 기대값을 KG 에서 readback(M1 measurer≠producer 패턴) — 둘 다 로컬에 정답 존재.",
        prediction=Prediction(metric_name="cross_metric_novel_trusts_client_float", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="cross-metric novel 확증은 서버앵커(재유도 sha 또는 KG readback) 없이 progressive 못 빚는다",
                              closes_question="q-ff1-cross-metric-novel"),
        novel_target=NovelTarget(metric_name="cross_metric_novel_server_anchored",
                                 direction="higher", threshold=1.0),
        guard_defect="test_cross_metric_novel_bare_client_float_cannot_mint_progressive",
        guard_mechanism="test_cross_metric_novel_requires_server_readback_or_sha",
        prom="longinus._recompute_script_sha(novel_script 확장) / io.rebuild kind='measurement' readback / judge.py:134 게이트를 cross-metric 으로 확장",
    ),
    # ※ 2026-06-26 동시편집: 원래 FF2(qual_backed←client novel_sha)를 H10(commit 1dc0e3f)이 *빌드 중에* 닫았다.
    #   엔진 사전등록 불변성(M6 lock)이 이 노드의 예측 재작성을 409 로 거부 — 엔진이 제 하네스에 무결성을 적용했다.
    #   다시 쓰지 않고 분기: FF2 = 원래 결함(H10 이 닫음; guard 착륙 = H10 영수증). revert-proof 잔여 = 새 노드 FF2b.
    AuditNode(
        tag="FF2_h1_qual_backed_client_hatch", severity="HIGH", parent="FF1_cross_metric_novel_client_float",
        evidence="judgement_service.py qual_backed (원래 client r.novel_sha 문자열; H10/1dc0e3f 가 서버앵커 novel_server_sha 로 닫음) / schemas.py:103,125",
        story="[H10(1dc0e3f) 동시편집으로 닫힘] 질적 self-report 차단(H1)이 qual_backed 면 억제되는데 qual_backed 가 "
              "client r.novel_sha 문자열+bool 로 계산되던 결함 — H10 이 서버앵커 novel_server_sha 로 교체해 닫았다. "
              "guard 착륙 시 progressive 는 H10 fix 의 영수증(손입력 0). *revert-proof* 여부는 FF2b 가 따로 본다.",
        prediction=Prediction(metric_name="qual_self_report_suppressed_by_client_fields", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="qual_backed 는 서버재계산 sha 로만 — client novel_sha 문자열+bool 로 self-report 표식 못 끈다",
                              closes_question="q-ff2-qual-hatch"),
        novel_target=NovelTarget(metric_name="qual_backing_uses_server_anchored_sha",
                                 direction="higher", threshold=1.0),
        guard_defect="test_client_novel_sha_string_does_not_clear_qual_self_report_on_submit",
        guard_mechanism="test_qual_backing_requires_server_recomputed_sha",
        prom="judgement_service.py novel_server_sha 재사용(H10 완료) / revert-proof 잔여는 FF2b",
    ),
    AuditNode(
        tag="FF2b_h10_revert_proof", severity="HIGH", parent="FF2_h1_qual_backed_client_hatch",
        evidence="가드 tests/test_design_audit_h1.py(spine.synthesize_promotion 격리만 — submit 음성오라클·revert-proof 부재) / deep-dive FG-1",
        story="H10 이 qual_backed 를 서버앵커로 바꿨으나(FF2 닫힘) 그 fix 가 *load-bearing* 인가는 별개다(deep-dive FG-1): "
              "현 H1 가드는 spine 격리만 운동해 submit-측 qual_backed 를 client sha 로 되돌려도 RED 가 안 된다. 진짜 봉인 = "
              "submit 경로 음성 오라클 + line 을 client sha 로 패치하면 RED 되는 revert-proof 메타테스트. [PROM] "
              "test_design_audit_h1 를 submit 경로로 확장 + revert-proof 메타가드.",
        prediction=Prediction(metric_name="h10_qual_backed_lacks_submit_revert_guard", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="qual_backed 서버앵커가 submit 경로 음성 오라클로 박혀 client sha 로 되돌리면 RED",
                              closes_question="q-ff2b-revert-proof"),
        novel_target=NovelTarget(metric_name="h10_qual_backed_revert_turns_guard_red",
                                 direction="higher", threshold=1.0),
        guard_defect="test_qual_backed_submit_path_has_negative_oracle",
        guard_mechanism="test_reverting_qual_backed_to_client_sha_turns_guard_red",
        prom="tests/test_design_audit_h1 submit 확장(spine 격리 아님) / revert-proof 메타가드(qual_backed 를 r.novel_sha 로 패치→RED)",
    ),
    AuditNode(
        tag="FF3_h2_human_attestation_client_authored", severity="HIGH", parent="receipt_binding_v2_hardcore",
        evidence="evidence_claim_service.py add_critique (≈101 SET a.by=$by,a.kind=$kind ← ≈104 by=c.by,kind=c.kind, client) / judgement_service.py floor has_human (≈207-209, ≈207 'Sybil 한계: by 가 노드 작성자와 다른지 미강제') / schemas.py:137-138(CritiqueIn by:str='',kind:str='doubt',무인증)",
        story="CANONICAL floor 의 has_human('진짜 human attestation')이 완전 client-authored 행이다 — add_critique 가 "
              "by/kind 를 client 값 그대로 SET 하고(인증 없음, node author 와 다른지 미검사) floor 는 kind∈{evaluation,"
              "verdict}+비어있지않은 by 만 본다. 코드가 자인(:211 'by 가 노드 작성자와 다른지는 ... 미강제'). client 가 "
              "critique(kind='evaluation',by='human:anyone')+set_verdict(human_verdict=True)로 내부 증명노드의 floor 를 "
              "연다. H2 가드는 by='human:gira'(client 문자열)로 floor 열림을 단언 → 위조경로를 양성오라클이 축복. "
              "[PROM] node author 의 KG 식별(FoundationRequirement 선결) + GIT/phoenix annotation 모델(annotator_kind+"
              "user_id) → actor≠author 존재쿼리; H8 self-vouch AF(by 보존)와 동일 척추.",
        prediction=Prediction(metric_name="human_floor_accepts_client_authored_attestation", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="floor has_human 은 actor≠node-author 인 KG-영속 human Argument 존재로만 충족",
                              closes_question="q-ff3-human-actor"),
        novel_target=NovelTarget(metric_name="human_attestation_actor_distinct_from_author",
                                 direction="higher", threshold=1.0),
        guard_defect="test_self_authored_human_attestation_does_not_open_floor",
        guard_mechanism="test_floor_requires_human_actor_distinct_from_node_author",
        prom="node author KG 식별(선결 Foundation) / evidence_claim_service AF by 보존(H8) / NIST RBAC SoD",
    ),
    AuditNode(
        tag="FF4_script_sha_arbitrary_absolute_read", severity="SECURITY", parent="FF1_cross_metric_novel_client_float",
        evidence="judgement_service.py _recompute_script_sha (≈155 if p.is_absolute→≈160 is_file 만, containment 부재; ≈163-165 relative=traversal 거부; ≈169 read_bytes 무cap, ≈172 hashlib.sha256) / 미사용: server.file_hashing.file_sha(chunk=1<<20)",
        story="H3/H6 의 서버측 judge-script sha 재유도가 매 test_result submit 마다 client 문자열 r.script 를 먹는다. "
              "relative 경로는 traversal 거부하지만 *absolute* 경로는 containment 없이 is_file() 만 보고 read_bytes() "
              "전체를 메모리에 올린다 → script='/etc/passwd' 가 그 파일 sha256 을 반환(실측 확인), 무cap read 는 "
              "대용량 파일 RAM-exhaustion. LAKATOS_API_TOKEN 미설정(기본 dev 런치) 시 무인증. 같은 out-of-root 탈출이 "
              "'file::symbol' 분기의 longinus.resolve_symbol(root/file, file 절대면 root 폐기)에도 있음. ROB-5 잔존. "
              "[PROM] server.file_hashing.file_sha(streaming chunked) 이미 존재 → 재유도 경로가 이걸 쓰고 ROOT "
              "containment(절대경로도 root.parents 검사)+size cap 부착.",
        prediction=Prediction(metric_name="script_sha_reads_arbitrary_absolute_file", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="root 밖 절대경로 script 는 거부(traversal 과 대칭) + 해시는 streaming+size-cap",
                              closes_question="q-ff4-script-sha-containment"),
        novel_target=NovelTarget(metric_name="script_path_root_contained_and_streamed",
                                 direction="higher", threshold=1.0),
        guard_defect="test_absolute_script_path_outside_root_is_rejected",
        guard_mechanism="test_script_sha_uses_streaming_capped_file_hash",
        prom="server.file_hashing.file_sha(chunk=1<<20) / longinus.resolve_symbol root/file 절대경로 검사 / 무인증 surface=opt-in token",
    ),

    # ※ 2026-06-26 동시편집: 원래 FF5 헤드라인(eigentrust 가 서빙 /metrics 에서 死)을 D1(working-tree)이 *빌드 중에*
    #   닫았다 — repository.load_tree_data 가 이제 observations 방출(≈171,181), read_models orphan 삭제(39줄). 엔진
    #   사전등록 lock 이 예측 재작성 거부 → 분기: FF5 = 원래 결함(D1 이 닫음). trust fail-open 기본값 잔여 = 새 노드 FF5b.
    AuditNode(
        tag="FF5_eigentrust_dead_failopen_trust", severity="HIGH", parent="receipt_binding_v2_hardcore",
        evidence="repository.load_tree_data observations(원래 키 없음; D1 이 ≈171,181 방출로 닫음) / read_models orphan 로더 삭제(39줄) / compute_tree_metrics td.get('observations') 게이트",
        story="[D1(working-tree) 동시편집으로 닫힘] 'eigentrust 가중 credence'가 서빙 /metrics 에서 死이던 결함(서빙 "
              "로더가 observations 미생성, 채우는 read_models.load_tree_data 는 orphan)을 D1 이 닫았다 — load_tree_data 가 "
              "이제 observations 를 방출해 eigentrust 가 실발동. guard 착륙 시 progressive 는 D1 영수증. trust *부재 "
              "기본값 fail-open* 은 FF5b 가 따로 본다.",
        prediction=Prediction(metric_name="eigentrust_credence_dead_and_trust_failopen", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="서빙 metrics 가 observations 를 채워 source_trust 가중이 실발동 + 신뢰부재는 fail-safe",
                              closes_question="q-ff5-eigentrust-wired"),
        novel_target=NovelTarget(metric_name="served_metrics_applies_source_trust_failsafe",
                                 direction="higher", threshold=1.0),
        guard_defect="test_served_metrics_path_downweights_low_trust_source",
        guard_mechanism="test_tree_service_loads_observations_and_defaults_failsafe",
        prom="read_models 통합(D1 완료) / fail-open 잔여는 FF5b",
    ),
    AuditNode(
        tag="FF5b_trust_failopen_default", severity="MEDIUM", parent="FF5_eigentrust_dead_failopen_trust",
        evidence="bayes.py:99 (st = v.get('source_trust', 1.0) 부재=최대신뢰) / bayes_factor 기본 source_trust=1.0(≈60) / trust.evidence_weight floor 0(명시 zero 만 중립화)",
        story="D1 이 dead-wiring 을 닫아도(FF5) 잔여 생존: trust 부재 기본값이 fail-open 이다 — branch_credence 의 "
              "v.get('source_trust', 1.0) 와 bayes_factor 기본 source_trust=1.0 이 신뢰 데이터 없는 출처에 *최대* 증거력을 "
              "준다. evidence_weight(floor=0)는 *명시* zero-trust 만 중립화하고 *부재*는 1.0 → no-self-report 엔진서 가장 "
              "나쁜 기본값. [PROM] 미지정 경로를 명시 fail-safe(중립-BF 또는 하한)로.",
        prediction=Prediction(metric_name="trust_absent_defaults_to_max_failopen", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="source_trust 미지정 출처는 최대신뢰(1.0)가 아니라 fail-safe 기본(중립/하한)을 받는다",
                              closes_question="q-ff5b-trust-failopen"),
        novel_target=NovelTarget(metric_name="trust_absent_defaults_failsafe",
                                 direction="higher", threshold=1.0),
        guard_defect="test_absent_source_trust_is_not_max_credulous",
        guard_mechanism="test_trust_default_floors_to_failsafe_not_one",
        prom="bayes.py:99/60 source_trust 미지정 fail-safe / trust.evidence_weight 부재 구분",
    ),

    # ───────────── META: 하네스가 스스로를 감사 (FG-2 — 우선순위 #6) ─────────────
    AuditNode(
        tag="FF6_dogfood_discriminates", severity="MEDIUM", parent="receipt_binding_v2_hardcore",
        evidence="design_audit_20260625_programme.py run() (≈426-427: improved_metric·novel_measured 둘 다 rc.get(n.guard_test) 한 비트) / 본 파일 run()+AuditNode(이중가드)",
        story="선행 하네스 run() 은 improved_metric 과 novel_measured 를 *같은* pytest 비트에서 유도해 judge() 가 "
              "green→progressive / red→pending 만 가능했다(cross-metric novel_target 라 sha 게이트도 무관) — partial/"
              "equivalent/rejected 도달불가 = '엔진이 자기 fix 를 채점'의 채점력 0, guard 적대성에 100% 의존. 이 "
              "하네스는 발견당 *독립 이중 가드*(guard_defect=개선축 음성오라클, guard_mechanism=novel축 양성오라클)로 "
              "고친다 → 우회만 막은 패치는 partial(천장), 메커니즘만 있고 구멍 여전은 equivalent 로 *판별*. 이 노드의 "
              "mechanism 은 이미 본 파일 run()/AuditNode 에 구현(코어수정 불요, 하네스 자체가 fix) → guard 착륙시 즉시 "
              "progressive. _discrimination_demo() 가 4-칸을 합성 receipt 로 증명. [PROM] 자기참조 — 선행 하네스 대비.",
        prediction=Prediction(metric_name="dogfood_judge_can_only_return_progressive", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="improved 와 novel 이 독립 두 가드에서 유도돼 judge() 가 partial/equivalent 도 낸다",
                              closes_question="q-ff6-dogfood-discriminates"),
        novel_target=NovelTarget(metric_name="dogfood_improved_and_novel_independently_sourced",
                                 direction="higher", threshold=1.0),
        guard_defect="test_dogfood_patch_without_mechanism_scores_partial_not_progressive",
        guard_mechanism="test_dogfood_improved_and_novel_read_from_distinct_guards",
        prom="이 파일 run() 의 이중가드 — 선행 design_audit_20260625_programme.py run()(≈426-427) 의 단일비트와 대비",
    ),
)


def _score(n: AuditNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)과 novel(novel축)이 *다른* 측정에서 온다(FG-2 교정)."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value   # 개선축: 결함 닫힘=baseline 아래로
    novel_measured = 1.0 if mech_present else 0.0                      # novel축: 메커니즘 존재=threshold 적중
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, severity=n.severity, parent=n.parent,
                verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 가 생성(손입력 0). 두 가드 미착륙 = 정직한 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in AUDIT_NODES:
        if n.prediction is None:                                       # 루트 추측
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:                                                   # receipt 미도래 = 정직한 pending
            out.append(dict(tag=n.tag, severity=n.severity, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, bool, bool, str]]:
    """FG-2 가 이 하네스에서 by-construction 으로 닫혔음을 증명 — judge() 가 4-칸을 *판별*한다.

    선행 하네스(단일비트)는 progressive/pending 만 냈다. 여기선 개선축과 novel축이 독립이라:
      (defect닫힘, mech있음) → progressive | (defect닫힘, mech없음) → partial
      (defect열림, mech있음) → equivalent  | (defect열림, mech없음) → equivalent
    """
    probe = AUDIT_NODES[1]   # FF1 (대표 노드)
    cases = [(True, True), (True, False), (False, True), (False, False)]
    return [(f"defect={dc}, mech={mp}", dc, mp, _score(probe, dc, mp)["verdict"]) for dc, mp in cases]


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: AuditNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=f"[{n.severity}] {n.story}  (근거 {n.evidence})"
                + (f"  [PROM] {n.prom}" if n.prom else ""),
        limitation=(f"novel!=개선 (judge P2 독립 이중가드): improve={pred.metric_name} / "
                    f"novel={n.novel_target.metric_name}" if pred else "하드코어 추측: 입력 영수증 바인딩 v2"),
        algorithm="frontier-fix" if pred else "conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in AUDIT_NODES]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"[{n.severity}] {n.tag}: {n.prediction.novel_prediction} "
              f"(guards: defect={n.guard_defect} / mechanism={n.guard_mechanism}; 근거 {n.evidence})")
    for n in AUDIT_NODES if n.prediction is not None
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"frontier-fix guard receipt: {landed}/{len(rc) or 0} green ({_RECEIPT_GLOB})\n")
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
        print(f"  [{r['severity']:8}] {r['tag']:38} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in AUDIT_NODES if n.prediction is not None)
    print(f"\n총 {n_findings} 결함: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0). 고치고 두 guard 착륙시키면 자동 채점.")
    print("\nFG-2 판별력 증명 (_discrimination_demo) — 선행 단일비트 하네스는 progressive/pending 만:")
    for label, _dc, _mp, verdict in _discrimination_demo():
        print(f"  {label:28} → {verdict}")
    print(f"\nKG 거울: {_TREE}")
