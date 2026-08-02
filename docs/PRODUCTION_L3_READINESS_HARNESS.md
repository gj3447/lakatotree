# Production + L3 readiness harness

This first harness milestone is executable and deliberately credential-free. It
checks whether one exact evidence case is internally consistent and whether a
locked source-checkout suite rejects the known storage-authority and signed-time
false positives. It does **not** deploy a server, drain a writer, inspect production
credentials, alter a database, or enable VAL L3.

## Claim boundary

There are two deliberately different success states:

- `CASE_ACCEPTED` means only that one exact in-memory case passed the pure checks.
  `evidence_bytes_bound=true` records only that the raw bytes match the reported
  SHA-256; the installed CLI additionally enforces a strict input path.
- `HARNESS_GREEN` is emitted only by the source-checkout OOPTDD suite after the
  frozen fixture, its expected report digest, and every manifest-declared negative
  control have run successfully.

Neither status is production approval. Every accepted case still contains:

```json
{
  "status": "CASE_ACCEPTED",
  "harness_status": "NOT_RUN",
  "deployment_status": "NOT_READY",
  "production_ready": false,
  "l3_assurance": "UNAVAILABLE",
  "mutation_attempts": 0
}
```

`mode=live` returns `UNSUPPORTED` until independent live adapters are implemented
and audited.

## Harness topology

```text
independently SHA-pinned JSON case
        |
        v
INFORM  bind file / case / operation / target / receipt / policy / sidecar
        |
        v
CONSTRAIN  no env, network, wall clock, subprocess, or mutation authority
        |
        +-------------------------------+
        |                               |
        v                               v
VERIFY storage                    VERIFY temporal component
  predeploy projection              policy-bound T1 receipt quorum
  signed writer fence               policy-bound T2 verdict quorum
  PostgreSQL role split             strict Ed25519 identities/signatures
  Neo4j Enterprise roles            same signer set at both endpoints
  single-worker runtime             max(all T1) < min(all T2)
        |                               |
        +---------------+---------------+
                        v
              CASE_ACCEPTED | NOT_READY
                        |
                        v
CORRECT  deterministic plan only; never executes production changes

frozen case + all declared attacks + unsupported-live control
                        |
                        v
             OOPTDD HARNESS_GREEN | HARNESS_RED
```

The harness is an L_IDE control surface over an L_RT server and an L_MC deployment
boundary. Inform, Constrain, Verify, and Correct are the four evidence axes, not
separate harness-family tiers.

## Storage case contract

The storage track requires all of the following together:

- the exact `server.storage_predeploy.verify_predeploy_receipt` result projection,
  bound to the expected contract, environment, operation, target, and independently
  pinned raw receipt-file SHA;
- a raw writer-fence response whose Ed25519 signature, authority-key pin, nonce,
  lease, drain-receipt identity, target, operation, evidence references, and bounded
  validity window are reverified, including the production verifier's maximum age
  and minimum expiry margin;
- zero listener, replica, writer, and nonce-reuse counts as explicit unsigned case
  projections. They are useful negative controls here but are not production facts
  until a live adapter derives them from the signed drain receipt and lease store;
- a PostgreSQL `NOLOGIN` owner, separate migrator and runtime actors, exact object
  ownership and coverage, safe owner/migrator/runtime role attributes, minimal runtime
  table/sequence/schema privileges, no `PUBLIC` grants or role memberships, and no
  runtime ownership or DDL. The successful target-bound predeploy projection establishes
  that the named migrator could perform this migration; its full DDL grant surface still
  belongs to the future live inspector;
- Neo4j Enterprise custom roles with separate migrator/runtime principals, exact
  database-scoped effective privilege projections, and no built-in admin or public
  role binding;
- one runtime worker, current storage authority, the exact signed writer-lease ID,
  no migration
  credential, zero pending/conflict state, and idempotent reconcile readback;
- the same target, operation, and predeploy-file identities on every projection.

