"""AG4/R-SOV V2 재현성 천장(reproducibility ceiling) — 측정주권 PROM 2026-07-03.

테제 후속(선행 [[measurement-sovereignty-prom-20260703]] AG3): 값소유(AG3)는 서버가 값을 재유도한
부분집합만 소유한다. AG4 는 *재현성 자체가 구조적으로 반증된*(lineage dangling/비-source root →
_reproducible_for_node=False) anchored-tier 노드를 progressive 밖 **partial 로 천장**한다 — 하드 409
아님(값 보존), CANONICAL 은 못 열되.

핵심 dead-σ 규율 **불가None≠불일치False**(관통위험): 재현성이 *불가*(None: result_path 없음/sha
미검증 = 증명 못 함)면 **천장 안 함**(부재≠반증) — 라이브 AG 노드 전부 result_path='' → None →
regression 0. *불일치*(False: 구조적 재현불가)일 때만 천장. 천장≠거부.

  guard_defect    = test_reproducibility_refuted_caps_at_partial (음성: 천장 제거 시 progressive 잔존 → RED)
  guard_mechanism = test_ceiling_is_anchored_gate_and_none_never_caps (양성: 게이트=anchored전용 ∧ None 무천장)

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag4_reproducibility_ceiling
"""
from __future__ import annotations

from lakatos import assurance
from server.contexts.tree.judgement_policy import VerdictDecision, apply_verdict_demotes
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result


# ── (A) 순수 결정 seam: apply_verdict_demotes 재현성 천장 진리표 ─────────────────────
def _demote(verdict="progressive", *, hc_derived=None, require_novel_anchor=False, novel=False,
            cross_metric_novel=False, novel_server_anchored=False,
            reproducible=None, reproducibility_ceiling=False):
    return apply_verdict_demotes(verdict, "ok", hc_derived=hc_derived,
                                 require_novel_anchor=require_novel_anchor, novel=novel,
                                 cross_metric_novel=cross_metric_novel,
                                 novel_server_anchored=novel_server_anchored,
                                 reproducible=reproducible, reproducibility_ceiling=reproducibility_ceiling)


def test_reproducibility_ceiling_truth_table():
    # 불일치 False + anchored 게이트 + progressive → partial 천장(값 보존, novel_independent=False).
    d = _demote(reproducible=False, reproducibility_ceiling=True)
    assert d == VerdictDecision("partial", "reproducibility_refuted", False)
    # 불가 None → 천장 안 함(부재≠반증, dead-σ). ★라이브 노드 무회귀의 핵심.
    assert _demote(reproducible=None, reproducibility_ceiling=True).verdict == "progressive"
    # 재현 True → 천장 안 함.
    assert _demote(reproducible=True, reproducibility_ceiling=True).verdict == "progressive"
    # 게이트 off(비-anchored tier): reproducible False 라도 천장 안 함(anchored 전용).
    assert _demote(reproducible=False, reproducibility_ceiling=False).verdict == "progressive"
    # progressive 밖(이미 강등)이면 천장 무발화(대상 아님).
    assert _demote("partial", reproducible=False, reproducibility_ceiling=True).verdict == "partial"
    # progressive_conditional 도 천장 대상(_PROGRESSIVE 집합).
    assert _demote("progressive_conditional", reproducible=False,
                   reproducibility_ceiling=True).verdict == "partial"


