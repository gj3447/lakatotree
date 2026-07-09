"""c1verify reproducible gate — runs in the clean venv (no engine). Synthetic content-sealed manifests.

Two distinct tamper classes: MANIFEST SUBSTITUTION (swap the sealed manifest, stale pin) dies on the
sha-pin; BROKEN LINEAGE (gap / wrong declared root / missing env / unrecorded artifact / cycle) dies
on the re-derived verify_dataset_manifest checks even with a MATCHING pin.
"""
from __future__ import annotations

import hashlib

import c1verify
from c1verify.jcs import jcs


def _manifest(**over) -> dict:
    """A raw-rooted, gapless, acyclic manifest with env present (passes G-RebuildFromRaw)."""
    m = {
        "schema_version": "lakatotree.dataset-manifest.v1",
        "final_artifact": "final.bin",
        "root_artifacts": ["raw.zdf"],
        "derivations": [
            {"output": "raw.zdf", "output_sha": "a" * 16, "producer": "", "producer_sha": "",
             "inputs": [], "params": {}, "kind": "source", "ts": "", "env": ""},
            {"output": "mid.bin", "output_sha": "b" * 16, "producer": "step1.py",
             "producer_sha": "s1", "inputs": [["raw.zdf", "a" * 16]], "params": {},
             "kind": "intermediate", "ts": "", "env": ""},
            {"output": "final.bin", "output_sha": "c" * 16, "producer": "step2.py",
             "producer_sha": "s2", "inputs": [["mid.bin", "b" * 16]], "params": {},
             "kind": "final", "ts": "", "env": ""},
        ],
        "environment": {"python": "3.14.4", "platform": "Linux", "package_locks": {},
                        "env_vars": {}, "tool_versions": {}},
        "tolerance": "",
        "metadata": {},
    }
    m.update(over)
    return m


def _sha(manifest: dict) -> str:
    return hashlib.sha256(jcs(manifest)).hexdigest()


def _bundle(manifest: dict, pin: str | None = None) -> bytes:
    return jcs({
        "c1_bundle_version": 1,
        "evidence_window": {"as_of": "2026-07-09T00:00:00+00:00",
                            "shas": {"reproducible": _sha(manifest) if pin is None else pin}},
        "gates": {"reproducible": {"manifest": manifest}},
    })


def _dec(bundle: bytes) -> dict:
    return next(g for g in c1verify.verify(bundle)["per_gate"] if g["gate"] == "reproducible")


def test_honest_manifest_accepts_with_residual():
    d = _dec(_bundle(_manifest()))
    assert d["decision"] == c1verify.ACCEPT
    assert d["residual_trust_surface"] and "staleness" in d["residual_trust_surface"]


def test_manifest_substitution_rejects():
    """Swap the sealed manifest for a different one, leaving the pin on the ORIGINAL -> sha mismatch."""
    honest_pin = _sha(_manifest())
    swapped = _manifest()
    swapped["derivations"][2]["output_sha"] = "d" * 16   # a different (still-valid) manifest
    d = _dec(_bundle(swapped, pin=honest_pin))
    assert d["decision"] == c1verify.REJECT and "manifest substitution" in d["reason"]


def test_reproducibility_gap_rejects_with_matching_pin():
    """Drop the intermediate derivation: final's input 'mid.bin' now has no derivation and is not a
    source -> broken lineage. Re-sealed with a MATCHING pin, so the LINEAGE check must catch it."""
    m = _manifest()
    m["derivations"] = [d for d in m["derivations"] if d["output"] != "mid.bin"]
    d = _dec(_bundle(m))   # pin recomputed to match the tampered manifest
    assert d["decision"] == c1verify.REJECT and "gap" in d["reason"]


def test_root_manifest_mismatch_rejects_with_matching_pin():
    m = _manifest(root_artifacts=["not_the_real_root.zdf"])
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "root manifest mismatch" in d["reason"]


