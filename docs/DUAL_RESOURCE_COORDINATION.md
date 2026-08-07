# Dual-resource coordination (v1)

- Status: **executable kernel, durable single-host journal, and operation-specific
  workload-dispatch authority; live metering and harness wiring not yet implemented**
- Schema: `lakatotree.resource/v1`
- Code: `lakatos/resource_coordination.py`, `lakatos/resource_kernel.py`,
  `lakatos/resource_execution.py`, `lakatos/io/resource_execution.py`,
  `lakatos/io/_resource_journal_contracts.py`,
  `lakatos/io/_resource_journal_codec.py`, `lakatos/io/_resource_anchor.py`,
  `lakatos/io/resource_journal.py`

## Why this is separate from `cycle_budget`

LakatoTree already has a `cycle_budget`, but that value caps *scientific judgements*
by counting scored nodes. It does not measure a process, GPU, wall clock, model call,
or token. Reusing that name or counter for execution cost would silently change its
meaning and let concurrent work consume resources before a verdict exists.

The v1 resource engine therefore gates costly effects independently:

```text
scientific gate: cycle_budget allows another scored judgement
resource gate:   a ResourceGrant covers the work's compute and token upper bounds

execution is eligible only when every applicable gate passes
```

A resource refusal is an operational result, never a Lakatosian verdict. Conversely,
a progressive result does not refund or enlarge a resource budget.

## Research basis and design consequence

