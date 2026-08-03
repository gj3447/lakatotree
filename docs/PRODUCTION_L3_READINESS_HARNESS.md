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

Operator-supplied `mode=live` cases remain permanently fail-closed at this milestone.
The separate live collector described below may observe a deployment, but it cannot
construct an approval verdict or bypass the pure evaluator's `UNSUPPORTED` boundary.

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

## Read-only live collection

`lakatotree-readiness-collect` is a separate evidence producer. It binds an exact
request file to a caller-supplied SHA-256, performs one bounded pass over the named
read-only sources, and creates a canonical `0600` output file with exclusive-create
semantics. The output parent must be owned by the collector user and must not be
group/other writable. The final inode and bytes are reread after durable directory
publication. It never overwrites evidence and has no `--evaluate`, `--approve`, or
pretty-print mode.

The five source slots are deliberately explicit:

- runtime uses only four unauthenticated GETs through a credential-free loopback HTTP
  origin. A minimal socket parser bypasses proxy and redirect machinery, requires
  exact `Content-Length` framing, bounds headers and body, and applies one absolute
  end-to-end deadline across all four reads. It emits only allowlisted fields plus
  body and endpoint digests. It never reads or sends a bearer token; a protected
  endpoint therefore remains unavailable until a server-authenticated nonce challenge
  or equivalent transport exists;
- PostgreSQL reads only `LAKATOTREE_READINESS_PG_DSN`. The value must contain exactly
  `host`, literal `hostaddr`, `port`, `dbname`, `user`, `password`,
  `sslmode=verify-full`, and `sslrootcert=system`; `host` is the certificate name and
  `hostaddr` pins the network endpoint. The collector passes explicit connection
  parameters, requires channel binding, disables ambient client-certificate fields,
  and sets read-only startup/session controls. If any process-global `PG*` variable is
  present it fails closed, and the exact DSN excludes service, `.pgpass`, or client-key
  authority. One bounded read-only transaction uses
  static catalog queries and hashed principals. It projects
  database/schema/relation/sequence/column ACL entries, recursive effective role
  membership, column-only privileges, object owners, and stable database identity
  without committing;
- Neo4j uses READ access and a fixed `CALL`/`SHOW` query allowlist. It records edition,
  version, role hashes, a hashed actor, stable database identity, and an
  effective-privilege projection digest. It reads only the fixed
  `LAKATOTREE_READINESS_NEO4J_URI`, `..._USER`, and `..._PASSWORD` names and requires
  one credential-free, literal-IP `bolt+s` endpoint with system-root server
  verification. Plaintext, locally trusted, routing, DNS, and multi-endpoint URIs are
  rejected. A Community deployment or unavailable privilege readback remains
  observable but cannot satisfy the production contract;
- predeploy binds one absolute, regular, non-symlink receipt to its raw-file digest
  and emits only receipt hashes and structural booleans, never its signature;
- temporal binds the policy, sidecar, and runtime-binding files separately and emits
  only their digests, schemas, anchor counts, and receipt bindings, never DIDs or
  signatures.

Every slot is required for `COLLECTION_COMPLETE`; a `null` slot is reported as
`NOT_CONFIGURED`, not silently skipped. A detected predeploy/PG/Neo target mismatch
also forces `COLLECTION_INCOMPLETE`. `COLLECTION_COMPLETE` says only that all five
sequential observations were obtained and no such mismatch was observed. It does not
say their values are safe. Every bundle explicitly carries
`verification_status=UNVERIFIED` and `snapshot_coherence=UNATTESTED`.
`cross_source_binding` is `UNVERIFIED`, `MATCHED_SEQUENTIAL`, or `MISMATCH`; even a
match is not a coherent or signed snapshot. `COLLECTION_INCOMPLETE` likewise records
an evidence gap, not a repair authorization. Neither status can emit
`production_ready`, `HARNESS_GREEN`, a deployment status, or L3 assurance.

