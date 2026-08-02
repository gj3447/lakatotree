# ADR: CLOSED question reattribute (receipt-backed closer append)

- **Status**: Accepted (Sprint A P0-2, 2026-07-31)
- **Tree context**: `LakatosTree_LakatoTree_SelfDev_20260612` / `q-selfdev-closed-question-reattribute-20260731`
- **Related**: P0-1 `close_ratio_receipted` ↔ `force_of_row` align

## Context

SelfDev live showed **7 unreceipted closes**: closers were `admin` / former_canonical or empty `closed_by`.  
`close_question` only mutates when `before_state=OPEN`. `CLOSED + CLOSE` is intentional **duplicate-close** (idempotent, no append).  

Scripted re-judge of historical nodes is **409** (no re-roll). So unreceipted closes could not be repaired without either:

1. silent history rewrite (rejected), or  
2. a new append-only path that never reopens.

## Decision

Add FSM event **`REATTRIBUTE`** (pure reducer in `lakatos/frontier_state.py` + `docs/data/frontier_question_fsm.v1.json`):

| From | Event | Guard | To | Effect |
|---|---|---|---|---|
| CLOSED | REATTRIBUTE | receipt_backed_conclusive | CLOSED | `AppendQuestionCloser` |
| CLOSED | REATTRIBUTE | receipt present, non-conclusive | CLOSED | (none) |
| OPEN | REATTRIBUTE | — | — | **reject** (use CLOSE/ADJUDICATED) |
| any | REATTRIBUTE | invalid/missing sha | — | **reject** |

Application service `TreeService.reattribute_question`:

1. Load closer node; require **`force_of_row(closer) == COUNTS`** (same predicate as progress credit).  
2. Reduce pure FSM with closer `verdict` + `current_receipt_sha`.  
3. On `AppendQuestionCloser`: append-only `closed_by` / `closed_events` / `QuestionClosure` with **unique** id `tree/q/closure/{by}@{ts}` (`kind=reattribute`).  
4. **Never** set status back to OPEN.

Surfaces: REST `POST .../question/{qname}/reattribute?closed_by=`, MCP `reattribute_question`.

## Consequences

- Unreceipted admin closes can gain a **second**, receipted closer without erasing the admin closer (append-only).  
- Metrics `close_ratio_receipted` (COUNTS-aligned) rises when a COUNTS closer is present in `closed_by`.  
- CLOSE remains idempotent; reopen remains forbidden.  
- Application still must **not** invent verdicts; closer must already be a judged COUNTS node.

## Non-goals

- Reopening CLOSED questions.  
- Re-judging scripted nodes.  
- Auto-reattribute of all legacy closes (manual/agent GO per question).

## Alternatives considered

| Option | Why not |
|---|---|
| (b) ADR+GO one-shot KG patch | Works but not agent-operable; no FSM contract |
| (c) SUPERSEDE + new OPEN | Honest freeze, higher process cost; still available |
| CLOSED+CLOSE append | Breaks close-is-idempotent safety property |
