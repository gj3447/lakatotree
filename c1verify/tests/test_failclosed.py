"""c1verify's OWN suite — runs in the clean-venv CI job where lakatos/server are NOT installed.

If any c1verify module ever imports the engine, THIS suite fails to even import in the clean venv
(ImportError, not a green test) — that is P0b's construction proof of engine-independence.
The suite itself imports ONLY c1verify + stdlib.
"""
from __future__ import annotations

import sys

import c1verify
from c1verify.jcs import jcs


def _canonical_bundle(gates=None) -> bytes:
    return jcs({"c1_bundle_version": 1, "gates": gates or {}})


# ── fail-closed totality: every one of these must REJECT every gate without raising ────────────
GARBAGE = [
    ("empty", b""),
    ("not-bytes-utf8", b"\xff\xfe\x00rubbish"),
    ("not-json", b"not json at all"),
    ("json-not-object", b"[1,2,3]"),
    ("json-scalar", b"123"),
    ("duplicate-keys", b'{"c1_bundle_version":1,"c1_bundle_version":2,"gates":{}}'),
    ("non-canonical-space", b'{"gates": {}, "c1_bundle_version": 1}'),
    ("unknown-top-field", jcs({"c1_bundle_version": 1, "gates": {}, "evil": 1})),
    ("wrong-version", jcs({"c1_bundle_version": 2, "gates": {}})),
    ("gates-not-object", jcs({"c1_bundle_version": 1, "gates": 5})),
    ("well-formed-empty", _canonical_bundle()),
    ("well-formed-with-gate-payloads", _canonical_bundle(
        {g: {"anything": True} for g in c1verify.GATES})),
]


def test_every_bundle_rejects_every_gate_and_never_certifies():
    for label, data in GARBAGE:
        report = c1verify.verify(data)  # must be total — no exception
        assert isinstance(report, dict), label
        assert report["certified"] is False, f"{label}: certified leaked True"
        assert set(report["missing"]) == set(c1verify.GATES), label
        assert all(g["decision"] == c1verify.REJECT for g in report["per_gate"]), \
            f"{label}: a gate did not REJECT"


def test_report_shape_is_stable():
    report = c1verify.verify(_canonical_bundle())
    assert set(report) == {"per_gate", "certified", "missing", "residuals"}
    assert [g["gate"] for g in report["per_gate"]] == list(c1verify.GATES)
    for g in report["per_gate"]:
        assert set(g) == {"gate", "decision", "reason", "residual_trust_surface"}


def test_reject_rate_over_corpus_is_total():
    rejected = sum(c1verify.verify(d)["certified"] is False
                   and all(g["decision"] == c1verify.REJECT for g in c1verify.verify(d)["per_gate"])
                   for _, d in GARBAGE)
    assert rejected == len(GARBAGE)  # garbage_bundle_reject_rate == 1.0


def test_zero_engine_symbols_loaded_by_verify():
    """After importing c1verify and running verify(), no lakatos/server module is loaded.
    In the clean venv the engine is not even installed, so this is trivially 0 — which is the point."""
    c1verify.verify(_canonical_bundle())
    engine = [m for m in sys.modules
              if m == "lakatos" or m.startswith("lakatos.")
              or m == "server" or m.startswith("server.")]
    assert engine == [], f"engine symbols loaded during verify(): {engine}"
