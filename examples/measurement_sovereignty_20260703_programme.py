"""측정주권(측정 정직) 캠페인 programme — 재현확인 ≠ 값소유 (2026-07-03 PROM, A- → A 승급 관문).

문제상황: 독립 평가(docs/lakatotree-evaluation-20260703.md)와 측정주권 PROM 이 수렴 — 원장은
client float 를 위조불가하게 *봉인·운반*하나 소유하지 않는다. replay 는 `return v.verified`
bool(재유도값 서버경계 폐기, LAKATOS_REPLAY_EXEC 기본 OFF=dead path)의 **재현확인**이고,
:VerdictReceipt(RECEIPT_FIELDS 12필드)엔 measurement_grade 가 없어 진짜 외부검증 값과 위조
float 가 같은 형식의 영수증을 받는다. **값소유**(서버 재유도 SSOT)는 AG3 착륙 대상이다.

하드코어 추측: 측정 정직 = ① 문서·영수증이 이 한계선을 등급(grade)으로 투명하게 말하고
② 값소유·신원(서명)이 검증가능한 부분집합부터 착륙하는 것. 판결-도출 위조불가(judge 결정론·
Lean)와 측정값 위조불가는 별개 주장이며, 혼용은 과대표현이다.

★규율: verdict 손입력 금지 — 전부 judge() 생성. guard 미착륙 = 정직 pending.
★★이중가드: guard_defect(음성 오라클 → 개선축 measured) + guard_mechanism(양성 오라클 →
novel축 novel_measured). 4-칸: 둘다닫힘→progressive · defect만→partial · mech만→equivalent ·
둘다미착륙→pending. 캠페인 가드 파일 명명: tests/fix_harness/test_ag<N>_rsov<M>_*.py.

# KG 거울: LakatosTree_MeasurementSovereignty_20260703
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

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 측정주권 가드가 착륙하는 전용 파일 패턴들(비면 전부 pending). AG 슬라이스당 1파일 × 2가드.
_RECEIPT_GLOBS = ("tests/fix_harness/test_ag*_rsov*.py", "tests/fix_harness/test_de1_*.py",
                  "tests/fix_harness/test_fe*_*.py")   # FERMENT(병렬 독립) 슬라이스 가드
_TREE = "LakatosTree_MeasurementSovereignty_20260703"


def receipt() -> dict[str, bool]:
    """외부 측정 = 이 repo .venv pytest 로 캠페인 guard 테스트를 돌려 {test_func: passed} 수집
    (self-report 아님). guard 파일 0개면 빈 dict → 전부 정직 pending."""
    matches = [m for g in _RECEIPT_GLOBS for m in glob.glob(os.path.join(_ROOT, g))]
    if not matches:
        return {}
    globs = " ".join(_RECEIPT_GLOBS)
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest {globs} -v --no-header -p no:cacheprovider 2>&1")
    out = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True).stdout
    res: dict[str, bool] = {}
    for line in out.splitlines():
        m = re.search(r"\b(test_\w+)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b", line)
        if m:
            name, ok = m.group(1), m.group(2) == "PASSED"
            res[name] = res.get(name, True) and ok
    return res


@dataclass(frozen=True)
class SovNode:
    tag: str
    dimension: str                # AG# / PROM 척추 표지
    parent: str | None
    evidence: str                 # 코드 실측 앵커(file:symbol) / 정찰 wf id
    story: str                    # anomaly → problemshift
    prom: str                     # 실 기제가 어디에 사는가
    prediction: Prediction | None = None      # 개선축(defect-closed)
    novel_target: NovelTarget | None = None   # novel축(mechanism 실재)
    guard_defect: str = ""
    guard_mechanism: str = ""


NODES_DEF: tuple[SovNode, ...] = (
    SovNode(
        tag="rsov_root", dimension="하드코어 / 측정주권 PROM 한줄결론", parent=None,
        evidence="server/app.py:_producer_replay_for_node(return v.verified) · lakatos/verdicts.py:RECEIPT_FIELDS(12필드, measurement_grade 부재) · 정찰 wf_48a54c6b",
        story="하드코어 추측: 원장은 client float 를 봉인·운반만 한다(재현확인 ≠ 값소유). 측정 정직 = "
              "한계선의 투명한 grade + 값소유·신원의 부분집합 착륙. 혼용 과대표현이 anomaly. (루트 — 채점 안 함)",
        prom="척추 AG1(어휘 한계선)→AG2(RCE 봉합)→DE1(submit 분해)→AG3(값소유 keystone)→AG4~AG7",
    ),
    SovNode(
        tag="ag1_rsov0_doc_honesty", dimension="AG1 어휘 한계선 (R-SOV-0)", parent="rsov_root",
        evidence="docs/ADR-measurement-sovereignty-20260703.md · judges/ag1_rsov0_doc_honesty.py(RED 실측 metric=3) · 정찰 wf_48a54c6b 확정 3건",
        story="정본 문서가 코드를 앞지른다 — TOUCH_THE_SKY 는 미구현 G-Web 재fetch 를 현재시제 '닫는다'로, "
              "'거짓말할 수 없는'을 무각주로, README 는 'an external measurement' 를 무단서로 서술(실제는 "
              "client float 운반, spine.py 자인). problemshift: 재현확인/값소유 어휘를 ADR 로 잠그고 확정 "
              "3건을 교정 + claim↔code tripwire(AG3/AG6 착륙 시 RED 로 ADR 개정 강제)를 기계 가드로 상주.",
        prom="docs/ADR-measurement-sovereignty-20260703.md + tests/fix_harness/test_ag1_rsov0_doc_honesty_20260703.py",
        prediction=Prediction(metric_name="ag1_unqualified_overclaims", direction="lower",
                              baseline_value=3.0, noise_band=0.0,
                              novel_prediction="ADR 실재 + 필수 어휘 + claim↔code 1:1 tripwire 가 기계 가드로 green(어휘 한계선 잠금)",
                              closes_question="q-rsov0-vocab-lock"),
        novel_target=NovelTarget(metric_name="ag1_adr_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_confirmed_overclaims_are_dead",
        guard_mechanism="test_adr_exists_and_pins_code",
    ),
    SovNode(
        tag="ag2_rsov1_replay_rce", dimension="AG2 replay RCE 봉합 (R-SOV-1)", parent="ag1_rsov0_doc_honesty",
        evidence="server/app.py:_safe_replay_argv+_apply_replay_rlimits · judges/ag2_rsov1_replay_rce.py(RED 실측 4벡터) · 정찰 wf_48a54c6b",
        story="replay 실행 경로가 submit 의 FF4 격리를 우회했다 — replay_command 가 client judge_script/"
              "result_path 를 f-string 결합하고 _replay_run 이 그대로 subprocess. 3벡터: 스크립트 격리부재"
              "(임의 절대경로/traversal)·judge_script='-c' argv 인젝션(python -c <rp>)·setrlimit 부재"
              "(fork/mem/disk-DoS). LAKATOS_REPLAY_EXEC 기본 OFF=dead path 라 실피해 0 이나 GO1(exec 기본-ON)의 "
              "절대 선행조건. problemshift: 실행 경로가 sha 재유도와 *같은* 격리(isolate_script_file 단일 출처)를 "
              "쓰게 하고 — python 계열만·스크립트=허용루트 실존파일·result_path flag 거부 → argv/traversal 봉쇄 — "
              "+ preexec_fn setrlimit(CPU/AS/FSIZE/CORE 유한 상한). fork-bomb 완전차단·seccomp=컨테이너/운영자.",
        prom="server/app.py _safe_replay_argv + _apply_replay_rlimits + judgement_service.isolate_script_file(모듈 정본)",
        prediction=Prediction(metric_name="ag2_open_rce_vectors", direction="lower",
                              baseline_value=4.0, noise_band=0.0,
                              novel_prediction="4 RCE 벡터가 side-effect 없이 거부되고 정직 스크립트는 유한 rlimit 하에 실행(이중가드 green)",
                              closes_question="q-rsov1-exec-path-rce"),
        novel_target=NovelTarget(metric_name="ag2_rce_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_rce_vectors_are_rejected",
        guard_mechanism="test_honest_replay_runs_under_finite_rlimits",
    ),
    SovNode(
        tag="de1_godmethod_split", dimension="DE1 godmethod 분해 (판결 seam 추출)", parent="ag2_rsov1_replay_rce",
        evidence="server/contexts/tree/judgement_policy.py(순수 3함수) · judges/de1_godmethod_split.py · judgement_service.submit_test_result(510, 344줄)",
        story="submit_test_result 는 344줄 godmethod — load·freshen·sha검증·write-cert·judge·강등체인·"
              "eureka·state·CAS·prov·fsck·history 를 한 메서드에 결합. AG3(값소유/measurement_grade)·"
              "AG4(재현성 partial 천장)·AG5(attested grade)가 편집할 *판결 결정 seam* 이 I/O 오케스트레이션에 "
              "묻혀 있어 착지가 위험. problemshift: 결정 seam 3종(강등체인 apply_verdict_demotes·질적플래그 "
              "qualitative_flags·receipt 조립 build_receipt_fields)을 순수 함수로 추출 — 거동 불변(1572 회귀 "
              "green)·hex 계약 유지(import-linter 3/3)·4사분면 특성화 골든 고정. AG3+ 는 이제 순수 seam 을 확장.",
        prom="server/contexts/tree/judgement_policy.py + judgement_service 위임(3 call-site) + 특성화 골든",
        prediction=Prediction(metric_name="de1_unextracted_seams", direction="lower",
                              baseline_value=3.0, noise_band=0.0,
                              novel_prediction="판결 seam 3종이 순수 함수로 추출되고 4사분면 골든+RECEIPT_FIELDS 1:1 만족(거동 불변)",
                              closes_question="q-de1-godmethod-split"),
        novel_target=NovelTarget(metric_name="de1_characterization_golden_green", direction="higher", threshold=1.0),
        guard_defect="test_demote_chain_golden_is_exact",
        guard_mechanism="test_receipt_fields_match_sealed_set",
    ),
    SovNode(
        tag="ag3_value_ownership", dimension="AG3 값소유 keystone (R-SOV V1)", parent="de1_godmethod_split",
        evidence="lakatos/verdicts.py:RECEIPT_FIELDS(13필드, measurement_grade) · server/contexts/tree/judgement_policy.py:resolve_measurement · server/app.py:_producer_replay_submit · judges/ag3_rsov3_value_ownership.py(RED 실측 gap=2)",
        story="원장은 client float 를 봉인·운반만 했다 — measurement_grade 부재로 서버-재유도값과 위조 "
              "float 가 *같은 receipt_sha* 를 들고, replay 는 verified bool 만 남기고 v.regenerated 를 "
              "폐기했다. 게다가 submit 시 producer_replay_for_node 는 아직 persist 안 된 e.metric_value=None "
              "을 읽어 신규노드에서 항상 not_attempted(ordering 역전). problemshift: (a) measurement_grade "
              "(server_regenerated/client_asserted)를 RECEIPT_FIELDS 로 봉인 → 진짜검증≠위조가 다른 sha; "
              "(b) resolve_measurement 이 verified∧regenerated 부분집합에서만 regenerated 를 SSOT metric_value "
              "로 SCOPED 치환(외부/반증값 파괴 금지); (c) _producer_replay_submit 로 *들어온* 값을 직접 "
              "replay(ordering 교정). 라이브 발효는 LAKATOS_REPLAY_EXEC(기본 OFF) → 코드완료·dead-σ, GO1 대기.",
        prom="lakatos/verdicts.py measurement_grade + judgement_policy.resolve_measurement + judgement_service submit 배선 + app._producer_replay_submit",
        prediction=Prediction(metric_name="ag3_value_ownership_gaps", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="measurement_grade 봉인(sha 를 가름) + verified replay 가 regenerated 를 SSOT 로 치환(값소유 SCOPED, 이중가드 green)",
                              closes_question="q-rsov3-value-ownership"),
        novel_target=NovelTarget(metric_name="ag3_value_ownership_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_verified_replay_owns_value_not_client",
        guard_mechanism="test_measurement_grade_sealed_in_receipt_fields",
    ),
    SovNode(
        tag="ag4_reproducibility_ceiling", dimension="AG4 재현성 천장 (R-SOV V2)", parent="ag3_value_ownership",
        evidence="lakatos/assurance.py:GATE_REPRODUCIBILITY_CEILING(anchored×submit) · server/contexts/tree/judgement_policy.py:apply_verdict_demotes(재현성 천장 branch) · server/app.py:_reproducible_for_node(False=구조반증/None=불가) · judges/ag4_rsov4_reproducibility_ceiling.py(RED gap=2)",
        story="AG3 값소유는 서버가 값을 재유도한 부분집합만 소유한다. 그런데 재현성이 *구조적으로 반증*"
              "(lineage dangling/비-source root → _reproducible_for_node=False)된 anchored 노드도 여전히 "
              "progressive 로 봉인돼 CANONICAL 로 오를 수 있었다 — 재현불가 측정이 최강 주장 후보가 되는 구멍. "
              "problemshift: anchored tier 게이트(assurance SSOT GATE_REPRODUCIBILITY_CEILING)를 무장하고 "
              "apply_verdict_demotes 가 (게이트 ∧ reproducible is False ∧ progressive)를 partial"
              "(reproducibility_refuted)로 **천장**(하드 409 아님, 값 보존, CANONICAL 은 못 열되). ★핵심 dead-σ: "
              "불가 None(result_path 없음/sha 미검증)은 천장 안 함(부재≠반증) — 라이브 노드(result_path='')는 "
              "전부 None → **무회귀**(1582 green). 천장≠거부, 불가None≠불일치False.",
        prom="lakatos/assurance.py 게이트 비트 + judgement_policy.apply_verdict_demotes 천장 branch + judgement_service submit 배선(reproducible+gate)",
        prediction=Prediction(metric_name="ag4_reproducibility_ceiling_gaps", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="anchored 게이트 무장 + 구조반증(False)만 partial 천장하고 불가(None)/재현(True)은 progressive 보존(이중가드 green)",
                              closes_question="q-rsov4-reproducibility-ceiling"),
        novel_target=NovelTarget(metric_name="ag4_ceiling_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_reproducibility_refuted_caps_at_partial",
        guard_mechanism="test_ceiling_is_anchored_gate_and_none_never_caps",
    ),
    SovNode(
        tag="ag5_attested_grade", dimension="AG5 attested 측정등급 (R-SOV V3)", parent="ag4_reproducibility_ceiling",
        evidence="server/contexts/tree/judgement_policy.py:resolve_measurement(attested=) · server/contexts/tree/judgement_service.py:attested_by_did→resolve · lakatos/write_cert.py(G10 인프라 재사용) · judges/ag5_rsov5_attested_grade.py(RED gap=2)",
        story="AG3 는 measurement_grade 를 server_regenerated vs client_asserted 2단으로 봉인했으나, 비평 "
              "재프레이밍이 지목한 *신원(open-write)이 co-fundamental* — allow-list 서명(write-cert)으로 "
              "신원에 묶인 값은 익명 client float 보다 강한데 AG3 는 둘을 같은 client_asserted 로 뭉갰다. "
              "problemshift: 3단 provenance 사다리 server_regenerated > **attested** > client_asserted — "
              "유효 write-cert(G10 인프라, attested_by_did)가 붙으면 grade='attested'(값은 client 지만 "
              "비부인·신원바인딩)로 봉인. ★dead-σ: attested 는 서명 실재 시만 → 무-attestor 트리는 그대로 "
              "client_asserted(무회귀 1586 green). server_regenerated 가 attested 를 이긴다(재유도>서명). "
              "★스코프 정직: IDENT 의 '비가역 verb(canonical/delete) 서명강제'+cert verb-판별자는 미착륙 — "
              "FE5 auth_posture 관측화 선행(q-rsov5 open). 본 노드는 attested *grade* 사다리만 닫는다.",
        prom="judgement_policy.resolve_measurement(attested 3단 사다리) + judgement_service attested_by_did 배선",
        prediction=Prediction(metric_name="ag5_attested_grade_gaps", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="서명값이 attested 로 봉인되고(무서명=client_asserted 무회귀) server_regenerated>attested 순서 유지(이중가드 green)",
                              closes_question="q-rsov5a-attested-grade"),
        novel_target=NovelTarget(metric_name="ag5_attested_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_attested_cert_yields_attested_grade",
        guard_mechanism="test_grade_ladder_truth_table",
    ),
    SovNode(
        tag="fe5_auth_posture", dimension="FE5 auth_posture 관측화 (FERMENT)", parent="ag5_attested_grade",
        evidence="server/auth_posture.py:classify+open_posture_warning · server/app.py:_current_auth_posture(/version 공시)+_lifespan(open WARN) · judges/fe5_auth_posture.py(RED gap=2)",
        story="비평 #1: 무인증 DEFAULT(LAKATOS_API_TOKEN 미설정 → _bearer_auth no-op → 모든 mutating 요청 "
              "무인증)는 blast-radius=전 연구그래프인데 *보이지 않았다* — 신원(open-write)이 co-fundamental "
              "A-blocker인데 관측 불가. problemshift: 쓰기 인증 자세를 3값 사다리(token_required>"
              "irreversible_attested>open)로 분류(server/auth_posture.py 순수 모듈)하고 /version 이 공시 + open "
              "부팅은 loud WARN. ★확정결정 open-but-observable: 무토큰 부팅거부 NO(부팅 안 막고 경고로 공시). "
              "★irreversible_attested 는 AG5-IDENT(비가역 verb 서명강제) 착륙 시 live — 현재 taxonomy 슬롯만. "
              "이 관측화가 AG5-IDENT 의 명시적 선행조건(FE5→AG5-IDENT).",
        prom="server/auth_posture.py(순수 분류+경고) + app.py /version 공시 + _lifespan open WARN",
        prediction=Prediction(metric_name="fe5_auth_invisibility_gaps", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="3값 사다리 분류 + open 자세 loud WARN(token_required 무경보) — 무인증 open-write 가 /version·부팅로그로 관측가능(이중가드 green)",
                              closes_question="q-fe5-auth-posture-observable"),
        novel_target=NovelTarget(metric_name="fe5_auth_posture_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_open_boot_warns",
        guard_mechanism="test_posture_taxonomy",
    ),
    SovNode(
        tag="ag5b_verb_signed_irreversible", dimension="AG5-IDENT 비가역 verb 서명강제 (R-SOV V3)", parent="fe5_auth_posture",
        evidence="lakatos/write_cert.py:COMMAND_FIELDS(+verb) · lakatos/assurance.py:VERB_GATES[set_verdict_canonical]+GATE_WRITE_CERT · server/contexts/tree/judgement_service.py:set_verdict cert 블록 · judges/ag5b_rsov5_verb_signed_irreversible.py(RED gap=2)",
        story="AG5-V3 는 attested *grade*(값 provenance)를 닫았다. IDENT 는 *enforcement*: 비가역 verb"
              "(CANONICAL 승격)이 무인증으로 통과했고, cert 는 verb 에 안 묶여 submit 용 cert 를 canonical 에 "
              "재생(sign-X-execute-Y)할 여지가 있었다. problemshift: (a) write_cert.COMMAND_FIELDS 에 verb 추가 "
              "→ cert 를 verb 에 바인딩(submit-cert≠canonical-cert); (b) assurance VERB_GATES[set_verdict_"
              "canonical]에 GATE_WRITE_CERT 무장 + set_verdict 가 attestor 선언 트리의 CANONICAL 승격에 서명 cert "
              "강제(verb='set_verdict_canonical' 바인딩). ★dead-σ(FE5 open-but-observable): cert 강제는 트리가 "
              "attestor 선언 시만 — 무-attestor 트리는 무인증 CANONICAL 유지(무회귀 1610 green). FE5 관측화가 "
              "선행. VerdictIn.write_cert + CertCommandIn(metric_value/script_sha optional + verb) 스키마 확장.",
        prom="write_cert.COMMAND_FIELDS verb + assurance set_verdict_canonical GATE_WRITE_CERT + judgement_service.set_verdict cert 검증",
        prediction=Prediction(metric_name="ag5b_unsigned_irreversible_gaps", direction="lower",
                              baseline_value=2.0, noise_band=0.0,
                              novel_prediction="attestor 트리 CANONICAL 승격 서명강제 + cert verb-바인딩(submit-cert 를 canonical 에 재생 거부, 이중가드 green)",
                              closes_question="q-rsov5-open-write-identity"),
        novel_target=NovelTarget(metric_name="ag5b_ident_guard_green", direction="higher", threshold=1.0),
        guard_defect="test_canonical_requires_cert_on_attestor_tree",
        guard_mechanism="test_cert_is_verb_bound_sign_x_execute_y",
    ),
)


def _score(n: SovNode, defect_closed: bool, mech_present: bool) -> dict:
    """독립 두 축을 judge() 에 먹인다 — improved(개선축)와 novel(novel축)이 다른 측정에서 온다."""
    measured = 0.0 if defect_closed else n.prediction.baseline_value
    novel_measured = 1.0 if mech_present else 0.0
    v = judge(n.prediction, measured, n.novel_target, novel_measured)
    return dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                verdict=v.verdict,
                status="CLOSED" if v.verdict == "progressive" else "OPEN",
                novel=v.novel, improved=v.improved, reason=v.reason)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """프로그램을 엔진에 태운다 — verdict 는 judge() 생성(손입력 0). 가드 미착륙 = 정직 pending."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_DEF:
        if n.prediction is None:
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="canonical_stage", status="ROOT"))
            continue
        have = (n.guard_defect in rc) or (n.guard_mechanism in rc)
        if not have:
            out.append(dict(tag=n.tag, dimension=n.dimension, parent=n.parent,
                            verdict="pending(no-receipt)", status="OPEN",
                            note=f"guard 미착륙: defect={n.guard_defect} mechanism={n.guard_mechanism}"))
            continue
        out.append(_score(n, rc.get(n.guard_defect, False), rc.get(n.guard_mechanism, False)))
    return out