The request schema is exact: unknown fields, operator-selected environment-variable
names, non-absolute artifact paths, and non-lowercase SHA-256 values are rejected.
The v1 shape below remains an unsigned shadow-collection compatibility surface. It
cannot enter the signed access gate. A complete v1 shape is:

```json
{
  "schema_version": "lakatotree-production-readiness-collection-request/v1",
  "target_id": "production-ct301",
  "timeout_seconds": 10,
  "adapters": {
    "runtime": {
      "base_url": "http://127.0.0.1:55170",
      "expected_git_sha": "0123456789abcdef0123456789abcdef01234567"
    },
    "postgresql": {
      "database": "lakatos",
      "owner_role": "lakatos_owner",
      "migrator_role": "lakatos_migrator",
      "runtime_role": "lakatos_runtime"
    },
    "neo4j": {"database": "neo4j"},
    "predeploy": {
      "path": "/absolute/evidence/predeploy.json",
      "file_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    },
    "temporal": {
      "authority_policy": {
        "path": "/absolute/evidence/policy.json",
        "file_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
      },
      "sidecar": {
        "path": "/absolute/evidence/sidecar.json",
        "file_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      },
      "runtime_binding": {
        "path": "/absolute/evidence/runtime-binding.json",
        "file_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
      }
    }
  }
}
```

Request v2 adds `audit_role` to PostgreSQL and adds `audit_user`, `audit_role`,
`migrator_role`, and `runtime_role` to Neo4j. All declared roles are pairwise
distinct, Neo4j roles must be custom rather than built-in, and the runtime source
identity must be a full 40-hex Git commit. The v2 adapters derive whether the actual
session actor is the dedicated audit principal and whether that principal has any
effective write/create/admin authority. An observation that says the principal is
not read-only may still be recorded by the shadow collector, but the signed producer
refuses to sign it.

Configured database adapters take authority only from these fixed names:

```text
LAKATOTREE_READINESS_PG_DSN
LAKATOTREE_READINESS_NEO4J_URI
LAKATOTREE_READINESS_NEO4J_USER
LAKATOTREE_READINESS_NEO4J_PASSWORD
```

Example invocation:

```bash
request=/absolute/path/to/readiness-collection-request.json
output=/absolute/new/path/readiness-live-evidence.json
lakatotree-readiness-collect \
  --request "$request" \
  --request-sha256 '<independently pre-recorded request SHA-256>' \
  --output "$output"
```

Collector exit codes are `0` for `COLLECTION_COMPLETE`, `1` for a successfully
written `COLLECTION_INCOMPLETE` bundle, `2` for invalid input or an unsafe output
target, and `3` when a final path may exist but durable exact publication is in
doubt. Adapter exceptions are normalized to stable failure codes; driver messages,
DSNs, URLs, credentials, tokens, signatures, and database principals are not echoed.
The base wheel can run `--help`, runtime GETs, and pinned-file adapters without third
party packages. PostgreSQL and Neo4j collection load the pinned `readiness-live`
extra lazily.

## Signed storage-access boundary

`lakatotree-storage-audit` is a separate one-shot L_MC evidence producer. Its exact
request and signed evidence schemas are v2. It consumes
an independently SHA-pinned `lakatotree-storage-access-policy/v1`, a structurally
self-digested pinned v5 predeploy receipt, an exact current artifact/operation
identity (clean Git commit or verified wheel RECORD), and strict
audit-principal connections. The policy declares four distinct PostgreSQL roles,
three distinct Neo4j users/custom roles, the intended PostgreSQL SET-only
migrator-to-NOLOGIN-owner membership, and different Ed25519 attestors for the two
datastores. The producer verifies the dedicated audit actors are read-only; the signed
full projections remain evidence for a later independent least-privilege review of
owner, migrator, and runtime roles.

For each phase (`predeploy` or `startup`) it performs this exact sequence:

```text
PG before -> Neo4j before -> pinned receipt/previous-phase readback
          -> PG after  -> Neo4j after
          -> four domain-separated signatures under two distinct datastore keys
          -> read-only bundle
```

