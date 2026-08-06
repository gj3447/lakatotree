# Dual-resource coordination (v1)

- Status: **executable kernel; persistence and live metering not yet wired**
- Schema: `lakatotree.resource/v1`
- Code: `lakatos/resource_coordination.py`

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

## v1 boundary

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
A storage adapter must commit command deduplication, transitions, revised state,
receipt, and any outbox intent in one revision-checked transaction before executing
the effect. External event names are an emit-adapter concern, not kernel vocabulary.

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
  load-bearing without exposing a production bypass.

Still required before claiming live dual-resource enforcement:

1. a durable CAS/event-journal adapter with `(scope, command_id)` uniqueness;
2. commit-before-response-loss and concurrent last-slot integration tests;
3. a harness preflight that receives an injected `ResourceEstimate`;
4. a real compute meter/limiter and an LLM provider usage adapter;
5. settlement/reconciliation workers, expiry observation, and an idempotent
   `StopWork` outbox effect for in-use cancel/deadline transitions;
6. only then, a versioned fair-queue or quality-per-cost routing policy.

Until those gates land, legacy harness calls remain uninstrumented. The repository can
claim an executable deterministic coordination kernel—not durable or fleet-wide
enforcement.
