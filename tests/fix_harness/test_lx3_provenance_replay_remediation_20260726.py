"""LX3 remediation guards: provenance-at-create, replay diagnostics, and safe backfill planning.

The live LX3 tree exposed two ambiguous states: internally-created nodes with a projected
``source_trust=None`` and standing replay mismatches whose persisted record did not say whether
the scorer disagreed, crashed, or emitted no metric.  These guards pin the server-owned write
contracts and a read-only migration plan; clients remain unable to self-assert either provenance.

# KG: LakatosTree_LX3_Metrology_20260723 / lx3_provenance_replay_remediation_20260726
"""
from __future__ import annotations

from pathlib import Path

from lakatos.io.replay import ProducerReplayVerdict
from lakatos.verdicts import prediction_content_sha, receipt_content_sha
from server.contexts.audit import fsck as F
from server.contexts.tree.evidence_claim_service import EvidenceClaimService
from server.contexts.tree.judgement_policy import build_receipt_fields
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.repository import TreeKgRepository
from server.contexts.tree.schemas import TestResultIn as Result


ROOT = Path(__file__).resolve().parents[2]


def test_source_trust_null_is_only_a_finding_for_actual_internet_sources():
    """Internal NULL is absence of an external claim, not missing maximum internet trust."""
    internal = F._check_source_trust({"tag": "internal", "source_trust": None})
    external = F._check_source_trust({
        "tag": "external", "source": "https://example.test/paper", "source_trust": None,
    })

    assert internal is None
    assert external is not None and external.check_id == "SOURCE_TRUST_NULL"
    assert "EigenTrust" in external.detail


def test_draft_result_path_and_source_trust_cannot_manufacture_claim_evidence():
    """A draft path/trust scalar is metadata, not an INTERNET or BASH observation receipt."""
    def kg(query, **_params):
        if "e.source_trust AS source_trust" in query:
            return [{
                "tag": "draft", "verdict": None, "source_trust": 1.0,
                "verdict_source": None, "judge_script": "/tmp/not-run.py",
                "judge_script_sha": None, "result_path": "/tmp/arbitrary.json",
                "current_receipt_sha": None, "replay_status": None, "args": [],
            }]
        if "RETURN ev.id AS id" in query:
            return []
        return []

    svc = EvidenceClaimService(
        kg=kg, hist=lambda *_a, **_k: None, foundation=lambda _name: None,
        load_lineage=lambda: [], reproducible_for_node=lambda *_a: None,
    )
    out = svc.claim_standing("T", "draft", require_replay=False)

    assert out["stands"] is False
    assert out["realms"] == []
    assert out["upper_confidence"] == 0.0 and out["lower_confidence"] == 0.0


class _SubmitKg:
    def __init__(self):
        self.captured: list[list[tuple[str, dict]]] = []

    def __call__(self, query, **_params):
        if "pred_metric AS m" in query:
            return [{
                "m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio",
                "novel": "", "vsrc": None, "nmet": None, "ndir": None, "nthr": None,
                "psha": None, "closes": None, "n_opened": 0,
                "pred_registered_at": "2026-07-26", "node_state": "PREDICTED",
                "judged_at": None, "existing_metric_value": None, "hard_core": "",
                "require_novel_anchor": False, "assurance_tier": None,
                "attestor_dids": None, "prev_receipt_sha": None,
            }]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


def _submit_with_replay(replay: ProducerReplayVerdict):
    kg = _SubmitKg()
    history: list[tuple] = []
    svc = JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=lambda *args, **_kwargs: history.append(args),
        foundation=lambda *_args, **_kwargs: None,
        reproducible_for_node=lambda *_args, **_kwargs: None,
        producer_replay_submit=lambda *_args, **_kwargs: replay,
    )
    out = svc.submit_test_result(
        "T", "seam", Result(metric_value=1.0, script="/srv/scorer.py", result_path="/srv/out.json"),
    )
    return kg.captured[0][0], out, history