The pure verifier checks strict Ed25519 keys/signatures, audit-actor and policy projections,
target/current-artifact/operation/receipt/policy bindings, bounded validity windows,
distinct store signers, exact before/after equality, and the producer's exact
cross-store observation order. Neo4j authorization projections are additionally
bracketed by the `system` writer's database identity and `lastCommittedTxn`; any
committed system/security change during that scan makes the observation partial.
Drift is derived from signed observations; the schema has no trusted `drift_free`
boolean. A startup bundle also
binds the raw SHA-256 of the predeploy bundle, uses a different nonce, and must retain
the same signed PG/Neo projections. Its only positive typed result is
`ACCESS_PAIR_VERIFIED`, while `production_ready=false` and
`deployment_status=NOT_READY` remain fixed.

The bracket is not a claim that PostgreSQL and Neo4j form one atomic database
snapshot. It only prevents disjoint datastore intervals and detects committed Neo4j
system-database changes during its multi-query authorization projection. A
change-and-revert outside those brackets is not disproved. The verifier is stateless:
it rejects reuse of the predeploy nonce as the startup nonce, but an identical valid
pair may be reevaluated until its signed expiry.

The signing seeds are raw 32-byte owner-controlled non-symlink files with mode 0400
or 0600 and are passed only to the one-shot audit process. Runtime launchers reject
all PG/Neo migration and readiness-audit DSN, URI, user, and password variables. The
PG migration profile
itself is single-target `verify-full` TLS, pinned `hostaddr`, SCRAM-only, required
channel binding, and `read-write`; Neo migration accepts only system-trusted
`bolt+s`/`neo4j+s`. These code constraints do not provision accounts or certificates.

### Privileged PostgreSQL preparation

The application migration cannot harden bootstrap-owned `pg_catalog` routines. Before
the signed audit, an operator must run the packaged
`server/storage_provisioning/postgresql_large_object_acl_v1.sql` in a new, dedicated,
direct bootstrap-superuser session connected to the exact LakatoTree database:

```bash
psql -X --set=ON_ERROR_STOP=1 \
  --dbname lakatos \
  --file /absolute/path/postgresql_large_object_acl_v1.sql
```

Keep the DBA secret out of the command line, repository, runtime environment, and
receipt; use an operator-controlled protected authentication mechanism. The resource
supports only PostgreSQL 16/17, binds the complete built-in large-object routine
inventory before mutation, revokes only `PUBLIC EXECUTE`, checks a zero postcondition,
and is idempotent. It is database-local, so run it for every exact target database and
rerun its verification after restore, initdb, or a major upgrade. A managed service
that cannot provide the required direct superuser authority remains `NOT_READY`.

This resource does not create roles, databases, schemas, certificates, application
objects, or positive grants. Provision the NOLOGIN owner, SET-only migrator,
runtime/audit logins, database/schema ownership, migration, and exact runtime grants
as separate operator steps. Revoke unrelated `PUBLIC` database/schema grants before
collecting evidence.

### Neo4j strict authorization preparation

The strict path accepts one concrete canonical application database and only the
explicitly audited Neo4j 2026.03 through 2026.06 Enterprise semantics. Remove the
built-in `PUBLIC` grants first. Runtime and migrator custom roles receive `ACCESS` only
on the application database; the audit custom role requires `ACCESS` on both the
application database and `system`, plus only the exact SHOW/procedure permissions used
by the collector. Every accepted grant must be mutable. Undeclared active privileged
or break-glass roles make the audit fail, so the audited DBMS must be dedicated or
those principals must be inactive during collection.

Current Neo4j Enterprise vocabulary and provisioning remain a live-evidence gate. The
repository's older Community integration container cannot prove this exact role shape,
and no license acceptance or production provisioning is performed automatically.

Example producer invocation:

```bash
lakatotree-storage-audit \
  --request /absolute/storage-audit-request.json \
  --request-sha256 '<independently recorded raw request SHA-256>' \
  --postgresql-signing-key /absolute/private/pg-audit-seed.raw \
  --neo4j-signing-key /absolute/private/neo-audit-seed.raw \
  --output /absolute/new/storage-audit-bundle.json
```

