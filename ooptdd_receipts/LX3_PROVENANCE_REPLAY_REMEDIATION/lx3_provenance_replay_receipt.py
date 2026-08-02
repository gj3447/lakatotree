"""OOPTDD receipt for LX3 claim-standing and replay-diagnostic remediation.

The receipt drives real service and fsck seams.  It pins three load-bearing boundaries:
metadata cannot manufacture evidence, replay diagnosis is v4 content-addressed with cache
parity, v5 binds artifact identity without moving historical v4 hashes, and the CLI carries a
concrete artifact path for managed replay.

# KG: LakatosTree_LX3_Metrology_20260723 / lx3_provenance_replay_remediation_20260726
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import lakatos.cli as cli  # noqa: E402
from lakatos.io.replay import ProducerReplayVerdict  # noqa: E402
from lakatos.verdicts import RECEIPT_FIELDS_V3, RECEIPT_FIELDS_V4, receipt_content_sha  # noqa: E402
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
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "scorer.py"
        result = Path(tmp) / "out.json"
        script.write_text("print(1.0)\n", encoding="utf-8")
        result.write_text('{"metric":1.0}\n', encoding="utf-8")
        out = svc.submit_test_result(
            "T", "seam", Result(metric_value=1.0, script=str(script), result_path=str(result)),
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
        judge_script_path=params["script"], result_path=params["rp"],
        result_sha256=params["result_sha256"], measurement_lock_sha=params["lsha"],
        source_script_path=params["source_script"], source_result_path=params["source_rp"],
        history_payload_sha256=params["history_payload_sha256"],
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


def _old_cache_only_failure_class(record: dict) -> str:
    """Ablated pre-parity reader: trust the mutable node cache as the diagnosis source."""
    return audit_fsck._replay_failure_class(record.get("replay_reason"))


def verify(backend, cid):
    # (A) Metadata alone cannot synthesize upper/lower evidence.
    draft = _drive_draft_claim()
    assert draft["stands"] is False and draft["realms"] == []
    assert draft["upper_confidence"] == draft["lower_confidence"] == 0.0
    backend.ship([_event(cid, "lx3_claim_metadata_cannot_synthesize_evidence")])

    # (B) Submit persists v4-schema diagnostics; the artifact-bearing current mint is v5.
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

    # (F) Genuine negative oracles: run the exact pre-remediation mechanisms, not an
    # assertion that merely deletes the value under test.

    # F1 — v3 omitted replay diagnostics.  Two verdict records that differ only in the
    # operator-relevant diagnosis therefore occupied the same legacy content address.
    forged_diagnostics = {
        **fields,
        "replay_reason": "scorer_nonzero_exit:1",
        "regenerated_metric": None,
    }
    assert receipt_content_sha(fields, fieldset=RECEIPT_FIELDS_V3) == receipt_content_sha(
        forged_diagnostics, fieldset=RECEIPT_FIELDS_V3,
    )
    assert receipt_content_sha(fields) != receipt_content_sha(forged_diagnostics)
    backend.ship([_event(cid, "lx3_negative_v3_replay_collision")])

    # F2 — the old cache-only reader accepts a forged node projection as scorer failure.
    # The current fsck rejects cache parity and refuses to let that cache steer diagnosis.
    assert _old_cache_only_failure_class(tampered) == "scorer_execution_failure"
    assert "scorer_execution_failure" not in diagnostic.detail
    assert "legacy_unclassified" in diagnostic.detail
    backend.ship([_event(cid, "lx3_negative_cache_only_substitution")])

    # F3 — historical v4 intentionally omitted replay artifact identity.  Changing the path,
    # artifact digest and measurement lock was invisible there, while current v5 binds all three
    # without retroactively moving the v4 sha-space.
    artifact_a = {
        **fields,
        "result_path": "/srv/out.json",
        "result_sha256": "a" * 64,
        "measurement_lock_sha": "b" * 64,
    }
    artifact_b = {
        **artifact_a,
        "result_path": "/srv/forged.json",
        "result_sha256": "c" * 64,
        "measurement_lock_sha": "d" * 64,
    }
    assert receipt_content_sha(artifact_a, fieldset=RECEIPT_FIELDS_V4) == receipt_content_sha(
        artifact_b, fieldset=RECEIPT_FIELDS_V4,
    )
    assert receipt_content_sha(artifact_a) != receipt_content_sha(artifact_b)
    backend.ship([_event(cid, "lx3_negative_v4_artifact_collision")])

    backend.ship([_event(cid, "lx3_remediation_negative_oracle", defects_reproduced=3)])