def _discrimination_demo() -> list[tuple[str, bool, bool, str]]:
    """judge() 가 4-칸을 판별함을 합성 receipt 로 증명(채점력 0 의 도그푸드 연극 아님)."""
    probe = NODES_DEF[1]   # ag1_rsov0_doc_honesty
    cases = [(True, True), (True, False), (False, True), (False, False)]
    return [(f"defect={dc}, mech={mp}", dc, mp, _score(probe, dc, mp)["verdict"]) for dc, mp in cases]


# ── KG 거울용 — verdict 는 stage 라벨만, 진보성은 run() judge() 권위 ──
def _kg_node(n: SovNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=f"[{n.dimension}] {n.story}  (근거 {n.evidence})"
                + (f"  [PROM] {n.prom}" if n.prom else ""),
        limitation=(f"novel≠개선 (독립 이중가드): improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "하드코어 추측: 재현확인 ≠ 값소유"),
        algorithm="measurement-sovereignty-problemshift" if pred else "hardcore-conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in NODES_DEF]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"[{n.dimension}] {n.tag}: {n.prediction.novel_prediction} "
              f"(guards: defect={n.guard_defect} / mechanism={n.guard_mechanism}; 근거 {n.evidence})")
    for n in NODES_DEF if n.prediction is not None
]