def test_missing_environment_rejects_with_matching_pin():
    m = _manifest(environment={"python": "", "platform": "", "package_locks": {},
                               "env_vars": {}, "tool_versions": {}})
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "environment fingerprint" in d["reason"]


def test_unrecorded_final_artifact_rejects_with_matching_pin():
    m = _manifest(final_artifact="ghost.bin")   # not produced by any derivation
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "unrecorded" in d["reason"]


def test_lineage_cycle_rejects_with_matching_pin():
    m = _manifest()
    # make mid.bin depend on final.bin -> final.bin -> mid.bin -> final.bin cycle
    for deriv in m["derivations"]:
        if deriv["output"] == "mid.bin":
            deriv["inputs"] = [["raw.zdf", "a" * 16], ["final.bin", "c" * 16]]
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "cycle" in d["reason"]


def test_missing_pin_rejects():
    m = _manifest()
    body = jcs({"c1_bundle_version": 1, "evidence_window": {"as_of": "t", "shas": {}},
                "gates": {"reproducible": {"manifest": m}}})
    d = _dec(body)
    assert d["decision"] == c1verify.REJECT and "pin" in d["reason"]


def test_absent_and_malformed_payload_reject():
    body = jcs({"c1_bundle_version": 1, "gates": {"reproducible": {}}})
    assert _dec(body)["decision"] == c1verify.REJECT
    body2 = jcs({"c1_bundle_version": 1, "gates": {"reproducible": {"manifest": [1, 2, 3]}}})
    assert _dec(body2)["decision"] == c1verify.REJECT


def test_malformed_derivation_rejects():
    m = _manifest()
    m["derivations"].append({"output": "x.bin", "inputs": "not-a-list"})
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "malformed" in d["reason"]


# ── fail-closed totality on attacker-controlled bytes (adversarial-verification 2026-07-09) ──────

def test_keyless_derivation_rejects_not_raises():
    """A derivation dict with NO 'inputs' key (a source, per the engine) must not crash the graph
    walk; a keyless node reachable-but-undeclared fails closed to a REJECT, never a KeyError."""
    m = {"final_artifact": "final.bin", "root_artifacts": ["raw.zdf"],
         "derivations": [{"output": "raw.zdf", "inputs": []},
                         {"output": "final.bin", "inputs": [["X", ""]]}, {"output": "X"}],
         "environment": {"python": "3.14"}}
    d = _dec(_bundle(m))   # must return a REJECT report, not raise
    assert d["decision"] == c1verify.REJECT
    # a CLEAN graph-walk REJECT, not the core totality backstop — proves _by_output normalisation is
    # load-bearing (revert it and _gaps KeyErrors, degrading this to a 'reverifier raised' reason).
    assert "raised" not in d["reason"]


def test_nonstring_root_rejects_not_raises():
    """A non-string root_artifacts element would be an unhashable set member — fail closed, don't crash."""
    m = _manifest(root_artifacts=[["raw.zdf"]])
    d = _dec(_bundle(m))
    assert d["decision"] == c1verify.REJECT and "non-string" in d["reason"]


def test_junk_typed_environment_rejects():
    """A junk-typed env field (a string package_locks, a bool tool_versions) is not a real fingerprint
    — it fails closed to REJECT, never an ACCEPT the engine could not itself represent."""
    for env in ({"package_locks": "junk"}, {"tool_versions": True}, {"python": 3.14}):
        m = _manifest(environment=env)
        d = _dec(_bundle(m))
        assert d["decision"] == c1verify.REJECT and "environment fingerprint" in d["reason"], env


def test_verify_never_raises_on_adversarial_bundles():
    """Totality keystone: verify() is total over arbitrary bytes — it returns a report, never raises."""
    import c1verify as cv
    for raw in (b"", b"not json", b"\xff\xfe", b"[]", b'{"gates":{"reproducible":{"manifest":42}}}',
                jcs({"c1_bundle_version": 1, "gates": {"reproducible": {"manifest": {"derivations": 5}}}})):
        rep = cv.verify(raw)   # must not raise
        assert rep["certified"] is False
