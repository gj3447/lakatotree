"""reproducible gate reverifier (C1 S2) — re-derive raw-rootedness from sealed bytes, never trust.

The engine's reproducible gate proves: the measurement's DatasetManifest passes G-RebuildFromRaw —
the final artifact is regenerable from declared raw roots (lineage is raw-rooted, gapless, root-
consistent, acyclic) with an environment fingerprint present (lakatos.io.lineage.verify_dataset_
manifest). Its certificate evidence_ref is a POINTER (a manifest path / a lineage node id) — an
outsider cannot re-check a pointer; they must trust the engine.

C1 replaces the pointer with re-derivation. The bundle CARRIES the manifest content-sealed, and its
sha is pinned in evidence_window.shas.reproducible. This reverifier:
  1. recomputes sha256(JCS(manifest)) and REJECTs unless it equals the sealed pin
     — MANIFEST SUBSTITUTION (swap the scored manifest for a nicer one after sealing) dies here;
  2. re-derives verify_dataset_manifest's DISK-FREE checks over the sealed derivation DAG and
     REJECTs unless it PASSES: final artifact recorded, no lineage cycle, actual roots == declared
     roots, no reproducibility gap (broken lineage link), environment fingerprint present
     — BROKEN LINEAGE (a gap / a wrong declared root / a missing env / an unrecorded artifact) dies
     here, even with a matching pin (distinct tamper class from manifest swap).
Anything missing/opaque => REJECT (fail-closed). The graph predicates are re-implemented here, not
imported; agreement with lakatos.io.lineage is pinned by an out-of-band golden test that runs only in
engine CI.

Enumerated residual (never discharged): input-sha staleness against the LIVE raw files. The bundle
seals RECORDED input shas, not the raw bytes; a recorded input_sha that no longer matches the current
on-disk raw file (lineage.verify_dataset_manifest's `current_shas`/`stale_inputs` path) is only
detectable with the raw root present — out-of-band. This ACCEPT proves the lineage is internally raw-
rooted, gapless, root-consistent and acyclic, NOT that the recorded raw shas still match live disk.
"""
from __future__ import annotations

import hashlib

from .._decision import ACCEPT, REJECT, gate_decision
from ..jcs import jcs

GATE = "reproducible"

_RESIDUAL = ("this re-derives the lineage TOPOLOGY only (raw-rooted, gapless, root-consistent, "
             "acyclic, env-fingerprint present) from the sealed manifest; the following are CARRIED "
             "but NOT discharged and stay out-of-band: (1) every recorded sha (root/intermediate/"
             "final output_sha, input_sha, producer_sha) is trusted, not content-verified — the bundle "
             "seals shas, not the raw/derived bytes; (2) internal sha consistency (a derivation's "
             "input_sha vs its upstream output_sha) is NOT cross-checked; (3) input-sha staleness vs "
             "the LIVE raw files needs the raw root present; (4) producer self-report integrity and "
             "measurer!=producer (lakatos.io.lineage M1, kind='measurement') are NOT enforced; "
             "(5) tolerance is carried, not evaluated. ACCEPT means the lineage GRAPH rebuilds from "
             "declared raw roots, NOT that the artifacts actually regenerate to their claimed shas.")


def _reject(reason: str) -> dict:
    return gate_decision(GATE, REJECT, reason)


def _by_output(derivations: list) -> dict | None:
    """{output_path: derivation}. None if a derivation is malformed (fail-closed). `inputs` is
    NORMALISED to a validated list (a missing key => [], mirroring the engine's derivation_from_dict)
    so every graph predicate can dereference d["inputs"] uniformly without a KeyError (totality)."""
    bo: dict = {}
    for d in derivations:
        if not isinstance(d, dict) or not isinstance(d.get("output"), str):
            return None
        inputs = d.get("inputs", [])
        if not isinstance(inputs, list) or any(
                not (isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str))
                for pair in inputs):
            return None
        bo[d["output"]] = {**d, "inputs": inputs}
    return bo


def _roots(artifact: str, bo: dict, seen: frozenset = frozenset()) -> set:
    """Ultimate source (root) artifacts of `artifact` — mirrors lakatos.io.lineage.roots.
    A revisited node (cycle) contributes {} here; the cycle itself is caught by _has_cycle."""
    if artifact in seen:
        return set()
    seen = seen | {artifact}
    d = bo.get(artifact)
    if d is None or not d.get("inputs"):
        return {artifact}
    out: set = set()
    for path, _ in d["inputs"]:
        out |= _roots(path, bo, seen)
    return out


def _gaps(final: str, bo: dict, sources: set, seen: frozenset = frozenset()) -> set:
    """Non-source artifacts with no derivation between `final` and the sources (broken links).
    Empty => reproducible. Mirrors lakatos.io.lineage.reproducibility_gaps (cycle => {final})."""
    if final in sources:
        return set()
    if final in seen:
        return {final}
    seen = seen | {final}
    d = bo.get(final)
    if d is None:
        return {final}
    out: set = set()
    for path, _ in d["inputs"]:
        out |= _gaps(path, bo, sources, seen)
    return out


