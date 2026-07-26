"""OOPTDD receipt for LX3 claim-standing and replay-diagnostic remediation.

The receipt drives real service and fsck seams.  It pins three load-bearing boundaries:
metadata cannot manufacture evidence, replay diagnosis is v4 content-addressed with cache
parity, and the CLI carries a concrete artifact path for managed replay.

# KG: LakatosTree_LX3_Metrology_20260723 / lx3_provenance_replay_remediation_20260726
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import lakatos.cli as cli  # noqa: E402
from lakatos.io.replay import ProducerReplayVerdict  # noqa: E402
from lakatos.verdicts import receipt_content_sha  # noqa: E402
from server.contexts.audit import fsck as audit_fsck  # noqa: E402
from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.judgement_policy import build_receipt_fields  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import TestResultIn as Result  # noqa: E402


def _event(cid: str, name: str, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.lx3.provenance_replay_remediation",
        "event": name,
        **attrs,
    }


class _SubmitKg:
    def __init__(self):
        self.ops = []

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
        self.ops.append(ops)
        return [[{"claimed": "seam"}] for _ in ops]


def _drive_submit():
    kg = _SubmitKg()
    history = []
    replay = ProducerReplayVerdict(
        verified=False, regenerated=7.0, recorded=1.0, reason="metric_mismatch",
    )
    svc = JudgementService(
        kg=kg, kg_tx=kg.tx, hist=lambda *args, **_kwargs: history.append(args),
        foundation=lambda *_args, **_kwargs: None,
        reproducible_for_node=lambda *_args, **_kwargs: None,
        producer_replay_submit=lambda *_args, **_kwargs: replay,
    )
    out = svc.submit_test_result(
        "T", "seam", Result(metric_value=1.0, script="/srv/scorer.py", result_path="/srv/out.json"),
    )
    return kg.ops[0][0], out, history[-1][3]


def _receipt_fields(params):
    return build_receipt_fields(
        tree=params["tree"], tag=params["tag"], target_id=params.get("target_id"),
        verdict=params["v"], metric_name=params["mn"], metric_value=params["mv"],
        novel_confirmed=params["novel"], lakatos_status=params["lstat"],
        judged_at=params["ts"], judge_script_sha=params["sha"],
        prev_receipt_sha=params["prev_rsha"], measurement_grade=params["mg"],
        engine_rule_sha=params["engine_rule_sha"], comment_sha=params["csha"],
        replay_status=params["replay_status"], replay_reason=params["replay_reason"],
        regenerated_metric=params["regenerated_metric"],
    )


def _drive_draft_claim():
    def kg(query, **_params):
        if "e.source_trust AS source_trust" in query:
            return [{
                "tag": "draft", "verdict": None, "source_trust": 1.0,
                "verdict_source": None, "judge_script": "/tmp/not-run.py",
                "judge_script_sha": None, "result_path": "/tmp/arbitrary.json", "args": [],
            }]
        if "RETURN ev.id AS id" in query:
            return []
        return []

    svc = EvidenceClaimService(
        kg=kg, hist=lambda *_a, **_k: None, foundation=lambda _name: None,
        load_lineage=lambda: [], reproducible_for_node=lambda *_a: None,
    )
    return svc.claim_standing("T", "draft", require_replay=False)


def _drive_result_cli():
    calls = []
    original = cli.call
    try:
        cli.call = lambda method, path, body=None: (
            calls.append((method, path, body)), {"ok": True}
        )[1]
        cli.main([
            "result", "T", "seam", "--value", "1.0", "--script", "scorer.py",
            "--result-path", "results/lx3.json",
        ])
    finally:
        cli.call = original
    return calls[0]


def verify(backend, cid):
    # (A) Metadata alone cannot synthesize upper/lower evidence.
    draft = _drive_draft_claim()
    assert draft["stands"] is False and draft["realms"] == []
    assert draft["upper_confidence"] == draft["lower_confidence"] == 0.0
    backend.ship([_event(cid, "lx3_claim_metadata_cannot_synthesize_evidence")])

    # (B) Submit persists diagnostics and seals them in a v4 content address.
    (query, params), out, hist = _drive_submit()
    fields = _receipt_fields(params)
    assert params["rsha"] == receipt_content_sha(fields)
    assert params["replay_reason"] == out["replay_reason"] == hist["replay_reason"] == "metric_mismatch"
    assert params["regenerated_metric"] == out["regenerated_metric"] == hist["regenerated_metric"] == 7.0
    assert "rec.replay_reason=$replay_reason" in query
    assert receipt_content_sha({**fields, "replay_reason": "scorer_nonzero_exit:1"}) != params["rsha"]
    backend.ship([_event(cid, "lx3_replay_diagnostics_v4_sealed")])

    # (C) Node cache substitution is an ERROR and cannot steer operator classification.
    receipt = {**fields, "receipt_sha": params["rsha"]}
    tampered = {
        "tag": "seam", "verdict": "progressive", "verdict_source": "scripted",
        "pred_registered_at": "2026-07-26", "assurance_tier_resolved": "anchored",
        "current_receipt_sha": params["rsha"], "metric_value": 1.0,
        "replay_status": "mismatch", "replay_reason": "scorer_nonzero_exit:1",
        "regenerated_metric": None, "receipts": [receipt],
    }
    findings = audit_fsck.fsck_node(tampered)
    assert any(f.check_id == "REPLAY_DIAGNOSTIC_CACHE_MISMATCH" and f.severity == "ERROR"
               for f in findings)
    diagnostic = next(f for f in findings if f.check_id == "MEASUREMENT_REFUTED_BUT_STANDING")
    assert "legacy_unclassified" in diagnostic.detail and "scorer_execution_failure" not in diagnostic.detail
    backend.ship([_event(cid, "lx3_replay_cache_parity_enforced")])

    # (D) Internal NULL is valid; only a real internet-bound source requires EigenTrust.
    assert audit_fsck._check_source_trust({"source_trust": None}) is None
    finding = audit_fsck._check_source_trust({"source": "https://example.test", "source_trust": None})
    assert finding and finding.check_id == "SOURCE_TRUST_NULL"
    backend.ship([_event(cid, "lx3_source_trust_semantics_scoped")])

    # (E) CLI carries the replay artifact path end-to-end.
    method, path, body = _drive_result_cli()
    assert (method, path) == ("POST", "/api/tree/T/node/seam/test_result")
    assert body["result_path"] == "results/lx3.json"
    backend.ship([_event(cid, "lx3_cli_result_path_forwarded")])

    # (F) Negative oracle: removing parity and v4 fields recreates silent diagnosis substitution.
    assert receipt_content_sha(fields) == params["rsha"]
    forged_cache = {**tampered, "receipts": []}
    old_findings = audit_fsck.fsck_node(forged_cache)
    assert not any(f.check_id == "REPLAY_DIAGNOSTIC_CACHE_MISMATCH" for f in old_findings)
    assert "result_path" not in {k: v for k, v in body.items() if k != "result_path"}
    backend.ship([_event(cid, "lx3_remediation_negative_oracle", defects_reproduced=3)])