# 정직 OPEN — 이번 회차(AG5-IDENT)가 닫지 *못한* 것들. 척추 AG1~AG5(V3+IDENT)+FE5 착륙 완료 →
#   q-rsov1·q-rsov3·q-rsov4·q-rsov5a·q-rsov5(open-write-identity: AG5-IDENT 이 닫음)·q-fe5 는 내림.
#   ★잔여: CANONICAL 서명강제는 닫혔으나 delete/carve verb 게이팅은 미착륙(후속) + GO 잔여.
OPEN_QUESTIONS = [
    dict(name="q-rsov5b-delete-carve-signed",
         body="[AG5-IDENT 후속] CANONICAL 승격 서명강제는 착륙(q-rsov5). 남은 비가역 verb — delete_tree/"
              "carve 는 별 call-path(mutations/writer)라 아직 cert-게이팅 미착륙. 같은 verb-바인딩 cert 로 확장 가능."),
    dict(name="q-go1-replay-exec-live",
         body="[GO1/user] AG3 값소유는 코드완료·dead-σ(LAKATOS_REPLAY_EXEC 기본 OFF). 라이브 σ0→1 은 "
              "도그푸드(별 프로세스/ephemeral 격리) 실증 후 exec 기본-ON flip — user GO 대기."),
]