def _has_cycle(final: str, bo: dict) -> bool:
    """Back-edge on the final->inputs DAG — mirrors the raise in lakatos.io.lineage.rebuild_plan."""
    visiting: set = set()
    done: set = set()

    def visit(art: str) -> bool:
        if art in done:
            return False
        if art in visiting:
            return True
        visiting.add(art)
        d = bo.get(art)
        if d is not None and d.get("inputs"):
            for path, _ in d["inputs"]:
                if visit(path):
                    return True
        visiting.discard(art)
        done.add(art)
        return False

    return visit(final)


def _environment_present(environment) -> bool:
    """Mirror lakatos.io.lineage.EnvironmentFingerprint's TYPED model: python/platform are strings,
    package_locks/env_vars/tool_versions are dicts. A junk-typed value (a string package_locks, a bool
    tool_versions) is NOT a real fingerprint field — count it absent so it fails closed (REJECT),
    never an ACCEPT the engine could not itself represent."""
    if not isinstance(environment, dict):
        return False
    if any(isinstance(environment.get(k), str) and environment[k] for k in ("python", "platform")):
        return True
    return any(isinstance(environment.get(k), dict) and environment[k]
               for k in ("package_locks", "env_vars", "tool_versions"))


def verify_reproducible(payload, ctx) -> dict:
    """payload = bundle['gates']['reproducible'] = {'manifest': <manifest_dict>}. Total, fail-closed.

    Re-derives lakatos.io.lineage.verify_dataset_manifest's DISK-FREE half (current_shas=None,
    require_environment=True) over the sealed manifest and REJECTs unless it PASSES."""
    if not isinstance(payload, dict):
        return _reject("reproducible payload absent or not an object")
    manifest = payload.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        return _reject("manifest absent or not an object (fail-closed)")

    evidence_window = (ctx or {}).get("evidence_window")
    pin = None
    if isinstance(evidence_window, dict) and isinstance(evidence_window.get("shas"), dict):
        pin = evidence_window["shas"].get("reproducible")
    if not isinstance(pin, str) or not pin:
        return _reject("no evidence_window.shas.reproducible pin — cannot content-seal the manifest")

    actual = hashlib.sha256(jcs(manifest)).hexdigest()
    if actual != pin:
        return _reject(f"manifest does not match its sealed sha — manifest substitution "
                       f"(recomputed {actual[:12]}… != pinned {pin[:12]}…)")

    # ── lineage re-derivation (verify_dataset_manifest, disk-free) ──────────────────────────────
    final = manifest.get("final_artifact")
    if not isinstance(final, str) or not final:
        return _reject("manifest has no final_artifact")
    derivations = manifest.get("derivations")
    if not isinstance(derivations, list):
        return _reject("manifest derivations absent or not a list")
    bo = _by_output(derivations)
    if bo is None:
        return _reject("manifest contains a malformed derivation (fail-closed)")
    if final not in bo:
        return _reject(f"final artifact {final!r} is unrecorded (not produced by any derivation)")
    if _has_cycle(final, bo):
        return _reject("lineage cycle — final artifact is not regenerable from raw roots")

    declared = manifest.get("root_artifacts")
    if not isinstance(declared, list):
        return _reject("manifest root_artifacts absent or not a list")
    if any(not isinstance(r, str) for r in declared):
        return _reject("root_artifacts contains a non-string entry (fail-closed)")
    declared_roots = set(declared)

    # A dangling non-source artifact is BOTH a gap and (via _roots) a spurious root, so these two
    # reasons are coupled in lakatos.io.lineage; checking gaps first keeps each reason reachable in
    # isolation (a wrong DECLARED root with intact lineage triggers only the root mismatch). Order
    # does not change the decision: the engine's `passed` is the AND of both regardless.
    gaps = _gaps(final, bo, declared_roots)
    if gaps:
        return _reject(f"reproducibility gap(s) {sorted(gaps)[:5]} — non-source artifact(s) with no "
                       f"derivation (broken lineage link, not regenerable from raw)")

    actual_roots = _roots(final, bo)
    if actual_roots != declared_roots:
        return _reject(f"root manifest mismatch — declared roots {sorted(declared_roots)} != "
                       f"actual roots {sorted(actual_roots)} (raw-rootedness not re-derivable)")

    if not _environment_present(manifest.get("environment")):
        return _reject("environment fingerprint missing — rebuild is not reproducible without it")

    return gate_decision(GATE, ACCEPT,
                         f"manifest of {len(derivations)} derivation(s) matches sealed sha; lineage "
                         f"topology of final {final!r} is raw-rooted from declared roots "
                         f"{sorted(declared_roots)} (gapless, root-consistent, acyclic, env present); "
                         f"recorded shas carried, not content-verified",
                         residual_trust_surface=_RESIDUAL)