A valid bundle proves only signed, bounded, stable projections collected through
read-only audit actors. It does not prove the non-audit roles already satisfy their
declared least-privilege policy, that no change-and-revert happened between
observations, that the current runtime writer lease is valid, or that a deployment is
approved.

## Signed runtime-writer boundary

Gate 2 now has a code-complete, fail-closed runtime admission surface. The
application creates a fresh nonce and challenges a separately pinned executable;
that external L_MC authority must independently read back the current boot,
singleton worker, exact Git or wheel-RECORD artifact, storage operation and target,
the signed access/predeploy evidence digests, and the current PostgreSQL/Neo4j writer
lease. Its domain-separated Ed25519 response is cached as immutable bytes and is
valid only for `critique-history-ledger/v1`. It is not an assertion about generic
tree writes, MongoDB, lineage delivery, or other external effects.

The historical migration-drain lease and current runtime-writer lease are distinct
bindings and may not share an identifier. A ledger operation captures the exact
boot, snapshot body, local storage generation, lease token digest, and lease
generation, PostgreSQL backend PID, and advisory-key pair; the final commit guard
checks the complete lease projection again. PostgreSQL ledger writes run
on the same backend session that owns the advisory election lock, so session loss
also destroys the transaction before a successor can publish authority. Neo4j
touches the exact lease node inside its managed transaction, preserving datastore
serialization across takeover.

`GET /api/ops/runtime-authority-snapshot` returns only the exact still-current
cached signed envelope. It never refreshes authority or acquires a lease and returns
503 after expiry, invalidation, boot drift, or lease drift. Collection request v3
adds this fifth read-only GET and independently verifies the signature and the exact
Git/wheel artifact pin. It emits only redacted digests and remains
`verification_status=UNVERIFIED`, `snapshot_coherence=UNATTESTED`; collection is not
deployment approval. Request v1/v2 behavior and their four-GET runtime adapter remain
compatible. The standalone `lakatotree-runtime-authority-verify` command performs
the same public-proof verification over caller-pinned files and likewise reports
`production_ready=false`.

Runtime authority uses a separate public key from the historical drain/fence key.
The server owns neither private key. If the runtime signer, exact pins, live
Enterprise authorization evidence, or signed access pair is absent, the ledger and
`/readyz` remain `NOT_READY`. Snapshot renewal is an explicit operator action; the
read-only collector cannot extend it. This is deliberately a short, at-most-five-minute
operating window rather than a continuous-renewal protocol: a long-lived process
fails closed at expiry until the authenticated contract-refresh operation obtains a
new external snapshot. The signer adapter caps stdout and stderr independently as
well as wall time, so rejection happens before oversized output can enter the JSON
verifier. The published envelope includes only a token digest plus lease PID/key
metadata; those values are accepted as non-secret collection metadata, while the raw
owner token and all private signing material remain unavailable. The locked
`ooptdd_receipts/RUNTIME_AUTHORITY_SNAPSHOT/` harness exercises exact binding,
redaction, lease replay, expiry, full source identity, and same-session commit
negative controls.

## Signed temporal-component boundary

The temporal track models a non-circular two-phase route:

```text
prediction receipt --external k-of-N T1 signatures--+
                                                     +--> immutable sidecar
verdict receipt    --external k-of-N T2 signatures--+
```

Gate 3 now persists an immutable prediction commitment before the verdict, seals its
SHA in the V7 verdict receipt, stores the T2 sidecar after the verdict, and reverifies
the exact genesis-to-current-verdict prefix on every permanent tree, standing, and
receipt read. Stored booleans are never authority inputs. A head race is unknown, an
invalid temporal adjunct leaves a valid receipt chain at L2, and only actual receipt
chain corruption produces L0.