- Multi-resource allocation cannot be made honest by adding unlike units. Dominant
  Resource Fairness compares each demand as a share of its own capacity and uses the
  largest share; its assumptions and fairness layer are distinct from hard-cap
  admission. LakatoTree v1 implements only componentwise feasibility, leaving fair
  queueing as a later policy. See [Ghodsi et al., NSDI 2011](https://www.usenix.org/legacy/events/nsdi11/tech/full_papers/Ghodsi.pdf).
- Kubernetes likewise separates requests/limits and quota admission across resource
  types. Quota is not by itself a fair scheduler. See the official
  [resource-management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
  and [ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
  documentation.
- Provider token accounting has nested categories: cached input is part of total
  input, and reasoning output is part of total output. The v1 cap therefore uses only
  total input and total output, avoiding double charging. Raw provider detail belongs
  in evidence for a later schema. See the
  [OpenTelemetry GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md).
- Test-time compute should be allocated adaptively rather than assumed to improve all
  tasks uniformly. That is a later routing policy over already-admissible work, not a
  reason to weaken a hard limit. See
  [Snell et al. (2024)](https://arxiv.org/abs/2408.03314).
- Runtime enforcement remains an adapter responsibility. Linux cgroup v2 supplies
  CPU and memory controllers, while wall deadlines and provider token ceilings need
  their own mechanisms. See the
  [Linux kernel cgroup v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
- The durable adapter uses a local SQLite rollback journal with `BEGIN IMMEDIATE`,
  `synchronous=FULL`, uniqueness, and revision/hash compare-and-swap. SQLite permits
  concurrent readers but only one writer at a time; its documented commit protocol
  makes a transaction appear all-or-nothing under its stated filesystem assumptions.
  See the official [transaction](https://sqlite.org/lang_transaction.html),
  [atomic commit](https://sqlite.org/atomiccommit.html), and
  [uniqueness/upsert](https://sqlite.org/lang_upsert.html) documentation.

## v1 boundary

### Functional architecture and extension seams

The resource slice is a functional core inside an imperative shell:

```text
immutable values + decide/evolve       lakatos/resource_coordination.py
                ↓ packaged as
injected ResourceKernel port           lakatos/resource_kernel.py
                ↓ consumed by
SQLite transaction/replay repository   lakatos/io/resource_journal.py
                ↙             ↘
pure canonical codec          TrustedAnchorStore protocol
_resource_journal_codec.py    + _resource_anchor.py adapter
                ↘             ↙
immutable shared contracts and version identities
_resource_journal_contracts.py

confirmed state + StartGrant intent      lakatos/resource_execution.py
                ↓ fresh-head revalidation through injected ports
operation-specific dispatch shell        lakatos/io/resource_execution.py
```

Existing consumers keep importing from `lakatos.io.resource_journal`; it is the
compatibility facade and re-exports the exact contract and anchor objects rather than
copies. For AI-assisted changes, use these bounded seams:

- change admission or lifecycle semantics only through pure `decide`/`evolve` and
  immutable commands/events, then prove equal inputs yield equal outputs;
- inject a `ResourceKernel` in shell tests instead of patching globals;
- add a trusted-anchor implementation against `TrustedAnchorStore`, without teaching
  SQLite or the pure kernel about its filesystem/network details;
- treat codec, schema, hash-domain, and rule-identity changes as explicit version
  migrations; the v1 decoder remains closed and fail-fast;
- never import `lakatos.io` or `server` from either functional-core module.
  `.importlinter`
  makes that direction machine-enforced.

The private filenames are internal ownership boundaries, not new public import
promises. Their canonical bytes and the public facade identities are nevertheless
frozen by RED-first regression tests and an isolated-mutant OOPTDD receipt.

The pure kernel owns:

- versioned `ResourceBudget`, `ResourceEstimate`, `ResourceGrant`, `ResourceUsage`,
  and `ResourceReceipt` envelopes over a closed nonnegative `ResourceVector`;
- componentwise, all-or-nothing reservation;
- reserve, start, settle, cancel, expiry, usage-unknown, and overrun transitions;
- UTC estimate-validity, grant-expiry, start, and deadline guards;
- grant/workload/fence binding;
- exact accepted-or-rejected command replay and changed-payload conflict;
- monotone reservation/start/observation times and bounded usage-measurement times;
- deterministic transition-payload, receipt, transition-envelope, and state-chain hashes;
- conservative reconciliation and budget freeze after measured overrun.

It does not own cap selection, prices, model/provider choice, GPU placement, tenant
fairness, retry policy, autoscaling, scientific verdicts, or automatic budget raises.

The state-plane adapter owns a stricter I/O boundary:

- canonical UTF-8 JSON codecs for budgets, commands, transitions, receipts, and
  checkpoints;
- full semantic replay on every load or write, plus a cumulative journal head that
  binds even state-convergent rejected histories;
- one SQLite transaction for `(scope, command_id)` deduplication, the transition,
  revision/hash CAS, cached head, and immutable anchor outbox intent;
- response-loss recovery in which an exact retry is checked before a stale expected
  revision and returns the original receipt without a second transition;
- post-commit reconciliation against an externally stored signed checkpoint chain.

`SignedAppendOnlyFileAnchor` is a reference authority, not magic trust. Its directory
must be independently administered or genuinely append-only relative to the SQLite
writer; placing it beside the database under the same deletion-capable principal does
not detect wholesale rollback. A remote predecessor-CAS authority can implement the
same port. An accepted admission decision alone is not an execution permit, and this
slice still exposes no operation-agnostic `executable` boolean.

For the single implemented operation, `workload.dispatch/v1`, an accepted and
externally confirmed `StartGrant` is the durable effect intent. This is an explicit
semantic strengthening of that lifecycle command: its `command_id` is the stable
`effect_id`, and `IN_USE` conservatively means the dispatch may already have occurred;
it does not prove effect completion. The workload hash must cover the complete input
consumed by the effect adapter. This equivalence is scoped to workload dispatch and
does not turn arbitrary commands into effect intents.

`ResourceExecutionGate.prepare` loads a confirmed cut, persists `StartGrant`, reloads
the current cut even on exact replay, and mints an immutable permit bound to operation,
budget identity, grant, fence, workload, estimate and adapter identity, expiry,
StartGrant command/receipt hashes, state, checkpoint, and journal head. Permits are
short-lived (30 seconds by default, closed maximum 300 seconds, and never beyond the
grant). The pure permit is a claim, not effect authority: `prepare` seals it in an
authenticated envelope through an injected authenticator, and the reference shell
uses an HMAC-SHA256 tag and a pinned issuer. `dispatch` first verifies that envelope,
then performs another fresh load and pure revalidation immediately before calling the
injected effect port. Any forged envelope, unconfirmed authority, head movement,
cancellation/state change, binding drift, or expiry visible at that decision point
fails before the effect boundary.

Dynamic permit authority and stable effect identity are deliberately separate. A
legitimate replay after time or journal-head movement receives a different permit but
retains the same `intent_sha256`. The effect port must durably deduplicate exact
`(effect_id, workload_sha256, intent_sha256)` retries across process restarts, return
the same stable-intent receipt for an exact replay, and reject changed intent under
the same effect id. A live adapter must also atomically consume or reject the fence at
the target boundary; source-side reload alone cannot provide target-side fencing.

A port exception or mismatched receipt is `DispatchOutcomeUnknown`. While the process
is alive the gate immediately appends and confirms a stable `UsageUnknown`, retaining
the reservation in `RECONCILIATION_REQUIRED`. `reconcile` performs authoritative
adapter lookup only—it never redispatches—and validates any recovered receipt against
the stable intent. Recovery does not retain or revive the expired permit: a fresh
confirmed journal load discovers unresolved effect ids and reconstructs the stable
intent reference from the accepted `StartGrant`. Abrupt process termination can leave
the grant in `IN_USE`; that status already means “may have dispatched,” so restart
recovery also discovers it, looks up the same effect id, and never infers zero use. An
authoritative not-found result still does not release resources by itself. These
contracts provide operation-scoped replay safety; they are not a generic exactly-once
claim.

The final source-side revalidation is the dispatch linearization point. Journal
movement already visible there rejects the permit. A cancellation that commits after
that point is a later lifecycle event, moves the accepted start toward
`CANCEL_PENDING`, and requires the future idempotent `StopWork` path; it does not
retroactively prove that dispatch did not happen. This ordering, plus target-side
fence enforcement, is required of the live harness adapter.

`ResourceAuthority` and raw `WorkloadDispatchPermit` are immutable pure values, not
cryptographic bearer tokens. The trusted composition root constructs authority only
from a fully verified `JournalSnapshot`; the I/O gate accepts only an authenticated
permit envelope from its pinned authenticator. The bundled HMAC implementation is an
in-process reference boundary: deployment across an untrusted transport still needs
proper secret distribution, rotation, and endpoint authentication. Constructing either
pure dataclass directly does not confer authority over an effect port.

Reconciliation in this slice is synchronous and caller-driven. The outbox has only
`PENDING` and `CONFIRMED` states, and the journal does not yet stop a caller from
adding later revisions while an earlier checkpoint remains unconfirmed. Consequently,
an anchor outage can accumulate a local-only branch; none of that branch authorizes
an external effect. The remaining harness milestone must add a bounded
retry/deadline and reconciliation state machine and halt fresh branch advancement
while the trusted head is unresolved. The dispatch gate itself does not retry,
auto-settle usage, or guess whether a failed provider call took effect.

The initial dimensions are intentionally small and enforceable:

| dimension | meaning | accounting rule |
|---|---|---|
| `compute.wall_ms` | elapsed upper bound for the isolated work attempt | independent hard cap |
| `llm.input_tokens` | provider-reported total input, including cached input | independent hard cap |
| `llm.output_tokens` | provider-reported total output, including reasoning output | independent hard cap |

CPU time, memory-time, GPU-profile time, cache subcategories, and reasoning
subcategories require a new schema version and adapter evidence. A generic “GPU” unit
is specifically avoided because MIG profiles and time slicing are not fungible.

## Pure protocol

```text
decide(ResourceState, Command)       -> Decision(transitions)
evolve(ResourceState, Transition)    -> ResourceState
```

For a fresh command, its single transition is authoritative. `Decision.receipt`,
`Decision.rejection`, and `Decision.accepted` are read-only projections of that
transition; callers cannot attach contradictory wrapper metadata. An exact replay
has no new transition and projects the already-stored receipt.

The kernel reads no wall clock, network, database, environment variable, model, or
process. Commands carry canonical RFC3339 UTC observations and measurement
identities; the kernel compares those observations to estimate and grant deadlines.
The durable storage adapter commits command deduplication, transitions, revised state,
receipt, and the anchor outbox intent in one revision-checked transaction before any
response or anchor publication. External event names remain an emit-adapter concern,
not kernel vocabulary.

### State machine

```text
RequestGrant -> RESERVED | REJECTED(CAP_EXCEEDED / INVALID_TRANSITION)
RESERVED -> IN_USE | CANCELLED_UNUSED | EXPIRED_UNUSED
IN_USE -> SETTLED | CANCEL_PENDING | RECONCILIATION_REQUIRED
CANCEL_PENDING -> CANCELLED_SETTLED | RECONCILIATION_REQUIRED
RECONCILIATION_REQUIRED -> SETTLED | CANCELLED_SETTLED
measured usage > reservation -> QUARANTINED_OVERRUN + budget FROZEN
```

Stale estimates and invalid expiry ordering are specific `INVALID_TRANSITION`
details; they are not separate public failure codes in schema v1.

Unknown usage never becomes zero usage and never releases capacity. In-use
cancellation holds the reservation until a final measurement is settled and its
cancel intent survives reconciliation. Both accepted and rejected decisions advance
the command ledger when persisted. An exact `command_id` plus payload replay returns
the original receipt without a new transition; the same ID with a changed payload
raises `IDEMPOTENCY_CONFLICT`.

The content-addressing chain is deliberately acyclic:

```text
before/current and projected/next snapshots -> before/after state hashes
state hashes + command + resource deltas -> transition-payload hash
payload hash + decision fields -> receipt hash
payload hash + receipt hash -> transition-envelope hash
successive receipts require previous.after_state == next.before_state
```

`evolve` recomputes the content hashes and then regenerates the expected pure
decision. This rejects both ordinary receipt tampering and a self-consistently
rehashed transition that is illegal for the current state. Each receipt also binds
the full state before and after its transition. The retained journal must form a
contiguous chain from the budget genesis snapshot to the current snapshot, and state
construction replays every retained transition through that same decision function.
A locally rehashed journal cannot silently change a rejected command into an accepted
replay, and an empty journal cannot carry a phantom grant.

`ResourceBudget` is the immutable declaration (`scope`, `epoch`, and hard caps).
`ResourceState` is the revisioned ledger snapshot that embeds that declaration plus
spent usage, grants, status, and command records. A cap change therefore requires a
new budget epoch rather than mutating a live ledger in place.

## Invariants

For every active, non-overrun state and every dimension `d`:

```text
spent[d] + reserved[d] <= hard_cap[d]
```

Admission is atomic across the full vector: if one dimension exceeds remaining
capacity, no dimension is reserved. Settled usage charges the measured vector and
releases only the unused part of the original upper bound. A measured external
overrun is preserved rather than clipped; the budget becomes `FROZEN`, so it cannot
admit more work while reconciliation is required.

Resource receipts contain no `verdict`, `progressive`, `canonical`, or `novelty`
field. This is a structural boundary, not just a caller convention.

## Verification and remaining gates

Implemented now:

- RED-first defect and mechanism guards for symmetric compute/token caps;
- reserve/start/settle/cancel/expire/reconcile-needed/overrun traces;
- exact accepted and rejected replay plus changed-payload conflict;
- an OOPTDD receipt that drives the real kernel and, only in temporary subprocess
  copies, separately removes compute, input-token, output-token, causal-time,
  receipt-derived decision, and journal-semantic-replay guards to prove all six are
  load-bearing without exposing a production bypass;
- a dependency-free SQLite journal with `(scope, command_id)` uniqueness, full replay,
  revision-and-hash CAS, atomic checkpoint outbox, and strict schema/version readback;
- a signed append-only checkpoint-chain reference adapter with independent exact
  readback, rollback/fork detection, and idempotent crash-window reconciliation;
- real-file response-loss, stale-retry, two-connection last-slot, rollback,
  same-revision replacement, and signed-record tamper integration guards;
- an additional OOPTDD receipt that ablates commit-before-response in an isolated
  source copy and proves the durable ordering is load-bearing.
- a pure operation-specific authority kernel plus injected execution shell that treats
  confirmed `StartGrant` as workload-dispatch intent, binds permits to the exact
  confirmed cut, and revalidates immediately before the effect boundary;
- authenticated short-lived adapter-bound permits, stable intent-bound receipts,
  automatic `UsageUnknown`, journal-only recovery discovery, and lookup-only recovery
  through a restart-capable effect port;
- RED-first stale-head, cancellation, expiry, adapter/payload drift, remint/replay,
  response-loss recovery, forged authorization, and receipt-mismatch guards, plus
  OOPTDD mutants that remove immediate revalidation or permit authentication only in
  isolated source copies and then perform the forbidden physical effect.

Still required before claiming live dual-resource enforcement:

1. implement a durable build adapter that atomically enforces the fence, then wire one
   harness build effect through preflight with an injected `ResourceEstimate` and the
   operation-specific gate;
2. a real compute meter/limiter and an LLM provider usage adapter;
3. settlement/reconciliation workers, expiry observation, and an idempotent
   `StopWork` outbox effect for in-use cancel/deadline transitions;
4. only then, a versioned fair-queue or quality-per-cost routing policy.

Until those gates land, legacy harness calls remain uninstrumented. The repository can
claim a deterministic coordination kernel, a durable local journal with an
external-checkpoint protocol, and a tested workload-dispatch authority primitive—not
live target-fenced, metered, harness-wide, or fleet-wide enforcement.
