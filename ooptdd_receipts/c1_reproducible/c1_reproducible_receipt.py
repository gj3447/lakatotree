"""OOPTDD emit-adapter — C1 S2 (reproducible gate rebuild-from-raw reverifier) as a receipt.

Discipline (ooptdd): event literals live ONLY in this adapter. `verify(backend,cid)` drives the REAL
c1verify reproducible reverifier (re-implementation forbidden) over bundles ASSEMBLED from a REAL
engine DatasetManifest (built with lakatos.io.lineage), and ships the S2 oracles as a structured
trace. This adapter is engine-side (it may import lakatos.io.lineage to build+seal a real manifest and
to serve as the golden reference); the verifier under test imports zero engine code.

Two independent tamper classes are measured (both must be fully rejected):
  manifest_substitution_reject_rate — swap the sealed manifest for a different one, pin unchanged.
  broken_lineage_reject_rate        — re-seal (matching pin) a manifest whose lineage does NOT rebuild
                                      from raw (gap / wrong declared root / missing env / unrecorded
                                      final / cycle) — distinct class from the sha swap.
Negative oracle: a reproducible variant WITHOUT the sha-pin ACCEPTs the swap, and a variant WITHOUT
the lineage check ACCEPTs a broken-lineage manifest => BOTH guards are load-bearing (revert-proof).
Golden cross-check: c1verify's reproducible decision agrees with lakatos.io.lineage.verify_dataset_
manifest(...).passed over a corpus, and the honest real-manifest bundle ACCEPTs.

# KG: LakatosTree_C1ExternalVerifier_20260708 / s2-reproducible-rebuild
"""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import c1verify  # noqa: E402 — the real external verifier (drive, don't reimplement)
from c1verify.jcs import jcs  # noqa: E402

from lakatos.io.lineage import (  # noqa: E402 — engine-side seal source + golden reference (assembler only)
    Derivation, EnvironmentFingerprint, dataset_manifest_from_derivations,
    manifest_from_dict, manifest_to_dict, verify_dataset_manifest,
)

_AS_OF = "2026-07-09T00:00:00+00:00"   # fixed for a deterministic bundle (S2 does not check freshness)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "c1verify.S2.reproducible", "event": name, **attrs}


def _real_manifest_dict() -> dict:
    """A REAL engine DatasetManifest (built with lakatos.io.lineage) that passes G-RebuildFromRaw:
    raw.zdf(source) -> mid.bin -> final.bin, environment fingerprint present."""
    derivations = [
        Derivation(output="raw.zdf", output_sha="a" * 16, producer="", producer_sha="",
                   inputs=[], kind="source"),
        Derivation(output="mid.bin", output_sha="b" * 16, producer="step1.py", producer_sha="s1",
                   inputs=[("raw.zdf", "a" * 16)], kind="intermediate"),
        Derivation(output="final.bin", output_sha="c" * 16, producer="step2.py", producer_sha="s2",
                   inputs=[("mid.bin", "b" * 16)], kind="final"),
    ]
    env = EnvironmentFingerprint(python="3.14.4", platform="Linux")
    manifest = dataset_manifest_from_derivations("final.bin", derivations, environment=env)
    return manifest_to_dict(manifest)


def _sha(manifest_dict: dict) -> str:
    return hashlib.sha256(jcs(manifest_dict)).hexdigest()


def build_reproducible_bundle(manifest_dict: dict | None = None, pin: str | None = None) -> bytes:
    """Assemble a canonical bundle sealing `manifest_dict` (default: the real manifest) with `pin`
    (default: the correct sha). Override manifest_dict/pin to model tampering."""
    md = _real_manifest_dict() if manifest_dict is None else manifest_dict
    seal = _sha(md) if pin is None else pin
    return jcs({
        "c1_bundle_version": 1,
        "evidence_window": {"as_of": _AS_OF, "shas": {"reproducible": seal}},
        "gates": {"reproducible": {"manifest": md}},
    })


def _reproducible_decision(bundle_bytes: bytes) -> dict:
    report = c1verify.verify(bundle_bytes)
    return next(g for g in report["per_gate"] if g["gate"] == "reproducible")


def _swapped_manifests() -> list:
    """Manifests that DIFFER from the honest one (so a stale pin no longer matches), each still a
    structurally-valid manifest — the swap must die on the sha-pin, not on the lineage check."""
    base = _real_manifest_dict()
    reshaded = copy.deepcopy(base)
    reshaded["derivations"][2]["output_sha"] = "d" * 16          # different final output sha
    relabelled = copy.deepcopy(base)
    relabelled["metadata"] = {"note": "a nicer-looking manifest"}  # extra metadata
    extended = copy.deepcopy(base)
    extended["derivations"].append(
        {"output": "sidecar.bin", "output_sha": "e" * 16, "producer": "aux.py", "producer_sha": "s3",
         "inputs": [["raw.zdf", "a" * 16]], "params": {}, "kind": "intermediate", "ts": "", "env": ""})
    return [("reshaded_output", reshaded), ("added_metadata", relabelled), ("added_sidecar", extended)]