Gate 4 adds a standalone stdlib-only `c1verify` artifact and bounded CLI. The server
copies the exact SHA-pinned import closure into a private directory and runs it under
the separately pinned Python interpreter with `-I -S -B`; `lakatos`, `server`,
site-packages, `sitecustomize`, and bytecode side effects are absent. C1 independently
rederives the policy, sidecar, every V7/prediction receipt, the exact graph prefix,
both canonical Ed25519 quorum endpoints, strict T1-before-T2 ordering, prediction
commitment, causal seal, request identity, and a separately signed time-observation
attestation. Its freshness decision uses the C1 process clock, never a caller-supplied
evaluation time. Multiple nodes share one bounded authority call and one C1 call.

Only an exact current-head C1 success may set `l3_eligible=true`, and that result
retains the complete C1 input digest, verifier identity, authority-role identity
hashes, and signed validity bound. L3 remains per proof; it is not a tree-wide,
service-wide, or deployment claim. Process separation and pins do not by themselves
prove organizational independence. The production time authority must be operated
outside the application trust domain (for example a protected service or HSM-backed
adapter); the deterministic executable and embedded key used by tests are synthetic
mechanism evidence only. The locked
`ooptdd_receipts/C1_TWO_ENDED_TEMPORAL/` nest preserves this claim ceiling.

## External production-approval boundary

Gate 5 is a separate offline surface. `build_live_review()` accepts only verified
storage-access, current runtime-authority, and exact per-proof Gate 4 objects. It
cross-binds target, operation, artifact, predeploy receipt, startup bundle, runtime
lease/boot digests, C1 input and every temporal receipt digest, then derives the
intersection of their validity windows. The resulting canonical review contains no
trusted `production_ready` input and remains `NOT_READY` without another authority.

`lakatotree-production-approval-verify` verifies an out-of-band pinned approval
policy and a separately administered Ed25519 receipt over that exact review. The
approver must be distinct from all hashed datastore, runtime, producer, attestor,
witness, and time-authority identities. A valid result is
`APPROVAL_RECEIPT_VERIFIED` with `deployment_status=APPROVED_NOT_APPLIED` and
`approval_applied=false`. The command has no signer, datastore, network, deploy,
restart, refresh, or mutation path and is deliberately not wired into `/readyz`.
`CASE_ACCEPTED`, `HARNESS_GREEN`, `COLLECTION_COMPLETE`, and
`ACCESS_PAIR_VERIFIED` are not approval shortcuts. The locked
`ooptdd_receipts/PRODUCTION_APPROVAL_VERIFICATION/` nest uses fixture keys only and
therefore cannot serve as the missing production receipt.

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

1. **Code surface installed; live evidence still blocked.** The v2 dedicated-audit
   projection, strict migration profiles, separately signed PG/Neo before/after
   attestations, and predeploy/startup phase-pair verifier are implemented. Production
   remains `NOT_READY` until real CA-verified PG audit roles and Neo4j Enterprise custom
   roles exist and produce the two pinned bundles.
2. **Code surface installed; live authority still blocked.** The boot-bound signed
   runtime snapshot, Git/wheel artifact union, current-lease generation binding,
   cached readback, v3 shadow collection, and same-PG-session commit fence are
   implemented. Production remains `NOT_READY` until an independently operated
   signer produces current evidence for the real target.
3. **Code surface installed; live authority still blocked.** Immutable T1/V7/T2
   storage, permanent read-time proof objects, the independent C1 process, process-local
   concurrency bound, and synthetic two-process OOPTDD harness are implemented.
   Production remains `NOT_READY` until the pins identify a genuinely separately
   administered time-observation authority and current real evidence.
4. **Code surface installed; external verdict absent.** The typed live review and
   verifier-only external approval receipt CLI are implemented without `/readyz` or
   deployment wiring. No real approval policy/receipt has been supplied, so the only
   current production verdict is `NOT_READY`.
5. A later, separately authorized deployment executor may consume a still-current
   verified approval receipt with replay-safe application semantics. This repository
   does not implement or infer that authorization.