These are frozen-case assertions today. A live inspector must derive them from
database-native actor, owner, ACL, edition, role, privilege, lease, and readiness
readbacks rather than accept operator-supplied projections.

## Signed temporal-component boundary

The temporal track models a non-circular two-phase route:

```text
prediction receipt --external k-of-N T1 signatures--+
                                                     +--> immutable sidecar
verdict receipt    --external k-of-N T2 signatures--+
```

The evaluator recomputes the authority-policy digest and sidecar digest, validates
every DID as a canonical non-identity prime-subgroup Ed25519 key, and reverifies each
signature over the exact receipt SHA. Both engine and independent verifier use the
LakatoTree strict profile, including non-identity prime-subgroup `A` and `R`; this is
intentionally narrower than general RFC 8032 interoperability. Producer, attestor, and witness roles must be
disjoint. The two endpoints must use the same signer set, both must meet the policy
threshold, and every accepted T1 must precede every accepted T2. The runtime binding
must point to the same current prediction receipt, verdict receipt, receipt graph,
and sidecar.

This proves only the pure temporal component. It does not rederive the verdict,
prove that distinct keys belong to distinct organizations, establish a trusted
wall-clock source, or wire the sidecar into permanent submit/read paths. Runtime
VAL therefore remains `UNAVAILABLE`.

## Run one case

The base wheel includes the stdlib-only evaluator. It accepts an absolute regular
JSON path plus a caller-supplied raw-file hash:

```bash
evidence=/absolute/path/to/evidence.json
lakatotree-readiness-harness \
  --evidence "$evidence" \
  --evidence-sha256 "$(shasum -a 256 "$evidence" | awk '{print $1}')" \
  --pretty
```

The command above is a local byte-consistency check because it derives the digest
from the same file immediately before evaluation. For an authority-bearing workflow,
obtain the expected digest from a separately administered, pre-recorded channel and
pass that fixed value instead. Neither form is production approval.

Case exit codes are `0` for `CASE_ACCEPTED`, `1` for a well-formed `NOT_READY`
case, and `2` for `UNSUPPORTED` or invalid/ambiguous input. The report separates
`evidence_bytes_bound`, `evidence_file_sha256`, `canonical_case_sha256`, and the unsigned
`report_body_sha256`; the last field is an integrity digest, not an authority seal.
Accepted and `NOT_READY` reports do not echo signatures, DIDs, public keys, or
database principals. Invalid-input diagnostics also redact unknown and duplicate
key names. Evidence bytes, JSON nesting, generic lists, and temporal-anchor
collections have hard size/depth/cardinality bounds before expensive verification.

## Run the locked suite

The machine-readable manifest, requirements, adapter, and frozen fixture are
source-checkout artifacts under `ooptdd_receipts/PRODUCTION_L3_READINESS/`; they are
not packaged as a live deployment contract in the wheel. Run the auto-discovered
suite with:

```bash
python ooptdd_receipts/run_all.py
```

The manifest pins the raw fixture SHA, canonical case SHA, expected case-report
digest, requirement IDs, exact emitted events, and the exact ordered control IDs.
The suite records a control ID only after that attack is rejected and requires the
executed list to equal the manifest. Each negative evaluator result must also retain
the exact bounded `NOT_READY`/`UNSUPPORTED` claim shape, a valid report-body digest,
zero mutation attempts, and an unchanged input case. Missing or drifted fixture bytes
or controls make the suite red; it never regenerates evidence implicitly.

## Next implementation gates

1. Implement database-native PostgreSQL actor/owner/ACL and Neo4j Enterprise
   role/privilege inspectors, then bind them into predeploy and startup readbacks.
2. Implement an immutable verdict-receipt T2 sidecar store and reverify it on every
   permanent read surface; replace the current internal boolean seam with a proof
   object.
3. Add an engine-independent two-ended verifier and a disposable real-datastore,
   independently administered time-authority harness.
4. Only then implement live mode and allow separately signed deployment evidence to
   produce a production-approval receipt.
