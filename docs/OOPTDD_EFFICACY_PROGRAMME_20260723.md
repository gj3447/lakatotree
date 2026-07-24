# ooptdd efficacy absorption programme — preregistration

This programme asks a narrower question than “does ooptdd work?”:

> Can ooptdd produce evidence whose aggregate claims are independently
> recomputable, whose negative controls are non-vacuous, and whose arrival
> mechanics remain correct across repeated loss, lag, flap, outage, mutation,
> and oracle-independence scenarios?

The machine-readable preregistration is
[`ooptdd_receipts/ooptdd_efficacy_absorption_20260723/preregistration.json`](../ooptdd_receipts/ooptdd_efficacy_absorption_20260723/preregistration.json).
It is committed before candidate implementation or candidate measurement.

## Exploratory baseline

The starting ooptdd head is
`53e646a7756325f4050819d7e00add87988fca4a`. Earlier measurements established
useful regression behavior, but implementation preceded their registration.
They therefore remain exploratory. In particular, the 27-case trajectory
battery is not renamed “held out”, and its `21` reused cases carry no novelty
weight.

Four executable integrity gaps define the baseline value `4`:

1. A trajectory-only mutation report has `n=0` while displaying `score=1.0`.
2. The evidence builder trusts top-level aggregate metrics instead of
   recomputing them from raw observations.
3. The evidence builder does not enforce the preregistered source heads and
   specification hash.
4. CI generates the real DeepEval held-out artifact but does not assert it.

## Frozen measurement contract

The primary metric is `unresolved_evidence_integrity_gaps` (`lower`, baseline
`4`, target `0`). The independent novel metric is
`tier0_required_oracle_match_rate` (`higher`, threshold `1.0`) over `20`
repetitions of the six scenario families named in the preregistration.

The benchmark must preserve three distinct outcomes:

- `present`: the required evidence arrived;
- `absent`: a complete reachable read falsified the requirement;
- `inconclusive`: the store or probe could not supply a clean observation.

JUnit and Markdown are projections of canonical JSON. They may not re-judge
the run. A correct outage scenario is an overall oracle match because the
expected engine verdict is `inconclusive`, while its own JUnit testcase remains
`skipped`/inconclusive. A benchmark-harness failure is a separate infrastructure
error and never an ordinary scenario pass or failure.

## Research absorption boundary

The programme absorbs mechanisms, not product breadth:

- Inspect AI: observation-first logs, retry/rescore lineage, and aggregate
  recomputation;
- promptfoo: full JSON as authority with lossy CI projections;
- Stryker and mutation-testing research: explicit eligible denominator and
  per-operator mutant identity;
- tau-bench: repeated reliability rather than one lucky trajectory;
- ToolSandbox and AgentDojo: paired milestones/minefields and safe-utility
  controls;
- runtime verification: explicit `present | absent | inconclusive` over finite
  traces.

It does not absorb dashboards, selector-language breadth, red-team generation,
or an in-kernel LLM judge.

## Evidence sequence

1. Commit this preregistration.
2. Implement the ooptdd candidate.
3. Freeze raw positive and injected-negative artifacts.
4. Replay the unchanged positive after the negative control.
5. Recompute aggregates from raw observations in a separate evidence step.
6. Run the deterministic LakatoTree judge; never place a hand-entered verdict
   in the evidence record.
