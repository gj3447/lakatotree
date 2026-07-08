"""grounded gate reverifier (C1 S1) — re-derive from sealed bytes, never trust a pointer.

The engine's grounded gate proves: the citation-constant registry is non-empty AND every constant
declares a tier in {literature, policy_in_scale, policy}. Its certificate evidence_ref is the POINTER
string 'lakatos/grounding.py GROUNDED tier registry' — an outsider cannot re-check a pointer.

C1 replaces the pointer with re-derivation. The bundle CARRIES the registry content-sealed, and its
sha is pinned in evidence_window.shas.grounding. This reverifier:
  1. recomputes sha256(JCS(registry)) and REJECTs unless it equals the sealed pin
     — SNAPSHOT SUBSTITUTION (swap the scored registry for a nicer one after sealing) dies here;
  2. REJECTs an empty/absent registry (bool(registry));
  3. REJECTs unless EVERY constant declares a tier in the allowlist.
Anything missing/opaque => REJECT (fail-closed). VALID_TIERS is re-implemented here, not imported;
its agreement with the engine is pinned by an out-of-band golden test that runs only in engine CI.

Enumerated residual (never discharged): this proves the shown registry is the SEALED one and its
tiers are IN the allowlist — NOT that each declared tier is TRUTHFUL (a policy value mislabelled
'literature' is a residual, out-of-band surface an ACCEPT names but does not close).
"""
from __future__ import annotations

import hashlib

from .._decision import ACCEPT, REJECT, gate_decision
from ..jcs import jcs

GATE = "grounded"

#: Re-implementation of the engine's grounded tier allowlist (evidence_claim_service valid_tiers /
#: grounding.py tiers). Copy-fidelity pinned by an engine-CI-only golden cross-check.
VALID_TIERS = frozenset(("literature", "policy_in_scale", "policy"))

_RESIDUAL = ("tier CORRECTNESS is out-of-band: the bundle proves each constant declares an "
             "allowlisted tier and the registry matches its sealed sha, NOT that a value labelled "
             "'literature' truly derives from the cited source (mislabelling is not re-derivable).")


def _reject(reason: str) -> dict:
    return gate_decision(GATE, REJECT, reason)


def verify_grounded(payload, ctx) -> dict:
    """payload = bundle['gates']['grounded'] = {'registry': {name: {tier, ...}}}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return _reject("grounded payload absent or not an object")
    registry = payload.get("registry")
    if not isinstance(registry, dict) or not registry:
        return _reject("grounding registry absent or empty (fail-closed; bool(registry) required)")

    evidence_window = (ctx or {}).get("evidence_window")
    pin = None
    if isinstance(evidence_window, dict) and isinstance(evidence_window.get("shas"), dict):
        pin = evidence_window["shas"].get("grounding")
    if not isinstance(pin, str) or not pin:
        return _reject("no evidence_window.shas.grounding pin — cannot content-seal the registry")

    actual = hashlib.sha256(jcs(registry)).hexdigest()
    if actual != pin:
        return _reject(f"registry does not match its sealed sha — snapshot substitution "
                       f"(recomputed {actual[:12]}… != pinned {pin[:12]}…)")

    ungrounded = sorted(name for name, entry in registry.items()
                        if not isinstance(entry, dict) or entry.get("tier") not in VALID_TIERS)
    if ungrounded:
        return _reject(f"{len(ungrounded)} constant(s) with no allowlisted tier "
                       f"{sorted(VALID_TIERS)}: {ungrounded[:5]}")

    return gate_decision(GATE, ACCEPT,
                         f"registry of {len(registry)} constants matches sealed sha; "
                         f"every tier in {sorted(VALID_TIERS)}",
                         residual_trust_surface=_RESIDUAL)
