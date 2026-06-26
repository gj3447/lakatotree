"""runtime-lean PROM — Python 런타임 전체검증 대신 Lean certificate 권한경계로 간다.

핵심 정직성:
  - Python/FastAPI/Neo4j 전체를 Lean 으로 직접 증명한다고 말하지 않는다.
  - Lean 이 검증할 수 있는 kernel transition/certificate 를 만들고,
    Python write-path 는 certificate 없이는 중요한 상태전이를 못 하게 만든다.
  - guard_test 가 착륙하기 전까지 모든 가지는 pending(no-receipt) 이다.

이 PROM 은 TOUCH_THE_SKY 의 "Python 도 자기보고 못 하게" 원칙을 formal/runtime 경계에 적용한다.
# KG: span_lakatotree_runtime_lean_20260626 / LakatosTree_RuntimeLean_20260626
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
_RECEIPT_GLOB = "tests/test_runtime_lean_*.py"


def receipt() -> dict[str, bool]:
    """외부 측정 = runtime-lean guard pytest 결과. guard 미존재면 빈 dict."""
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
class RuntimeLeanNode:
    tag: str
    parent: str | None
    evidence: str
    story: str
    prediction: Prediction | None = None
    novel_target: NovelTarget | None = None
    guard_test: str = ""
    prom: str = ""


NODES_DEF: tuple[RuntimeLeanNode, ...] = (
    RuntimeLeanNode(
        tag="certificate_hardcore",
        parent=None,
        evidence="README Formal foundation / formal/Pidna.lean / runtime Python boundary",
        story="하드코어: 런타임 전체를 Lean 이 직접 보증한다고 과장하지 않는다. 대신 중요한 상태전이는 "
              "Lean-checkable certificate 없이는 commit 할 수 없게 만든다. Python 은 실행자이지 판관이 아니다.",
    ),
    RuntimeLeanNode(
        tag="L1_transition_system",
        parent="certificate_hardcore",
        evidence="formal/Pidna.lean currently models kernel only",
        story="TreeState/NodeState/ReceiptForce/Promotion/Abandonment 를 Lean transition system 으로 올린다. "
              "현재 judge/bayes theorem 을 상태전이 헌법으로 확장하는 첫 단계.",
        prediction=Prediction(metric_name="runtime_transition_not_in_lean", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="Lean 에 promote/abandon/receipt-force 상태전이와 보존정리 추가",
                              closes_question="q-runtime-lean-transition-system"),
        novel_target=NovelTarget(metric_name="lean_transition_theorems_build",
                                 direction="higher", threshold=1.0),
        guard_test="test_lean_transition_system_builds_and_has_no_sorry",
        prom="Lean inductive state machine + existing Pidna Rung.derived reuse",
    ),
    RuntimeLeanNode(
        tag="L2_certificate_schema",
        parent="L1_transition_system",
        evidence="Python verdict/promotion writes currently rely on runtime tests and Longinus guards",
        story="Promotion/Canonical/Demotion/Abandonment 마다 입력 bundle + expected output + Lean checker result 를 "
              "담는 certificate JSON 스키마를 만든다. certificate 는 self-report 가 아니라 재검증 가능한 artifact.",
        prediction=Prediction(metric_name="state_transition_without_certificate_schema", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="certificate schema 가 pred/measurement/receipt/source hashes/output 를 모두 요구",
                              closes_question="q-runtime-lean-certificate-schema"),
        novel_target=NovelTarget(metric_name="certificate_schema_rejects_missing_receipt",
                                 direction="higher", threshold=1.0),
        guard_test="test_certificate_schema_rejects_missing_receipt_force",
        prom="JSON Schema/Pydantic boundary + Lean checker IO contract",
    ),
    RuntimeLeanNode(
        tag="L3_python_write_gate",
        parent="L2_certificate_schema",
        evidence="server write paths can mutate verdict state; current protection is distributed tests",
        story="server write path 는 certificate.valid 없으면 CANONICAL/former_canonical/scripted verdict mutation 을 거부한다. "
              "Python 이 'judge 통과'라고 주장하는 대신 checker receipt 를 요구한다.",
        prediction=Prediction(metric_name="write_path_accepts_uncertified_transition", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="verdict-mutating writes require valid certificate id/hash",
                              closes_question="q-runtime-lean-write-gate"),
        novel_target=NovelTarget(metric_name="uncertified_verdict_write_rejected",
                                 direction="higher", threshold=1.0),
        guard_test="test_uncertified_verdict_write_is_rejected",
        prom="reuse H9 verdict CAS class-lock + certificate verifier chokepoint",
    ),
    RuntimeLeanNode(
        tag="L4_io_three_valued_boundary",
        parent="L2_certificate_schema",
        evidence="ooptdd/readback has present/absent/inconclusive semantics, but runtime edges can drift",
        story="외부 I/O 는 Lean 안에서 현실을 증명하지 않는다. Present/Absent/Inconclusive 3치 관찰로만 core 에 들어오게 "
              "하고, unreachable/partial 은 pass 도 fail 도 아닌 inconclusive certificate 로 고정한다.",
        prediction=Prediction(metric_name="io_boundary_can_collapse_inconclusive_to_green", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="partial/unreachable readback cannot mint COUNTS receipt",
                              closes_question="q-runtime-lean-io-three-valued"),
        novel_target=NovelTarget(metric_name="inconclusive_io_cannot_certify_transition",
                                 direction="higher", threshold=1.0),
        guard_test="test_inconclusive_io_cannot_certify_transition",
        prom="ooptdd LTL3 semantics + force_of COUNTS/INCONCLUSIVE SSOT",
    ),
    RuntimeLeanNode(
        tag="L5_lean_python_trace_equivalence",
        parent="L1_transition_system",
        evidence="Lean model and Python implementation are currently coupled by tests, not generated code",
        story="Lean evaluator 와 Python core 가 같은 golden trace 에서 같은 verdict/credence/force 를 내는지 검사한다. "
              "이건 Python 전체증명이 아니라 모델-구현 drift 감지다.",
        prediction=Prediction(metric_name="lean_python_semantics_can_drift", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="shared JSON golden traces pass in Lean checker and Python",
                              closes_question="q-runtime-lean-trace-equivalence"),
        novel_target=NovelTarget(metric_name="lean_python_golden_trace_equivalent",
                                 direction="higher", threshold=1.0),
        guard_test="test_lean_python_golden_trace_equivalence",
        prom="golden trace corpus + lake exe checker + pytest comparison",
    ),
    RuntimeLeanNode(
        tag="L6_no_sorry_axiom_gate",
        parent="L1_transition_system",
        evidence="lake build alone does not fail on sorry unless warning is escalated",
        story="formal job 은 build success 뿐 아니라 no-sorry/no-unapproved-axiom 을 gate 한다. certificate checker 가 "
              "sorryAx 위에 서면 전체 권한경계가 종이문이 된다.",
        prediction=Prediction(metric_name="formal_ci_can_pass_with_sorry", direction="lower",
                              baseline_value=1.0, noise_band=0.0,
                              novel_prediction="CI detects sorry/unauthorized axioms and fails",
                              closes_question="q-runtime-lean-no-sorry-ci"),
        novel_target=NovelTarget(metric_name="sorry_in_formal_fails_ci",
                                 direction="higher", threshold=1.0),
        guard_test="test_formal_ci_rejects_sorry_and_unapproved_axioms",
        prom="set_option warningAsError true + #print axioms allow-list",
    ),
)


def run(rc: dict[str, bool] | None = None) -> list[dict]:
    """PROM 을 엔진에 태운다. guard 미착륙은 pending, guard green 은 judge 가 progressive 생성."""
    rc = receipt() if rc is None else rc
    out: list[dict] = []
    for n in NODES_DEF:
        if n.prediction is None:
            out.append(dict(tag=n.tag, parent=n.parent, verdict="canonical_stage", status="ROOT"))
            continue
        if n.guard_test not in rc:
            out.append(dict(tag=n.tag, parent=n.parent, verdict="pending(no-receipt)",
                            status="OPEN", note=f"guard 미착륙: {n.guard_test}"))
            continue
        measured = 0.0 if rc[n.guard_test] else n.prediction.baseline_value
        novel_measured = 1.0 if rc[n.guard_test] else 0.0
        v = judge(n.prediction, measured, n.novel_target, novel_measured)
        out.append(dict(tag=n.tag, parent=n.parent, verdict=v.verdict,
                        status="CLOSED" if v.verdict == "progressive" else "OPEN",
                        improved=v.improved, novel=v.novel, reason=v.reason))
    return out


def _kg_node(n: RuntimeLeanNode) -> dict:
    pred = n.prediction
    return dict(
        tag=n.tag,
        verdict="canonical_stage",
        parent=n.parent,
        comment=n.story + (f" [PROM] {n.prom}" if n.prom else "") + f" (근거 {n.evidence})",
        limitation=(f"improve={pred.metric_name} / novel={n.novel_target.metric_name}"
                    if pred else "Python runtime 전체증명 과장 금지"),
        algorithm="runtime-lean-certificate" if pred else "conjecture",
        metric_value=None,
        questions=[pred.closes_question] if pred else [],
    )


NODES = [_kg_node(n) for n in NODES_DEF]

FRONTIER = [
    dict(name=n.prediction.closes_question, status="OPEN", closed_by=None,
         body=f"{n.tag}: {n.prediction.novel_prediction} (guard: {n.guard_test}; 근거 {n.evidence})")
    for n in NODES_DEF if n.prediction is not None
]


if __name__ == "__main__":
    rc = receipt()
    print(f"runtime-lean guard receipt: {sum(1 for ok in rc.values() if ok)}/{len(rc)} green\n")
    for row in run(rc):
        if row["status"] == "ROOT":
            tail = "(추측·루트)"
        elif row["verdict"].startswith("pending"):
            tail = row["note"]
        else:
            tail = f"novel={row['novel']} improved={row['improved']} — {row['reason']}"
        print(f"  {row['tag']:34} -> {row['verdict']:20} {tail}")
    print("\nKG 거울: LakatosTree_RuntimeLean_20260626")
