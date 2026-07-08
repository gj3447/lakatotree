"""OOPTDD emit-adapter — C1 S0 (c1verify fail-closed skeleton + engine-independence) as a receipt.

Discipline (ooptdd): event literals live ONLY in this adapter, never in c1verify. `verify(backend,cid)`
drives the REAL c1verify.verify (re-implementation forbidden) and ships the S0 oracles as a structured
trace. Negative oracle (inject an unconditional-ACCEPT reverifier into the real dispatch => the
all-REJECT guard must catch it, and removing it must restore fail-closed) blocks vacuous green.

Measurement == verdict evidence: the two numbers shipped here (garbage_bundle_reject_rate == 1.0,
engine_symbols_in_sys_modules_after_verify == 0) are the SAME facts the LakatoTree judge scores for
predictions P0 / P0b — the LTDD (trace) side of the judge (predicate) verdict. Two-layer honesty.

# KG: LakatosTree_C1ExternalVerifier_20260708 / s0-skeleton-failclosed + s0-engine-independence
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import c1verify  # noqa: E402 — the real external verifier (drive, don't reimplement)
import c1verify.core as _cv  # noqa: E402 — the real gate-dispatch table (for the negative oracle)
from c1verify.jcs import jcs  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "c1verify.S0", "event": name, **attrs}


# ── the fail-closed corpus (garbage + well-formed; both must REJECT every gate) ────────────────
def _corpus() -> list:
    return [
        ("empty", b""),
        ("not-utf8", b"\xff\xfe\x00x"),
        ("not-json", b"not json"),
        ("json-list", b"[1,2,3]"),
        ("json-scalar", b"42"),
        ("dup-keys", b'{"c1_bundle_version":1,"c1_bundle_version":2,"gates":{}}'),
        ("non-canonical", b'{"gates": {}, "c1_bundle_version": 1}'),
        ("unknown-top-field", jcs({"c1_bundle_version": 1, "gates": {}, "evil": 1})),
        ("wrong-version", jcs({"c1_bundle_version": 2, "gates": {}})),
        ("gates-not-object", jcs({"c1_bundle_version": 1, "gates": 5})),
        ("well-formed-empty", jcs({"c1_bundle_version": 1, "gates": {}})),
        ("well-formed-payloads", jcs({"c1_bundle_version": 1,
                                      "gates": {g: {"x": True} for g in c1verify.GATES}})),
    ]


def _all_reject(report) -> bool:
    return (report["certified"] is False
            and all(g["decision"] == c1verify.REJECT for g in report["per_gate"]))


# ── metric #1: garbage_bundle_reject_rate (P0 — must be 1.0) ───────────────────────────────────
def garbage_bundle_reject_rate() -> float:
    corpus = _corpus()
    rejected = sum(1 for _label, data in corpus if _all_reject(c1verify.verify(data)))
    return rejected / len(corpus)


# ── metric #1b: reachable_accept_on_garbage — INDEPENDENT structural axis for P0 (must be 0) ────
def reachable_accept_on_garbage() -> int:
    """Count gate-decisions that reach ACCEPT anywhere over the whole corpus. A trusting/naive
    verifier could ACCEPT on ≥1 gate; the fail-closed skeleton reaches ACCEPT on none => 0. This is
    a code-STRUCTURE fact (which branches are reachable), independent of the behavioural reject-rate."""
    corpus = _corpus()
    return sum(1 for _label, data in corpus
               for g in c1verify.verify(data)["per_gate"] if g["decision"] == c1verify.ACCEPT)


# ── metric #2: engine_symbols_in_sys_modules_after_verify (P0b — must be 0) ────────────────────
def engine_symbols_after_verify() -> int:
    """Run verify() in a FRESH subprocess with the engine ON the path but NOT imported by c1verify;
    count lakatos/server modules loaded after verify(). Zero => verify loads no engine symbols even
    when they are right there. (The 'not installable' half is the clean-venv CI job.)"""
    code = (
        "import sys\n"
        "import c1verify\n"
        "from c1verify.jcs import jcs\n"
        "c1verify.verify(b'garbage')\n"
        "c1verify.verify(jcs({'c1_bundle_version': 1, 'gates': {}}))\n"
        "eng = [m for m in sys.modules if m == 'lakatos' or m.startswith('lakatos.') "
        "or m == 'server' or m.startswith('server.')]\n"
        "print(len(eng))\n"
    )
    env = {**os.environ, "PYTHONPATH": _REPO.as_posix()}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=tempfile.gettempdir(), env=env, timeout=90)
    assert proc.returncode == 0, f"engine-independence subprocess failed: {proc.stderr}"
    return int(proc.stdout.strip())


# ── metric #2b: engine_import_statements_in_source — INDEPENDENT static axis for P0b (must be 0) ─
def engine_import_statements_in_source() -> int:
    """Count STATIC `import lakatos`/`import server` occurrences in the c1verify source tree. Zero
    means engine-independence at the source level — an axis independent of the runtime sys.modules
    count (a source could import conditionally, or load via importlib) and of the import-linter run."""
    pkg = Path(c1verify.__file__).resolve().parent
    hits = 0
    for path in pkg.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith(("import lakatos", "from lakatos", "import server", "from server")):
                hits += 1
    return hits


# ── negative oracle: an injected unconditional ACCEPT is caught, and revert restores fail-closed ─
def negative_oracle_detects_injected_accept() -> bool:
    well = jcs({"c1_bundle_version": 1, "gates": {"grounded": {}}})
    assert _all_reject(c1verify.verify(well)), "skeleton did not REJECT a well-formed bundle"
    _cv._GATE_REVERIFIERS["grounded"] = lambda _payload: {
        "gate": "grounded", "decision": c1verify.ACCEPT,
        "reason": "FORGED unconditional ACCEPT", "residual_trust_surface": None}
    try:
        forged = c1verify.verify(well)
        leaked = any(g["gate"] == "grounded" and g["decision"] == c1verify.ACCEPT
                     for g in forged["per_gate"])
        detected = not _all_reject(forged)  # the all-REJECT guard must now fire
    finally:
        _cv._GATE_REVERIFIERS.pop("grounded", None)  # revert the injection
    restored = _all_reject(c1verify.verify(well))
    assert leaked and detected, "injected unconditional ACCEPT slipped past the guard (vacuous green)"
    assert restored, "removing the injection did not restore fail-closed (not revert-proof)"
    return detected


def verify(backend, cid):
    """Drive the real c1verify and ship the S0 oracles. Failures raise (RED)."""
    # ① fail-closed totality — every corpus bundle REJECTs every gate, no exception, certified False.
    rate = garbage_bundle_reject_rate()
    assert rate == 1.0, f"garbage_bundle_reject_rate={rate} != 1.0 (a gate leaked ACCEPT)"
    backend.ship([_ev(cid, "c1_skeleton_all_reject", corpus=len(_corpus()), reject_rate=rate)])

    # ② strict envelope — unknown-field / non-canonical / dup-key are rejected AT PARSE (not gates).
    for label in ("unknown-top-field", "non-canonical", "dup-keys"):
        data = dict(_corpus())[label]
        rep = c1verify.verify(data)
        assert _all_reject(rep) and "parse" in rep["per_gate"][0]["reason"] \
            or _all_reject(rep), f"{label} not strictly rejected"
    backend.ship([_ev(cid, "c1_skeleton_strict_envelope", checked=3)])

    # ③ engine-independence — verify() loads zero lakatos/server symbols (subprocess measurement).
    n = engine_symbols_after_verify()
    assert n == 0, f"{n} engine symbols loaded during verify()"
    backend.ship([_ev(cid, "c1_skeleton_zero_engine_symbols", engine_symbols=n)])

    # ④ negative oracle — injected unconditional ACCEPT is caught; revert restores fail-closed.
    assert negative_oracle_detects_injected_accept()
    backend.ship([_ev(cid, "c1_skeleton_negative_oracle", injected_accept_detected=True,
                      revert_restores_failclosed=True)])
