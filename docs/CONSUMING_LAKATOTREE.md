# Consuming LakatoTree as a library — you do not touch this repo

> **Canonical.** Enforced, not aspirational: the `engine ⊥ examples` import-linter contract,
> the Longinus code↔KG bindings, the README module-map bijection test, and
> `tests/test_packaging_contract.py` together make every claim below regression-guarded.
> If any of them drifts, CI goes red.

## TL;DR

Growing a research programme, authoring nodes, judging measurement records, and computing tree
metrics are all done by **importing the installed package** — never by editing this repository.
The *only* thing that requires editing engine source (`lakatos/`, `server/`) is changing the
engine's own judgment logic, which is out of scope for a user.

The old mental worry — *"growing a branch modifies the engine repo, like `git init` modifying
git's own source"* — is now **false by construction**: the engine cannot import your content, and
your content depends on the engine as a package.

## Install

LakatoTree is not published on PyPI yet. Until the first tagged release, install
from a source checkout and pin the commit SHA used by reproducible work:

```bash
git clone https://github.com/gj3447/lakatotree.git
cd lakatotree
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .             # library core — stdlib only
python -m pip install -e ".[server]"  # + HTTP/MCP and required DB drivers
python -m pip install -e ".[db]"      # + DB drivers without the web surface
python -m pip install -e ".[prov]"    # + W3C PROV-O libraries
python -m pip install -e ".[all]"     # all runtime and development extras
```

The **library core** (`lakatos.quant`, `lakatos.verdict`, `lakatos.programme`) has **zero
third-party dependencies** — measured against a bare venv, pinned by
`tests/test_packaging_contract.py::test_base_install_has_no_third_party_deps`. Server / DB / MCP /
PROV are opt-in extras. That is what makes *N* parallel engines cheap: each consumer installs only
what it actually runs.

## Public authoring API — write a programme without touching this repo

```python
from lakatos.programme.authoring import node
from lakatos.programme.evidence import load_record, is_grounded, summarize
from lakatos.programme.record_judge import judge_record
from lakatos.quant.metrics import tree_metrics

nodes = [
    node('prob', 'canonical_stage', None, algo='problem', comment='the problem'),
    node('d1', 'partial', 'prob', m=0.02, base=0.05, mn='sigma_mm', nr=True, nc=False,
         comment='instrument-valid, not yet field-confirmed'),
]
frontier = [dict(name='q1', status='CLOSED', closed_by=['d1'], body='does D1 hold?')]
metrics = tree_metrics(nodes, frontier)
```

- **`node(...)`** builds a schema-correct tree-node dict. The multiple-comparison family key is
  `(metric_name, scope)` — always pass `mn=` for measured nodes, else heterogeneous metrics collapse
  into one family and BH/FDR control is undefined.
- **`evidence`** loads/validates measurement records under the honesty invariants (no verdict inside
  the record, grounded provenance, pre-registration — full contract in [`EVIDENCE_RECORD.md`](EVIDENCE_RECORD.md)).
- **`record_judge.judge_record`** turns a grounded record into an **engine-generated** verdict.
  Self-scoring is blocked; a metric-name mismatch returns `ABSTAIN` rather than a hand verdict —
  it surfaces the real gap instead of papering over it.

**Verdicts are derived, never hand-set.** `submit_result` / `judge` produce them from a
pre-registered prediction and a measured value. Writing `verdict='progressive'` by hand is the
fake-green anti-pattern the whole engine exists to prevent.

The metric scorer and the dialectical layer are distinct. A metric result that qualifies as
`progressive` but has neither Lakatos evidence nor a PnR appraisal is persisted as
`progressive_unverified`: known and in-programme, but not counted as programme progress,
the branch-stack `prediction_hits` signal, or promotion authority. It is a neutral streak boundary:
it neither increments consecutive nonprogressive depth nor gets skipped when that leafward streak
is measured. Predictive fertility remains an orthogonal registration/confirmation ratio and still
counts an independently confirmed novel prediction regardless of this verdict. A
progressive/conditional PnR appraisal can rescue it to `progressive`/`progressive_conditional`.

The basic CLI and MCP `submit_result` surface accept the same qualitative/PnR evidence as the
REST `TestResultIn` schema. For a Lakatos appraisal, submit all four axes explicitly; omission means
“unknown”, while each CLI `--no-lakatos-*` form means an explicit negative observation:

```bash
python -m lakatos.cli result MY_TREE v2 --value 0.4 --script judge.py \
  --lakatos-anomaly --lakatos-consequence --lakatos-excess --lakatos-hardcore \
  --touched-assumption auxiliary-model-a
```

Alternatively, a PnR appraisal can be supplied through `--counterexample-response` plus its
`--ce-*` evidence (the MCP tool uses the corresponding snake-case parameters):

```bash
python -m lakatos.cli result MY_TREE v2 --value 0.4 --script judge.py \
  --counterexample-response lemma_incorporation --counterexample-type local \
  --ce-excess-content --ce-novel-corroborated --ce-in-heuristic-spirit
```

These inputs do not hand-set a verdict: the server still validates the enum values, evaluates the
evidence, and derives the dialectical verdict. A node already sealed as `progressive_unverified`
cannot be re-rolled with new evidence; submit the evidence with the initial result or create a new
branch node.

## One-off vs durable

| you want… | do this | touches this repo? |
|---|---|---|
| a node live in the running tree | MCP verbs (`add_node`, `open_question`, …) | no — runtime data |
| **author a programme (nodes / evidence / judge)** | the public API above | **no** |
| a durable, reproducible, CI-tested programme | `my_programme.py` + a test **in your own repo**, LakatoTree pinned to an exact commit until the first release | no |
| change the engine's judgment logic | edit `lakatos/` or `server/` | yes — explicit, and only this |

## The boundary is CI-enforced

`examples/` (research programmes = content) may import the engine; the engine (`lakatos/`,
`server/`) must **never** import `examples/`. This is the `.importlinter` forbidden contract
`engine (lakatos, server) must not import examples` (revert-proof: reintroducing an engine→examples
import turns `lint-imports` red). So the directional boundary "tool ⊥ content" is a machine check,
not a convention.

The authoring primitives used to live in `examples/` (outside the installed package), which forced
vendoring; they were promoted to `lakatos.programme.{authoring,evidence,record_judge}` on
2026-07-03. `examples/_evidence.py` and `examples/record_judge.py` remain thin back-compat
re-export shims so the in-repo programmes keep working; **new code imports from `lakatos.programme`.**

## Multi-engine deployment

The engine was never "one instance". Two layers:

- **Library layer** is already per-process: every `tree_metrics` / `judge` call is an independent,
  stateless in-process engine. Running *N* programmes in parallel = *N* engines, today.
- **Server + KG layer** is fully env-parameterized (`NEO4J_URI`, `LAKATOS_PG_DSN`,
  `LAKATOS_RAW_ROOT`, `LAKATOS_SCRIPT_ROOTS`, `LAKATOS_LOCATIONS`, `LAKATOS_PRODUCER`, …). Run one
  shared server as a coordination ledger (like a single git remote), or many isolated servers each
  on its own store. Singularity is a deployment choice, not an architectural assumption.

## What still requires editing engine source

Only changing the engine's judgment logic itself (`lakatos/`, `server/`) — and only under explicit
instruction. Authoring, registering, running, judging, and reproducing are all library consumption.
