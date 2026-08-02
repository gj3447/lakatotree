#!/usr/bin/env python3
"""Render the human view from the authoritative frontier-question FSM JSON."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/data/frontier_question_fsm.v1.json"
TARGET = ROOT / "docs/FRONTIER_QUESTION_FSM.md"


def render(spec: dict) -> str:
    machine = spec["machines"][0]
    rows = []
    edges = []
    for transition in machine["transitions"]:
        effects = ", ".join(transition.get("effects", [])) or "none"
        guard = f' [{transition["guard"]}]' if transition.get("guard") else ""
        rows.append(
            f'| `{transition["from"]}` | `{transition["event"]}{guard}` | '
            f'`{transition["to"]}` | `{transition["id"]}` | {effects} |'
        )
        edges.append(
            f'    {transition["from"]} --> {transition["to"]}: '
            f'{transition["event"]}{guard} / {effects}'
        )
    safety = "\n".join(f'- `{item["id"]}`: {item["statement"]}' for item in spec["safety_properties"])
    liveness = "\n".join(f'- `{item["id"]}`: {item["statement"]}' for item in spec["liveness_properties"])
    return f"""# Frontier Question FSM

> Generated view. Authoritative source: `docs/data/frontier_question_fsm.v1.json`.
> Regenerate with `python scripts/render_frontier_question_fsm.py`.

## Transition table

| From | Event | To | Transition | Effects |
|---|---|---|---|---|
{chr(10).join(rows)}

Unlisted state/event pairs are rejected without state change. In particular, `CLOSED + OPEN`
is invalid. `CLOSED` is intentionally atomic rather than final so duplicate `CLOSE` has an
explicit idempotent self-loop.

`ADJUDICATED` is a transition event, not a client verdict label. The judgement
service emits it only after minting the content-addressed verdict receipt in the
same managed transaction. Exact final verdicts `progressive` and `rejected`
answer the preregistered question positively or negatively only when the
sealed assurance is replay-verified (L2 or higher) and the result is not a
qualitative self-report. Partial, equivalent, conditional, unverified, L0/L1,
and qualitative-self-report outcomes keep the question open.

## State diagram

```mermaid
stateDiagram-v2
    [*] --> {machine["initial"]}
{chr(10).join(edges)}
```

## Properties

Safety:

{safety}

Liveness:

{liveness}

## Verification

```bash
python /path/to/fsm-design/scripts/validate_fsm.py docs/data/frontier_question_fsm.v1.json
python /path/to/fsm-design/scripts/run_fsm_traces.py docs/data/frontier_question_fsm.v1.json docs/data/frontier_question_fsm.traces.json
pytest -q tests/test_state_isolation_fsm_20260728.py
python ooptdd_receipts/run_all.py
```
"""


def main() -> int:
    TARGET.write_text(render(json.loads(SOURCE.read_text(encoding="utf-8"))), encoding="utf-8")
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
