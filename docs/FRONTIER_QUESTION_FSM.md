# Frontier Question FSM

> Generated view. Authoritative source: `docs/data/frontier_question_fsm.v1.json`.
> Regenerate with `python scripts/render_frontier_question_fsm.py`.

## Transition table

| From | Event | To | Transition | Effects |
|---|---|---|---|---|
| `OPEN` | `OPEN` | `OPEN` | `refresh-open` | UpdateQuestionMetadata |
| `OPEN` | `CLOSE` | `CLOSED` | `close` | RecordQuestionClosure |
| `CLOSED` | `CLOSE` | `CLOSED` | `duplicate-close` | none |
| `OPEN` | `ADJUDICATED [receipt_backed_conclusive]` | `CLOSED` | `adjudication-close` | RecordQuestionClosure |
| `OPEN` | `ADJUDICATED` | `OPEN` | `adjudication-retain-open` | none |
| `CLOSED` | `ADJUDICATED` | `CLOSED` | `duplicate-adjudication` | none |

Unlisted state/event pairs are rejected without state change. In particular, `CLOSED + OPEN`
is invalid. `CLOSED` is intentionally atomic rather than final so duplicate `CLOSE` has an
explicit idempotent self-loop.

`ADJUDICATED` is a transition event, not a client verdict label. The judgement
service emits it only after minting the content-addressed verdict receipt in the
same managed transaction. Exact final verdicts `progressive` and `rejected`
answer the preregistered question positively or negatively. Partial,
equivalent, conditional, and unverified outcomes keep the question open.

## State diagram

```mermaid
stateDiagram-v2
    [*] --> OPEN
    OPEN --> OPEN: OPEN / UpdateQuestionMetadata
    OPEN --> CLOSED: CLOSE / RecordQuestionClosure
    CLOSED --> CLOSED: CLOSE / none
    OPEN --> CLOSED: ADJUDICATED [receipt_backed_conclusive] / RecordQuestionClosure
    OPEN --> OPEN: ADJUDICATED / none
    CLOSED --> CLOSED: ADJUDICATED / none
```

## Properties

Safety:

- `closed-does-not-reopen`: A CLOSED question cannot return to OPEN through the OPEN command.
- `close-is-idempotent`: Repeated CLOSE commands do not increment visits or append closure/history events.
- `self-report-cannot-close`: An adjudication without a valid content-addressed receipt identity cannot close a question; the application transaction persists that receipt and closure together.

Liveness:

- `eventual-close`: An OPEN question reaches CLOSED when a CLOSE command or receipt-backed conclusive ADJUDICATED event is delivered.

## Verification

```bash
python /path/to/fsm-design/scripts/validate_fsm.py docs/data/frontier_question_fsm.v1.json
python /path/to/fsm-design/scripts/run_fsm_traces.py docs/data/frontier_question_fsm.v1.json docs/data/frontier_question_fsm.traces.json
pytest -q tests/test_state_isolation_fsm_20260728.py
python ooptdd_receipts/run_all.py
```
