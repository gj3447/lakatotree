# PROM 5 Report: Open Meaning Gaps

Cycle: `cycle-prom-lakatotree-open-gaps-20260618`
Lesson: `lesson-lakatotree-open-meaning-gaps-prom-20260618`

## Summary

The original five open gaps are real, but they are not all the same kind of
open. Three diagnostic layers have now been implemented, and one has been
closed as an explicit DON'T-DO policy.

| Gap | Triage | Decision |
| --- | --- | --- |
| Laudan conceptual problems | `IMPLEMENTED` | Pure score layer added, separate from empirical problem balance |
| Laudan comparative anomaly | `IMPLEMENTED` | Pure rival-relative anomaly evaluator added |
| Research tradition | `DESIGN_FIRST_DOC_READY` | Ontology/methodology design written; code still deferred |
| Novelty senses scored | `MAINTAIN_DONT_DO_CLOSED` | Explicit tag-only policy owner; do not score contested senses |
| Programme-as-series | `DIAGNOSTIC_LAYER_IMPLEMENTED` | Diagnostic aggregate added before verdict authority |

## Findings

1. `finding_lkt_open_gap_laudan_conceptual_20260618`
   Conceptual problems should not be hidden inside empirical open/closed
   question counts. A separate pure score layer now exists.

2. `finding_lkt_open_gap_laudan_comparative_anomaly_20260618`
   Laudan anomaly is rival-relative: an unsolved problem becomes an anomaly
   when a relevant rival solves it. A pure evaluator now captures this rule.

3. `finding_lkt_open_gap_research_tradition_20260618`
   A Laudan research tradition is broader and more revisable than a Lakatos
   hard core. It now has a design note and should not be patched into hard-core
   protection.

4. `finding_lkt_open_gap_novelty_senses_20260618`
   Temporal novelty, Zahar use-novelty, and Worrall/essential use-novelty
   diverge. Current tag-only policy is intentional, owned by
   `judge.NOVELTY_SENSE_SCORING_POLICY`, and covered by OOPTDD receipts.

5. `finding_lkt_open_gap_programme_series_20260618`
   A research programme is a series/problem-shift object. Lakatotree has
   lifecycle/metrics coverage, and now has a dedicated series diagnostic before
   any verdict-authority change.

## Action Plan

- Do not implement all five gaps immediately.
- Preserve the gap registry with explicit triage and sources.
- Higher-level integration for `conceptual_problem_score` needs a separate
  policy decision before it can influence abandonment or lifecycle verdicts.
- Higher-level integration for `rival_relative_anomaly` needs typed target/rival
  problem records at the tree surface.
- Research tradition design is ready; implementation waits for an accepted
  diagnostic consumer.
- Novelty-sense scoring is closed as a DON'T-DO until a stable oracle exists.
- Programme-series diagnostics remain off-spine until a separate authority
  decision rewires canonical promotion or abandonment.

## Verification

- `pytest -q tests/test_meaning_srp.py`
- `pytest -q tests/test_judge.py tests/test_laudan.py tests/test_lifecycle.py`