def _broken_lineage_manifests() -> list:
    """Manifests that FAIL verify_dataset_manifest, each RE-SEALED with a MATCHING pin so the sha
    check passes — the LINEAGE check must still REJECT (distinct tamper class from the swap)."""
    gap = _real_manifest_dict()
    gap["derivations"] = [d for d in gap["derivations"] if d["output"] != "mid.bin"]  # dangling link

    wrong_root = _real_manifest_dict()
    wrong_root["root_artifacts"] = ["not_the_real_root.zdf"]

    no_env = _real_manifest_dict()
    no_env["environment"] = {"python": "", "platform": "", "package_locks": {},
                             "env_vars": {}, "tool_versions": {}}

    unrecorded = _real_manifest_dict()
    unrecorded["final_artifact"] = "ghost.bin"                    # not produced by any derivation

    cycle = _real_manifest_dict()
    for d in cycle["derivations"]:
        if d["output"] == "mid.bin":
            d["inputs"] = [["raw.zdf", "a" * 16], ["final.bin", "c" * 16]]  # final -> mid -> final

    return [("gap", gap), ("wrong_root", wrong_root), ("missing_env", no_env),
            ("unrecorded_final", unrecorded), ("cycle", cycle)]


def manifest_substitution_reject_rate() -> float:
    """Swap the sealed manifest for a different one, leaving the pin on the ORIGINAL — must REJECT."""
    honest_pin = _sha(_real_manifest_dict())
    cases = _swapped_manifests()
    rejected = sum(1 for _label, md in cases
                   if _reproducible_decision(build_reproducible_bundle(md, honest_pin))["decision"]
                   == c1verify.REJECT)
    return rejected / len(cases)


def broken_lineage_reject_rate() -> float:
    """Re-seal (MATCHING pin) a manifest whose lineage does NOT rebuild from raw — the lineage check
    must REJECT even though the sha matches. Distinct tamper class from the manifest swap."""
    cases = _broken_lineage_manifests()
    rejected = sum(1 for _label, md in cases
                   if _reproducible_decision(build_reproducible_bundle(md, _sha(md)))["decision"]
                   == c1verify.REJECT)
    return rejected / len(cases)


def _malformed_manifests() -> list:
    """Attacker-controlled malformed manifests the ENGINE cannot cleanly evaluate (it raises building
    the EnvironmentFingerprint from a junk value, or on an unhashable root element). c1verify must fail
    CLOSED — return a REJECT decision, never raise — which is totality on adversarial bytes (the honest
    keystone the whole campaign stands on). These are NOT fed to the engine golden (it raises)."""
    return [
        ("keyless_derivation", {"final_artifact": "final.bin", "root_artifacts": ["raw.zdf"],
            "derivations": [{"output": "raw.zdf", "inputs": []},
                            {"output": "final.bin", "inputs": [["X", ""]]}, {"output": "X"}],
            "environment": {"python": "3.14"}}),
        ("nonstring_root", {"final_artifact": "f", "root_artifacts": [["r"]],
            "derivations": [{"output": "f", "inputs": []}], "environment": {"python": "3.14"}}),
        ("junk_str_env", {"final_artifact": "f", "root_artifacts": ["f"],
            "derivations": [{"output": "f", "inputs": []}], "environment": {"package_locks": "junk"}}),
        ("junk_bool_env", {"final_artifact": "f", "root_artifacts": ["f"],
            "derivations": [{"output": "f", "inputs": []}], "environment": {"tool_versions": True}}),
    ]


def totality_reject_rate_on_malformed() -> float:
    """Every malformed manifest yields a REJECT decision and verify() NEVER raises (fail-closed
    totality). A raise (uncounted) OR an ACCEPT drops the rate below 1.0 => receipt RED."""
    cases = _malformed_manifests()
    ok = 0
    for _label, md in cases:
        try:
            dec = _reproducible_decision(build_reproducible_bundle(md, _sha(md)))
            ok += (dec["decision"] == c1verify.REJECT)
        except Exception:   # noqa: BLE001 — a raise IS the totality failure we are testing for
            pass
    return ok / len(cases)