def test_submit_persists_and_discloses_replay_reason_and_regenerated_metric():
    """Defect guard: status=mismatch is not the whole replay receipt."""
    replay = ProducerReplayVerdict(
        verified=False, regenerated=7.0, recorded=1.0, reason="metric_mismatch",
    )
    (cypher, params), out, history = _submit_with_replay(replay)

    assert "e.replay_reason=$replay_reason" in cypher
    assert "e.regenerated_metric=$regenerated_metric" in cypher
    assert params["replay_reason"] == "metric_mismatch"
    assert params["regenerated_metric"] == 7.0
    assert out["replay_status"] == "mismatch"
    assert out["replay_reason"] == "metric_mismatch"
    assert out["regenerated_metric"] == 7.0
    assert history[-1][3]["replay_reason"] == "metric_mismatch"
    assert history[-1][3]["regenerated_metric"] == 7.0


def test_replay_diagnostics_are_content_addressed_in_v4_verdict_receipt():
    """Changing the operator diagnosis under one receipt SHA must be impossible."""
    base = build_receipt_fields(
        tree="T", tag="seam", target_id=None, verdict="progressive", metric_name="m",
        metric_value=1.0, novel_confirmed=False, lakatos_status="progressive",
        judged_at="2026-07-26T00:00:00+00:00", judge_script_sha="a" * 64,
        prev_receipt_sha="b" * 64, measurement_grade="client_asserted",
        engine_rule_sha="c" * 64, comment_sha="d" * 64,
        replay_status="mismatch", replay_reason="metric_mismatch", regenerated_metric=7.0,
    )
    original = receipt_content_sha(base)

    from c1verify.receipts import receipt_content_sha as external_receipt_content_sha
    assert external_receipt_content_sha(base) == original

    assert receipt_content_sha({**base, "replay_reason": "scorer_nonzero_exit:1"}) != original
    assert receipt_content_sha({**base, "regenerated_metric": None}) != original
    assert receipt_content_sha({**base, "replay_status": "not_replayable"}) != original


def test_repository_and_fsck_preserve_replay_failure_classification():
    """Mechanism guard: read projection feeds a reason-aware fsck message without inventing refutation."""
    seen: list[str] = []

    def kg(query, **_params):
        seen.append(query)
        if "RETURN t.title AS title" in query:
            return [{"title": "T"}]
        if "ORDER BY tag" in query:
            return [{"tag": "n", "parents": [], "parent_edges": [], "questions": []}]
        return []

    TreeKgRepository(kg).load_tree_data("T")
    projection = next(query for query in seen if "ORDER BY tag" in query)
    assert "e.replay_reason AS replay_reason" in projection
    assert "e.regenerated_metric AS regenerated_metric" in projection

    common = dict(
        tree="T", tag="n", target_id=None, verdict="progressive", metric_name="m",
        metric_value=1.0, novel_confirmed=False, lakatos_status="progressive",
        judged_at="2026-07-26T00:00:00+00:00", judge_script_sha="a" * 64,
        prev_receipt_sha=None, measurement_grade="client_asserted",
        engine_rule_sha="c" * 64, comment_sha="d" * 64, replay_status="mismatch",
    )
    value_fields = build_receipt_fields(
        **common, replay_reason="metric_mismatch", regenerated_metric=7.0)
    value_sha = receipt_content_sha(value_fields)
    sealed_receipt = {**value_fields, "receipt_sha": value_sha}
    value = F._check_measurement_refuted({
        "verdict": "progressive", "replay_status": "mismatch",
        "replay_reason": "metric_mismatch", "metric_value": 1.0, "regenerated_metric": 7.0,
        "current_receipt_sha": value_sha, "receipts": [sealed_receipt],
    })
    crash_fields = build_receipt_fields(
        **common, replay_reason="scorer_nonzero_exit:1", regenerated_metric=None)
    crash_sha = receipt_content_sha(crash_fields)
    crash = F._check_measurement_refuted({
        "verdict": "progressive", "replay_status": "mismatch",
        "replay_reason": "scorer_nonzero_exit:1", "metric_value": 1.0,
        "current_receipt_sha": crash_sha,
        "receipts": [{**crash_fields, "receipt_sha": crash_sha}],
    })
    legacy = F._check_measurement_refuted({
        "verdict": "progressive", "replay_status": "mismatch",
    })

    assert value is not None and "replay_failure_class='value_mismatch'" in value.detail
    assert "recorded=1.0" in value.detail and "regenerated=7.0" in value.detail
    assert crash is not None and "replay_failure_class='scorer_execution_failure'" in crash.detail
    assert "값 비교 전" in crash.detail and "측정 재실행이 값을 반증" not in crash.detail
    assert legacy is not None and "replay_failure_class='legacy_unclassified'" in legacy.detail


