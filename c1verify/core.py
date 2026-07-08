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

from .jcs import JcsError, parse_canonical

C1_BUNDLE_VERSION = 1

#: The five certificate gates plus the cryptographic substrate. certified = AND over all of them.
GATES = ("preregistered", "reproducible", "stands", "calibrated", "grounded", "substrate")

ACCEPT = "ACCEPT"
REJECT = "REJECT"

_ALLOWED_TOP = frozenset(("c1_bundle_version", "gates"))

#: Slices S1.. replace entries here with real fail-closed reverifiers gate -> (bundle -> decision dict).
#: Empty in S0 => every gate takes the default REJECT branch (the empty ACCEPT set).
_GATE_REVERIFIERS: dict = {}


def _reject_all(reason: str) -> dict:
    """A whole-bundle rejection: every gate REJECTs with the same parse/envelope reason."""
    per_gate = [{"gate": g, "decision": REJECT, "reason": reason, "residual_trust_surface": None}
                for g in GATES]
    return {"per_gate": per_gate, "certified": False, "missing": list(GATES), "residuals": []}


def _default_gate_decision(gate: str) -> dict:
    return {"gate": gate, "decision": REJECT,
            "reason": "gate reverification not implemented (fail-closed skeleton default)",
            "residual_trust_surface": None}


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

    per_gate = []
    for gate in GATES:
        reverifier = _GATE_REVERIFIERS.get(gate)
        if reverifier is None:
            per_gate.append(_default_gate_decision(gate))
        else:  # slices S1.. — a real fail-closed reverifier; still REJECTs unless it proves ACCEPT
            per_gate.append(reverifier(gates.get(gate)))

    accepted = [g for g in per_gate if g["decision"] == ACCEPT]
    certified = len(GATES) > 0 and len(accepted) == len(GATES)
    missing = [g["gate"] for g in per_gate if g["decision"] != ACCEPT]
    return {"per_gate": per_gate, "certified": certified, "missing": missing, "residuals": []}
