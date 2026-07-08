"""OOPTDD emit-adapter — C1 S1 (grounded gate sha-pin reverifier) as a receipt.

Discipline (ooptdd): event literals live ONLY in this adapter. `verify(backend,cid)` drives the REAL
c1verify grounded reverifier (re-implementation forbidden) over bundles ASSEMBLED from the real engine
GROUNDED registry, and ships the S1 oracles as a structured trace. This adapter is engine-side (it may
import lakatos.grounding to SEAL the registry); the verifier under test imports zero engine code.

Two independent tamper classes are measured (both must be fully rejected):
  snapshot_substitution_reject_rate — swap the sealed registry for a different one, pin unchanged.
  bogus_tier_reject_rate            — flip one constant's tier to a value outside the allowlist.
Negative oracle: a grounded variant WITHOUT the sha-pin check ACCEPTs the swap => the pin is
load-bearing (revert-proof). Golden cross-check: c1verify.VALID_TIERS agrees with the engine's tiers
and the honest bundle built from the real GROUNDED ACCEPTs.

# KG: LakatosTree_C1ExternalVerifier_20260708 / s1-grounded-sha-pin
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
from c1verify.gates import grounded as cg  # noqa: E402 — the reverifier under test
from c1verify.jcs import jcs  # noqa: E402

from lakatos.grounding import GROUNDED  # noqa: E402 — engine-side seal source (assembler only)

_AS_OF = "2026-07-09T00:00:00+00:00"   # fixed for a deterministic bundle (S1 does not check freshness)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "c1verify.S1.grounded", "event": name, **attrs}


def _sha(registry: dict) -> str:
    return hashlib.sha256(jcs(registry)).hexdigest()


def build_grounded_bundle(registry: dict | None = None, pin: str | None = None) -> bytes:
    """Assemble a canonical bundle sealing `registry` (default: the real GROUNDED) with `pin`
    (default: the correct sha of `registry`). Override registry/pin to model tampering."""
    reg = GROUNDED if registry is None else registry
    seal = _sha(reg) if pin is None else pin
    return jcs({
        "c1_bundle_version": 1,
        "evidence_window": {"as_of": _AS_OF, "shas": {"grounding": seal}},
        "gates": {"grounded": {"registry": reg}},
    })


def _grounded_decision(bundle_bytes: bytes) -> dict:
    report = c1verify.verify(bundle_bytes)
    return next(g for g in report["per_gate"] if g["gate"] == "grounded")


def _swapped_registries() -> list:
    """Registries that DIFFER from GROUNDED (so a stale pin no longer matches)."""
    add = copy.deepcopy(GROUNDED)
    add["injected_backdoor"] = {"value": 0.0, "source": "policy", "tier": "policy"}
    drop = {k: v for k, v in GROUNDED.items() if k != next(iter(GROUNDED))}
    edit = copy.deepcopy(GROUNDED)
    edit[next(iter(edit))] = {**next(iter(edit.values())), "value": -999.0}
    return [("added_constant", add), ("dropped_constant", drop), ("edited_value", edit)]


def snapshot_substitution_reject_rate() -> float:
    """Swap the sealed registry for a different one, leaving the pin on the ORIGINAL — must REJECT."""
    honest_pin = _sha(GROUNDED)
    cases = _swapped_registries()
    rejected = sum(1 for _label, reg in cases
                   if _grounded_decision(build_grounded_bundle(reg, honest_pin))["decision"]
                   == c1verify.REJECT)
    return rejected / len(cases)


def _bogus_tier_registries() -> list:
    out = []
    for name in list(GROUNDED)[:3]:
        bad = copy.deepcopy(GROUNDED)
        bad[name] = {**bad[name], "tier": "bogus_totally_made_up"}
        out.append((name, bad))
    return out


def bogus_tier_reject_rate() -> float:
    """Flip one constant's tier to a non-allowlisted value and RE-SEAL with a MATCHING pin (so the
    sha check passes) — the tier check must still REJECT. Distinct tamper class from snapshot swap."""
    cases = _bogus_tier_registries()
    rejected = sum(1 for _name, reg in cases
                   if _grounded_decision(build_grounded_bundle(reg, _sha(reg)))["decision"]
                   == c1verify.REJECT)
    return rejected / len(cases)


def negative_oracle_pin_is_load_bearing() -> bool:
    """A grounded variant WITHOUT the sha-pin check ACCEPTs a snapshot swap => the real pin check is
    load-bearing. The real reverifier must REJECT the same swap; removing the check flips it (RED)."""
    swap_reg = _swapped_registries()[0][1]
    stale_pin = _sha(GROUNDED)
    bundle = build_grounded_bundle(swap_reg, stale_pin)

    real = _grounded_decision(bundle)
    assert real["decision"] == c1verify.REJECT, "real grounded did not reject a snapshot swap"

    # defect injection: reverify grounded WITHOUT the sha-pin clause (everything else identical).
    def _no_pin(payload, ctx):
        registry = payload.get("registry")
        if not isinstance(registry, dict) or not registry:
            return {"gate": "grounded", "decision": c1verify.REJECT, "reason": "empty",
                    "residual_trust_surface": None}
        bad = [n for n, e in registry.items()
               if not isinstance(e, dict) or e.get("tier") not in cg.VALID_TIERS]
        dec = c1verify.REJECT if bad else c1verify.ACCEPT
        return {"gate": "grounded", "decision": dec, "reason": "no-pin variant",
                "residual_trust_surface": None}

    forged = _no_pin({"registry": swap_reg}, {"evidence_window": {"shas": {"grounding": stale_pin}}})
    detected = forged["decision"] == c1verify.ACCEPT  # the swap slips through WITHOUT the pin check
    assert detected, "dropping the sha-pin check did NOT accept the swap — negative oracle vacuous"
    return detected


def golden_tiers_agree_with_engine() -> bool:
    """Out-of-band copy-fidelity: c1verify's re-implemented tier allowlist == the engine's, and the
    honest bundle sealing the REAL GROUNDED ACCEPTs. (Runs where both are importable, i.e. engine CI.)"""
    engine_tiers = {g["tier"] for g in GROUNDED.values()}
    assert engine_tiers <= cg.VALID_TIERS, f"engine uses a tier c1verify rejects: {engine_tiers - cg.VALID_TIERS}"
    assert cg.VALID_TIERS == frozenset(("literature", "policy_in_scale", "policy"))
    honest = _grounded_decision(build_grounded_bundle())
    assert honest["decision"] == c1verify.ACCEPT, f"honest real-GROUNDED bundle rejected: {honest['reason']}"
    return True


def verify(backend, cid):
    """Drive the real grounded reverifier and ship the S1 oracles. Failures raise (RED)."""
    # ① honest — the bundle sealing the real GROUNDED ACCEPTs, and surfaces its residual (not 'trust').
    honest = _grounded_decision(build_grounded_bundle())
    assert honest["decision"] == c1verify.ACCEPT and honest["residual_trust_surface"], \
        f"honest grounded not ACCEPT-with-residual: {honest}"
    backend.ship([_ev(cid, "c1_grounded_honest_accept", constants=len(GROUNDED),
                      residual_named=bool(honest["residual_trust_surface"]))])

    # ② snapshot substitution — swapping the sealed registry (stale pin) is REJECTed every time.
    ssr = snapshot_substitution_reject_rate()
    assert ssr == 1.0, f"snapshot_substitution_reject_rate={ssr} != 1.0 (a swap slipped past the pin)"
    backend.ship([_ev(cid, "c1_grounded_snapshot_reject", reject_rate=ssr)])

    # ③ bogus tier — a re-sealed registry with an off-allowlist tier is REJECTed (distinct class).
    btr = bogus_tier_reject_rate()
    assert btr == 1.0, f"bogus_tier_reject_rate={btr} != 1.0 (an ungrounded tier slipped past)"
    backend.ship([_ev(cid, "c1_grounded_bogustier_reject", reject_rate=btr)])

    # ④ negative oracle — the sha-pin is load-bearing (drop it => the swap ACCEPTs).
    assert negative_oracle_pin_is_load_bearing()
    backend.ship([_ev(cid, "c1_grounded_negative_oracle", pin_is_load_bearing=True)])

    # ⑤ golden cross-check — re-implemented tiers agree with the engine; real GROUNDED ACCEPTs.
    assert golden_tiers_agree_with_engine()
    backend.ship([_ev(cid, "c1_grounded_golden_tiers", agree=True)])
