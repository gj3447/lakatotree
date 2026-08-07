# LakatoTree functional-core migration

Status: active, milestone 1 implemented on 2026-08-07.

## Outcome

LakatoTree will converge on a **functional core / imperative shell** architecture. This does not
mean replacing every class with a free function. Frozen dataclasses, Pydantic schemas, typed
exceptions, capability protocols, repositories, and effect adapters remain objects where identity
or lifecycle matters. Domain decisions become pure functions over immutable snapshots; clocks,
environment, filesystems, databases, subprocesses, HTTP, and history projection stay in thin
shells.

The machine-readable engine boundary is
[`LAKATOTREE_FUNCTIONAL_ENGINE_SPEC_20260807.json`](LAKATOTREE_FUNCTIONAL_ENGINE_SPEC_20260807.json).
The bounded migration process is
[`LAKATOTREE_FUNCTIONAL_MIGRATION_LOOP_20260807.json`](LAKATOTREE_FUNCTIONAL_MIGRATION_LOOP_20260807.json).

## Compatibility freeze

Every extraction must preserve these surfaces unless a separate versioned migration is approved:

| Surface | Frozen property |
|---|---|
| Python/API/MCP/CLI | Public imports, method signatures, request and response shapes |
| Durable ledger | Labels, properties, statement ordering, expected-head and writer fences |
| Receipts and replay | Canonical bytes, hash domains, version dispatch, causal identities |
| History | Event operation, payload, ordering, pending/recovery behavior |
| Failures | HTTP and typed-error taxonomy, dry-run behavior, CAS-conflict semantics |
| Ordering | Existing query, candidate, transaction, and effect order where observable |

A facade may preserve a public surface while internals move. Copying a durable DTO or hash
algorithm into the facade is forbidden; it must re-export or delegate to the one authority.

## Target seam

```text
captured immutable observation + command
                 |
                 v
       pure decide / plan / evolve
                 |
        events or effect requests
                 |
                 v
 writer-fenced transaction / outbox / adapter
                 |
                 v
        receipt + exact readback
```

The core cannot discover time or configuration. A named value such as a schema version, receipt
domain, event kind, or durable filename is allowed only when it is a documented protocol identity.
Deployment paths, limits, credentials, clocks, executors, and policy choices must be injected or
loaded by the shell.

## Migration sequence

1. **Freeze contracts.** Keep characterization tests, public import checks, receipt goldens,
   dependency rules, and recovery tests green.
2. **Extract one vertical slice.** Select one command and split captured input, pure decision plan,
   existing transaction interpreter, and recovery path.
3. **Prove the seam.** Add RED-first defect and mechanism guards plus a hermetic OOPTDD receipt whose
   negative oracle proves the injected plan is load-bearing.
4. **Repeat at high-coupling boundaries.** Next targets are the fresh `submit_test_result` commit
   construction tail, storage/readiness evaluators, local-build lifecycle decisions, and backtest
   calculations.
5. **Thin adapters.** API, CLI, MCP, composition, filesystem, database, and subprocess modules retain
   authorization and effects but stop deciding domain outcomes.
6. **Enforce dependency direction.** Every new pure module receives an import-linter contract; no
   effect-layer exceptions are added to make a test pass.
7. **Retire only after evidence.** Compatibility paths are deprecated only after every consumer and
   replay corpus has moved; durable bytes are never silently rewritten.

## Milestone 1: stale-CANONICAL sweep

`lakatos.stale_canonical` now owns three deterministic stages:

- canonical-head snapshots plus effective floor become an ordered, frozen sweep decision;
- the decision becomes an immutable, validated demotion draft before any recovery effect runs;
- that draft plus one captured timestamp and engine identity becomes immutable receipt-bound plans.

`JudgementService.demote_stale_canonical` remains the compatibility interpreter. It still discovers
the effective floor, checks live readiness, queries heads, projects all pending administrative
predecessors before capturing one timestamp, executes one guarded CAS per candidate, and emits
history only after a successful commit. Dry run never reaches a live-only capability.

The floor and clock are injectable shell capabilities, and the captured floor is frozen before it
crosses a policy port. Alternate decision or effect planners may only suppress an ordered subset of
the canonical plan; they fail closed if they invent, unlock, reorder, or forge work. Effect drafts
are validated before predecessor recovery, so an empty or invalid planner cannot touch recovery,
clock, ledger, or history ports. For selected drafts, predecessor projection still completes before
the one timestamp is captured and receipts are sealed. The transaction rechecks both the receipt
head and the operator-lock value, and the verdict, source, node state, receipt identity, and expected
heads come from one immutable versioned plan rather than duplicated mutation literals.

This slice does not claim to close the pre-existing crash window between the Neo4j commit and its
history projection. A later outbox/recovery slice must version that behavior instead of hiding it
inside this compatibility-preserving extraction.

The planner is deliberately a module, not another engine. Its fit decision is recorded in
[`STALE_CANONICAL_PLANNER_MODULE_DECISION_20260807.json`](STALE_CANONICAL_PLANNER_MODULE_DECISION_20260807.json).

## Per-slice acceptance gate

- The preregistered guard fails for the intended reason before production code exists.
- Equal closed inputs produce equal frozen decisions without input mutation.
- An injected tripwire or alternate plan changes the real shell path, proving no bypass.
- Applicable CAS, crash/recovery, history, and wire cut points retain their prior behavior; any
  uncovered pre-existing cut point is recorded as an explicit frontier rather than called solved.
- Focused tests, all OOPTDD receipts, import-linter, compile checks, full pytest, and Longinus pass.
- Only the declared write set is committed, pushed, and exact-read back.

The next slice is the receipt and causal-outbox construction tail of
`JudgementService.submit_test_result`. Its existing monolithic guarded Cypher remains intact during
the first extraction; only the deterministic construction before it moves into a pure planner.
`effective_floor()` remains shell-side filesystem/environment I/O and enters that planner only as a
frozen captured value. The planner must emit both question-open and question-closed Eureka/outbox
variants; the guarded transaction selects the applicable preplanned variant from its authoritative
`question_closed` readback rather than rebuilding policy inside Cypher or the adapter.