def test_fsck_rejects_node_replay_cache_that_disagrees_with_v4_head_receipt():
    """Receipt integrity plus cache parity prevents operator-diagnosis substitution."""
    fields = build_receipt_fields(
        tree="T", tag="n", target_id=None, verdict="progressive", metric_name="m",
        metric_value=1.0, novel_confirmed=False, lakatos_status="progressive",
        judged_at="2026-07-26T00:00:00+00:00", judge_script_sha="a" * 64,
        prev_receipt_sha=None, measurement_grade="client_asserted",
        engine_rule_sha="c" * 64, comment_sha="d" * 64,
        replay_status="mismatch", replay_reason="metric_mismatch", regenerated_metric=7.0,
    )
    sha = receipt_content_sha(fields)
    tampered_cache = {
        "tag": "n", "verdict": "progressive", "verdict_source": "scripted",
        "pred_registered_at": "2026-07-25", "assurance_tier_resolved": "anchored",
        "current_receipt_sha": sha, "metric_value": 1.0,
        "replay_status": "mismatch", "replay_reason": "scorer_nonzero_exit:1",
        "regenerated_metric": None, "receipts": [{**fields, "receipt_sha": sha}],
    }
    findings = F.fsck_node(tampered_cache)

    assert any(f.check_id == "REPLAY_DIAGNOSTIC_CACHE_MISMATCH" and f.severity == F.ERROR
               for f in findings)
    measurement = next(f for f in findings if f.check_id == "MEASUREMENT_REFUTED_BUT_STANDING")
    assert "legacy_unclassified" in measurement.detail
    assert "scorer_execution_failure" not in measurement.detail


def test_fsck_never_trusts_invalid_v4_content_or_prediction_extra_fields():
    """Only a content-valid verdict-v4 head may select an actionable replay diagnosis."""
    fields = build_receipt_fields(
        tree="T", tag="n", target_id=None, verdict="progressive", metric_name="m",
        metric_value=1.0, novel_confirmed=False, lakatos_status="progressive",
        judged_at="2026-07-26T00:00:00+00:00", judge_script_sha="a" * 64,
        prev_receipt_sha=None, measurement_grade="client_asserted",
        engine_rule_sha="c" * 64, comment_sha="d" * 64,
        replay_status="mismatch", replay_reason="metric_mismatch", regenerated_metric=7.0,
    )
    honest_sha = receipt_content_sha(fields)
    forged_head = {
        **fields, "receipt_sha": honest_sha,
        "replay_reason": "scorer_nonzero_exit:1", "regenerated_metric": None,
    }
    forged = {
        "verdict": "progressive", "current_receipt_sha": honest_sha,
        "replay_status": "mismatch", "replay_reason": "scorer_nonzero_exit:1",
        "regenerated_metric": None, "receipts": [forged_head],
    }
    findings = F.fsck_node(forged)
    assert any(f.check_id == "RECEIPT_SHA_CONTENT_MISMATCH" for f in findings)
    diagnosis = next(f for f in findings if f.check_id == "MEASUREMENT_REFUTED_BUT_STANDING")
    assert "legacy_unclassified" in diagnosis.detail and "scorer_execution_failure" not in diagnosis.detail

    prediction = {"receipt_kind": "prediction", "tree": "T", "tag": "n"}
    pred_sha = prediction_content_sha(prediction)
    pred_with_extras = {
        **prediction, "receipt_sha": pred_sha, "replay_status": "mismatch",
        "replay_reason": "scorer_nonzero_exit:1", "regenerated_metric": None,
    }
    prediction_smuggle = {
        "verdict": "progressive", "current_receipt_sha": pred_sha,
        "replay_status": "mismatch", "replay_reason": "scorer_nonzero_exit:1",
        "regenerated_metric": None, "receipts": [pred_with_extras],
    }
    pred_diagnosis = F._check_measurement_refuted(prediction_smuggle)
    assert pred_diagnosis is not None and "legacy_unclassified" in pred_diagnosis.detail


guard_defect = "test_draft_result_path_and_source_trust_cannot_manufacture_claim_evidence"
guard_mechanism = "test_replay_diagnostics_are_content_addressed_in_v4_verdict_receipt"