def negative_oracle_both_guards_load_bearing() -> bool:
    """Two defect injections. (1) drop the sha-pin clause => a manifest swap ACCEPTs. (2) drop the
    lineage clause => a broken-lineage manifest ACCEPTs. The real reverifier REJECTs both (revert-proof)."""
    # (1) sha-pin is load-bearing: swap the manifest, keep the stale pin.
    swap_md = _swapped_manifests()[0][1]
    stale_pin = _sha(_real_manifest_dict())
    assert _reproducible_decision(build_reproducible_bundle(swap_md, stale_pin))["decision"] \
        == c1verify.REJECT, "real reproducible did not reject a manifest swap"

    def _no_pin(payload):
        """reproducible WITHOUT the sha-pin check (lineage-only) — the swap slips through."""
        md = payload.get("manifest")
        ok = verify_dataset_manifest(manifest_from_dict(md), current_shas=None,
                                     require_environment=True).passed
        return c1verify.ACCEPT if ok else c1verify.REJECT
    assert _no_pin({"manifest": swap_md}) == c1verify.ACCEPT, \
        "dropping the sha-pin did NOT accept the swap — pin negative oracle vacuous"

    # (2) lineage check is load-bearing: a broken manifest, re-sealed with a MATCHING pin.
    broken_md = _broken_lineage_manifests()[0][1]   # the gap case
    assert _reproducible_decision(build_reproducible_bundle(broken_md, _sha(broken_md)))["decision"] \
        == c1verify.REJECT, "real reproducible did not reject a broken-lineage manifest"

    def _pin_only(payload, ctx):
        """reproducible WITHOUT the lineage check (sha-pin only) — the broken lineage slips through."""
        md = payload.get("manifest")
        pin = ctx["evidence_window"]["shas"]["reproducible"]
        return c1verify.ACCEPT if _sha(md) == pin else c1verify.REJECT
    slipped = _pin_only({"manifest": broken_md},
                        {"evidence_window": {"shas": {"reproducible": _sha(broken_md)}}})
    assert slipped == c1verify.ACCEPT, \
        "dropping the lineage check did NOT accept the broken manifest — lineage negative oracle vacuous"
    return True


def golden_agrees_with_engine() -> bool:
    """Out-of-band copy-fidelity: c1verify's reproducible decision == lakatos.io.lineage.verify_dataset_
    manifest(...).passed over a corpus, and the honest real-manifest bundle ACCEPTs. (Runs where both
    are importable, i.e. engine CI.)"""
    corpus = [("honest", _real_manifest_dict())] + _broken_lineage_manifests()
    for label, md in corpus:
        c1_accept = (_reproducible_decision(build_reproducible_bundle(md, _sha(md)))["decision"]
                     == c1verify.ACCEPT)
        engine_pass = verify_dataset_manifest(manifest_from_dict(md), current_shas=None,
                                              require_environment=True).passed
        assert c1_accept == engine_pass, \
            f"golden disagreement on {label!r}: c1verify ACCEPT={c1_accept} != engine passed={engine_pass}"
    honest = _reproducible_decision(build_reproducible_bundle())
    assert honest["decision"] == c1verify.ACCEPT, f"honest real-manifest bundle rejected: {honest['reason']}"
    return True


def verify(backend, cid):
    """Drive the real reproducible reverifier and ship the S2 oracles. Failures raise (RED)."""
    # ① honest — the bundle sealing a REAL engine manifest ACCEPTs and surfaces its residual (not 'trust').
    honest = _reproducible_decision(build_reproducible_bundle())
    assert honest["decision"] == c1verify.ACCEPT and honest["residual_trust_surface"], \
        f"honest reproducible not ACCEPT-with-residual: {honest}"
    backend.ship([_ev(cid, "c1_reproducible_honest_accept",
                      derivations=len(_real_manifest_dict()["derivations"]),
                      residual_named=bool(honest["residual_trust_surface"]))])

    # ② manifest substitution — swapping the sealed manifest (stale pin) is REJECTed every time.
    msr = manifest_substitution_reject_rate()
    assert msr == 1.0, f"manifest_substitution_reject_rate={msr} != 1.0 (a swap slipped past the pin)"
    backend.ship([_ev(cid, "c1_reproducible_manifest_substitution_reject", reject_rate=msr)])

    # ③ broken lineage — a re-sealed (matching pin) manifest that fails rebuild-from-raw is REJECTed.
    blr = broken_lineage_reject_rate()
    assert blr == 1.0, f"broken_lineage_reject_rate={blr} != 1.0 (a broken lineage slipped past)"
    backend.ship([_ev(cid, "c1_reproducible_broken_lineage_reject", reject_rate=blr)])

    # ④ negative oracle — BOTH the sha-pin and the lineage check are load-bearing (drop either => slip).
    assert negative_oracle_both_guards_load_bearing()
    backend.ship([_ev(cid, "c1_reproducible_negative_oracle", both_guards_load_bearing=True)])

    # ⑤ golden cross-check — the reproducible decision agrees with the engine verify_dataset_manifest.
    assert golden_agrees_with_engine()
    backend.ship([_ev(cid, "c1_reproducible_golden", agrees_with_engine=True)])

    # ⑥ totality — every malformed/attacker-controlled manifest yields a REJECT (verify() never raises).
    trr = totality_reject_rate_on_malformed()
    assert trr == 1.0, f"totality_reject_rate_on_malformed={trr} != 1.0 (verify() raised / over-accepted)"
    backend.ship([_ev(cid, "c1_reproducible_totality", reject_rate=trr, cases=len(_malformed_manifests()))])