if __name__ == "__main__":
    rc = receipt()
    landed = sum(1 for ok in rc.values() if ok)
    print(f"측정주권 guard receipt: {landed}/{len(rc) or 0} green ({', '.join(_RECEIPT_GLOBS)})\n")
    rows = run(rc)
    n_open = sum(1 for r in rows if r["status"] == "OPEN")
    n_closed = sum(1 for r in rows if r["status"] == "CLOSED")
    for r in rows:
        if r["status"] == "ROOT":
            tail = "(하드코어 추측·루트)"
        elif r["verdict"].startswith("pending"):
            tail = r.get("note", "")
        else:
            tail = f"novel={r.get('novel')} improved={r.get('improved')} — {r.get('reason')}"
        print(f"  [{r['dimension']:32}] {r['tag']:24} → {r['verdict']:20} {tail}")
    n_findings = sum(1 for n in NODES_DEF if n.prediction is not None)
    print(f"\n총 {n_findings} problemshift: OPEN(pending) {n_open} · CLOSED(progressive) {n_closed}. "
          f"verdict 전부 judge() 생성(손입력 0).")
    print(f"정직 OPEN frontier {len(OPEN_QUESTIONS)}건: "
          + ", ".join(q["name"] for q in OPEN_QUESTIONS))
    print("\n판별력 증명 (_discrimination_demo):")
    for label, _dc, _mp, verdict in _discrimination_demo():
        print(f"  {label:28} → {verdict}")
    print(f"\nKG 거울: {_TREE}")
