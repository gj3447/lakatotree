# c1verify — External Certificate Verifier for LakatoTree (campaign C1)

Re-verify a lakatotree **Certificate** without trusting — or even installing — the engine.

Today the engine's certificate proves each of its five gates (`preregistered`, `reproducible`,
`stands`, `calibrated`, `grounded`) with an `evidence_ref` that is a **pointer** into the engine/KG
(a path, an endpoint URL, a node property, a comma-joined output set). An outsider cannot re-check a
pointer; they must **trust the engine**. `c1verify` deletes that trust: each gate is reduced to a
**total, fail-closed pure function over the bytes of a self-contained, content-sealed bundle**.
Anything not fully re-derivable is **REJECT** — never "trust".

## Trust base
`sha256` + a re-implemented RFC-8032 `Ed25519` (stdlib only) — and, for *temporal* gates only, an
independent k-of-N witness quorum whose keys the verifier holds **out-of-band** (never from the
bundle). The issuer is treated as the adversary (full KG-write, whole-bundle, arbitrary-timestamp
control). On a solo box with no independent witnesses, temporal gates are **UNSUPPORTED and REJECT**
by design — they never degrade to trust.

## Engine-independence (proven three ways)
- **import-linter** forbidden contract: `c1verify` may import neither `lakatos` nor `server`.
- **clean-venv CI**: the suite runs in a fresh venv where the engine is not installed — an accidental
  engine import is an `ImportError`, not a green test.
- **subprocess guard**: after `verify()`, zero `lakatos`/`server` keys appear in `sys.modules`.

Copy-fidelity of the re-implemented pure functions (JCS, `judge()`, `grounded_extension`,
`receipt_content_sha`, Ed25519) to the engine is pinned by a golden cross-check that runs **only in
the engine repo's CI**, where both are importable — it never ships inside this package.

## Status
**S0 (skeleton)** — this slice ships the fail-closed spine only: a strict typed JCS parser that
DEFAULTS to REJECT (empty ACCEPT set) with **zero gate logic**. `verify(bytes)` is total and always
returns `certified=false`. Gate reverifiers land slice by slice (S1..S9); until then each gate is
`REJECT / not implemented`. See `LakatosTree_C1ExternalVerifier_20260708` for the programme.

```python
import c1verify
report = c1verify.verify(bundle_bytes)
# {'per_gate': [...], 'certified': False, 'missing': [...all gates...], 'residuals': []}
```