def test_precedence_hardcore_beats_ceiling_beats_ff1():
    # ① hardcore(다른 프로그램)가 재현성 천장보다 우선.
    d = _demote(hc_derived=False, reproducible=False, reproducibility_ceiling=True)
    assert d.verdict == "different_programme"
    # ② 재현성 천장이 FF1(novel 미앵커)보다 우선 — 둘 다 partial 이나 label 은 reproducibility_refuted.
    d = _demote(reproducible=False, reproducibility_ceiling=True,
                require_novel_anchor=True, novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d == VerdictDecision("partial", "reproducibility_refuted", False)
    # FF1 단독(재현성 천장 조건 없음)은 기존대로 novel_not_server_anchored.
    d = _demote(require_novel_anchor=True, novel=True, cross_metric_novel=True, novel_server_anchored=False)
    assert d.lakatos_status == "novel_not_server_anchored"


# ── (B) assurance 게이트: 재현성 천장 = anchored 전용, 단조 ─────────────────────────
def test_ceiling_is_anchored_gate_and_none_never_caps():
    """guard_mechanism: GATE_REPRODUCIBILITY_CEILING 가 submit_test_result×anchored 에만 무장,
    receipted/notebook 엔 없음(단조 보존) + None 은 절대 천장 안 함(dead-σ 재확인)."""
    g = assurance.GATE_REPRODUCIBILITY_CEILING
    assert g in assurance.gates_for("submit_test_result", "anchored")
    assert g not in assurance.gates_for("submit_test_result", "receipted")
    assert g not in assurance.gates_for("submit_test_result", "notebook")
    # 구조코어 오염 금지(교집합 ∅).
    all_bits = frozenset().union(*assurance.TIER_GATES.values()) | frozenset().union(*assurance.VERB_GATES.values())
    assert g not in assurance.STRUCTURAL_CORE and assurance.STRUCTURAL_CORE & all_bits == frozenset()
    # None 무천장(부재≠반증).
    assert _demote(reproducible=None, reproducibility_ceiling=True).verdict == "progressive"


# ── (C) submit 배선: 실 apply 경로가 게이트+reproducible 을 먹는다 ─────────────────
class _SubmitKg:
    def __init__(self, tier="anchored"):
        self.captured = []
        self.tier = tier

    def __call__(self, query, **p):
        if "pred_metric AS m" in query:
            # novel 앵커된 progressive 가 나오도록 novel target 등록(천장이 강등할 대상을 만든다).
            return [{"m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio", "novel": "",
                     "vsrc": None, "nmet": "seam2", "ndir": "higher", "nthr": 1.0, "psha": None,
                     "closes": None, "n_opened": 0, "pred_registered_at": "2026-07-03",
                     "node_state": "PREDICTED", "judged_at": None, "existing_metric_value": None,
                     "hard_core": "", "require_novel_anchor": False, "assurance_tier": self.tier,
                     "attestor_dids": None, "prev_receipt_sha": None}]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


def _svc(kg, reproducible):
    import hashlib
    svc = JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                           foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: reproducible)
    # 서버 sha 재유도를 결정론 스텁으로 — 서로 다른 스크립트 본문 → 서로 다른 sha(H6 독립 앵커) → 판결 progressive.
    svc._recompute_script_sha = lambda s: ((hashlib.sha256(s.encode()).hexdigest(), {}) if s else (None, {"reason": "none"}))
    return svc


def _submit(svc):
    return svc.submit_test_result(
        "T", "seam",
        Result(metric_value=1.0, script="def score_a", novel_script="def score_b", novel_measured=1.0))


def test_reproducibility_refuted_caps_at_partial():
    """guard_defect: anchored tree + reproducible=False → progressive 가 partial(reproducibility_refuted)로 봉인.

    천장을 apply_verdict_demotes 에서 떼면 verdict='progressive' 로 봉인 → 이 가드 RED(revert-민감)."""
    kg = _SubmitKg(tier="anchored")
    _submit(_svc(kg, False))
    _q, params = kg.captured[0][0]
    assert params["v"] == "partial", f"재현성 천장 실패 — verdict={params['v']}"
    assert params["lstat"] == "reproducibility_refuted", f"lstat={params.get('lstat')}"


def test_reproducible_none_stays_progressive_no_regression():
    """라이브 무회귀 실증: 같은 노드가 reproducible=None(불가)이면 anchored 라도 progressive 유지(부재≠반증)."""
    kg = _SubmitKg(tier="anchored")
    _submit(_svc(kg, None))
    _q, params = kg.captured[0][0]
    assert params["v"] == "progressive", f"None 인데 천장됨(dead-σ 오분류) — verdict={params['v']}"


guard_defect = "test_reproducibility_refuted_caps_at_partial"
guard_mechanism = "test_ceiling_is_anchored_gate_and_none_never_caps"
