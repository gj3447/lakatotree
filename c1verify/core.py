"""Top-level verifier — fail-closed skeleton (S0).

verify(bytes) -> report. TOTALITY: it never raises and never returns a half-trusted value; every
gate DEFAULTS to REJECT (the ACCEPT set is empty in the skeleton). There is exactly one place per
gate where a decision could become ACCEPT, and in S0 no gate reaches it — gate reverification logic
lands slice by slice. `certified` is True only when EVERY gate ACCEPTs, so the skeleton is
永 REJECT, which is the honest behaviour: nothing has been re-derived yet, so nothing is certified.

No 'trust the pointer' branch exists anywhere. A missing/opaque/unknown/non-canonical bundle field
is a REJECT, never a silent pass. This is the honesty keystone the whole campaign stands on.
"""
from __future__ import annotations

from ._decision import ACCEPT, REJECT, gate_decision
from .jcs import JcsError, parse_canonical

C1_BUNDLE_VERSION = 1

#: The five certificate gates plus the cryptographic substrate. certified = AND over all of them.
GATES = ("preregistered", "reproducible", "stands", "calibrated", "grounded", "substrate")

#: Top-level bundle fields. evidence_window carries the {as_of, shas:{...}} pins that content-seal
#: each gate's payload (a gate recomputes its sha over the sealed bytes and matches it here).
_ALLOWED_TOP = frozenset(("c1_bundle_version", "evidence_window", "gates"))

#: gate -> reverifier(payload, ctx) -> decision dict. A gate absent here takes the default REJECT
#: (empty ACCEPT set). Slices S1.. register real fail-closed reverifiers (wired at the bottom).
_GATE_REVERIFIERS: dict = {}


def _reject_all(reason: str) -> dict:
    """A whole-bundle rejection: every gate REJECTs with the same parse/envelope reason."""
    per_gate = [gate_decision(g, REJECT, reason) for g in GATES]
    return {"per_gate": per_gate, "certified": False, "missing": list(GATES), "residuals": []}


def _default_gate_decision(gate: str) -> dict:
    return gate_decision(gate, REJECT,
                         "gate reverification not implemented (fail-closed skeleton default)")


def verify(data: bytes) -> dict:
    """Re-verify a certificate bundle. Total & fail-closed. Returns:
        {per_gate:[{gate,decision,reason,residual_trust_surface}], certified, missing, residuals}
    certified is True ONLY if every gate decision == ACCEPT. Any parse/envelope doubt => all REJECT.
    """
    try:
        bundle = parse_canonical(data)
    except JcsError as exc:
        return _reject_all(f"bundle rejected at parse (fail-closed): {exc}")

    unknown = sorted(set(bundle) - _ALLOWED_TOP)
    if unknown:
        return _reject_all(f"unknown top-level field(s) {unknown} (fail-closed)")
    if bundle.get("c1_bundle_version") != C1_BUNDLE_VERSION:
        return _reject_all(
            f"unsupported c1_bundle_version {bundle.get('c1_bundle_version')!r} "
            f"(expected {C1_BUNDLE_VERSION})")
    gates = bundle.get("gates")
    if not isinstance(gates, dict):
        return _reject_all("'gates' missing or not a JSON object")

    ctx = {"evidence_window": bundle.get("evidence_window")}
    per_gate = []
    for gate in GATES:
        reverifier = _GATE_REVERIFIERS.get(gate)
        if reverifier is None:
            per_gate.append(_default_gate_decision(gate))
        else:  # a real fail-closed reverifier; still REJECTs unless it PROVES ACCEPT from sealed bytes
            try:
                per_gate.append(reverifier(gates.get(gate), ctx))
            except Exception as exc:  # noqa: BLE001 — TOTALITY: a reverifier bug on attacker-controlled
                # bytes must degrade to REJECT, never escape verify() as a crash (fail-closed keystone).
                per_gate.append(gate_decision(
                    gate, REJECT, f"reverifier raised on the bundle (fail-closed): {type(exc).__name__}"))

    accepted = [g for g in per_gate if g["decision"] == ACCEPT]
    certified = len(GATES) > 0 and len(accepted) == len(GATES)
    missing = [g["gate"] for g in per_gate if g["decision"] != ACCEPT]
    return {"per_gate": per_gate, "certified": certified, "missing": missing, "residuals": []}


# ── gate reverifiers (registered after verify() is defined; each gate module imports only
#    _decision + jcs + receipts + judge, never core, so there is no import cycle) ────────────────
from .gates.grounded import verify_grounded  # noqa: E402
from .gates.preregistered import verify_preregistered  # noqa: E402
from .gates.reproducible import verify_reproducible  # noqa: E402
from .gates.substrate import verify_substrate  # noqa: E402

_GATE_REVERIFIERS["grounded"] = verify_grounded
_GATE_REVERIFIERS["substrate"] = verify_substrate
_GATE_REVERIFIERS["preregistered"] = verify_preregistered
_GATE_REVERIFIERS["reproducible"] = verify_reproducible
