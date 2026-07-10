"""c1verify substrate gate — runs in the clean venv (no engine). Synthetic content-addressed chains."""
from __future__ import annotations

import c1verify
from c1verify.jcs import jcs
from c1verify.receipts import receipt_content_sha


def _receipt(prev=None, verdict="progressive", source="scripted", **over):
    fields = {"tree": "T", "tag": "n", "target_id": "n", "verdict": verdict, "verdict_source": source,
              "metric_name": "m", "metric_value": 1.0, "novel_confirmed": True,
              "lakatos_status": "canonical", "judged_at": "2026-07-09T00:00:00+00:00",
              "judge_script_sha": "deadbeef", "prev_receipt_sha": prev,
              "measurement_grade": "server_regenerated"}
    fields.update(over)
    fields["receipt_sha"] = receipt_content_sha(fields)   # receipt_sha is NOT in RECEIPT_FIELDS
    return fields


def _bundle(chain, head):
    return jcs({"c1_bundle_version": 1, "gates": {"substrate": {"chain": chain, "head": head}}})


def _dec(bundle):
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "substrate")


def test_honest_chain_accepts_with_residual():
    genesis = _receipt()
    head = _receipt(prev=genesis["receipt_sha"])
    d = _dec(_bundle([genesis, head], head["receipt_sha"]))
    assert d["decision"] == c1verify.ACCEPT
    assert d["residual_trust_surface"] and "AUTHENTICITY" in d["residual_trust_surface"]


def test_tampered_receipt_field_rejects():
    genesis = _receipt()
    head = _receipt(prev=genesis["receipt_sha"])
    tampered = {**head, "verdict": "rejected"}   # flip verdict but keep the old receipt_sha
    d = _dec(_bundle([genesis, tampered], head["receipt_sha"]))
    assert d["decision"] == c1verify.REJECT and "content-sha mismatch" in d["reason"]


def test_dangling_head_rejects():
    genesis = _receipt()
    d = _dec(_bundle([genesis], "0" * 64))
    assert d["decision"] == c1verify.REJECT


def test_broken_prev_link_rejects():
    head = _receipt(prev="1" * 64)   # prev points at a receipt not in the chain
    d = _dec(_bundle([head], head["receipt_sha"]))
    assert d["decision"] == c1verify.REJECT and "broken" in d["reason"]


def test_empty_and_missing_chain_reject():
    assert _dec(_bundle([], "x"))["decision"] == c1verify.REJECT
    body = jcs({"c1_bundle_version": 1, "gates": {"substrate": {"head": "x"}}})
    assert _dec(body)["decision"] == c1verify.REJECT
