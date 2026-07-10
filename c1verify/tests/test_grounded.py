"""c1verify grounded gate — runs in the clean venv (no engine). Synthetic registries + sealed pins."""
from __future__ import annotations

import hashlib

import c1verify
from c1verify.jcs import jcs


def _sha(reg):
    return hashlib.sha256(jcs(reg)).hexdigest()


REG = {
    "damping": {"value": 0.85, "source": "brin_page1998", "tier": "literature"},
    "bf_progressive": {"value": 6.0, "source": "jeffreys1961", "tier": "policy_in_scale"},
    "weight_floor": {"value": 0.3, "source": "policy", "tier": "policy"},
}


def _bundle(registry, pin=None, evidence_window=True):
    ew = {"as_of": "2026-07-09T00:00:00+00:00", "shas": {"grounding": pin or _sha(registry)}}
    body = {"c1_bundle_version": 1, "gates": {"grounded": {"registry": registry}}}
    if evidence_window:
        body["evidence_window"] = ew
    return jcs(body)


def _grounded(bundle_bytes):
    return next(g for g in c1verify.verify(bundle_bytes)["per_gate"] if g["gate"] == "grounded")


def test_honest_registry_accepts_with_residual():
    g = _grounded(_bundle(REG))
    assert g["decision"] == c1verify.ACCEPT
    assert g["residual_trust_surface"], "ACCEPT must name the tier-correctness residual"


def test_snapshot_substitution_rejects():
    # seal the honest pin, then swap the registry for a different one
    honest_pin = _sha(REG)
    swapped = {**REG, "backdoor": {"value": 0.0, "source": "policy", "tier": "policy"}}
    g = _grounded(_bundle(swapped, pin=honest_pin))
    assert g["decision"] == c1verify.REJECT and "snapshot substitution" in g["reason"]


def test_bogus_tier_rejects_even_with_matching_pin():
    bad = {**REG, "damping": {**REG["damping"], "tier": "made_up"}}
    g = _grounded(_bundle(bad, pin=_sha(bad)))   # pin matches => sha check passes; tier check must fail
    assert g["decision"] == c1verify.REJECT and "tier" in g["reason"]


def test_empty_registry_rejects():
    assert _grounded(_bundle({}))["decision"] == c1verify.REJECT


def test_missing_pin_rejects():
    assert _grounded(_bundle(REG, evidence_window=False))["decision"] == c1verify.REJECT


def test_registry_absent_rejects():
    body = jcs({"c1_bundle_version": 1,
                "evidence_window": {"as_of": "x", "shas": {"grounding": "y"}},
                "gates": {"grounded": {}}})
    assert _grounded(body)["decision"] == c1verify.REJECT


def test_grounded_alone_does_not_certify():
    # even with grounded ACCEPT, the other five gates are still REJECT => certified False
    report = c1verify.verify(_bundle(REG))
    assert report["certified"] is False
    assert "grounded" not in report["missing"]        # grounded passed
    assert set(report["missing"]) == set(c1verify.GATES) - {"grounded"}
