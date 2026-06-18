# Research Tradition Design Note

Status: `DESIGN_FIRST_DOC_READY`

## Design Boundary

Laudan's research tradition is not the same object as Lakatos's hard core.

The existing Lakatos hard-core path must stay intact:

- `LakatosGate` treats hard-core violation as `different_programme`.
- `HardCoreProtected` prevents silent hard-core contraction or rewrite.
- `promotion_gate` remains the canonical promotion boundary.

A research tradition layer should initially be diagnostic-only. It can describe
revisable ontology and methodology drift, but it must not silently override
canonical promotion, abandonment, or hard-core identity.

## Proposed Objects

`ResearchTradition`

- `tradition_id`: stable id for a family of programmes.
- `name`: human label.
- `ontology_commitments`: entities, processes, and relations the tradition
  treats as legitimate.
- `methodology_rules`: accepted methods, instruments, inference styles, and
  admissible evidence forms.
- `exemplars`: canonical solved cases or model problems.
- `accepted_problem_types`: problems this tradition promises to solve.
- `background_theories`: neighbouring theories or domain assumptions it relies
  on.
- `revision_policy`: which commitments are revisable and what receipt is
  required for revision.
- `compatibility_notes`: why a change is same-tradition revision, tradition
  drift, or a different-programme candidate.

`TraditionCommitment`

- `commitment_id`
- `kind`: `ontology`, `methodology`, `exemplar`, `problem_type`, or
  `background_theory`
- `statement`
- `revisability`: `routine`, `costly`, or `identity_boundary`
- `source_refs`

`TraditionRevision`

- `target_commitment_id`
- `operation`: `add`, `modify`, `retire`, or `reclassify`
- `reason`
- `receipt_refs`
- `compatibility_claim`

`TraditionAppraisal`

- `outcome`: `same_tradition_revision`, `tradition_drift`, or
  `different_programme_candidate`
- `conceptual_pressure`
- `methodology_pressure`
- `ontology_pressure`
- `reasons`
- `authority`: always `diagnostic_only` in the first implementation

## Invariants

1. Hard-core violation is still a programme identity event, not ordinary
   degeneration.
2. A revisable tradition commitment may change without triggering
   `different_programme`, if its `revision_policy` receipt is satisfied.
3. An `identity_boundary` tradition commitment is not automatically the Lakatos
   hard core; it is a diagnostic warning unless explicitly mapped to hard core.
4. Research tradition diagnostics may feed `programme_series_appraisal`, but do
   not change canonical promotion authority.
5. Conceptual problems belong here before they are mixed into empirical
   problem-solving balance.

## Future OOPTDD Contracts

The first implementation should add tests for these outcomes:

- revising a `routine` ontology commitment yields `same_tradition_revision`;
- revising a `costly` methodology commitment yields `tradition_drift` unless
  receipts justify compatibility;
- revising an `identity_boundary` commitment yields
  `different_programme_candidate`, not direct hard-core violation;
- mapping a commitment to the actual hard core still routes through
  `LakatosGate` / `HardCoreProtected`;
- conceptual pressure from a tradition appraisal can be passed into
  `programme_series_appraisal` as diagnostic pressure only.

## Example Boundary

For a CAD-grounded deterministic 3D inspection tradition, "CAD model is a valid
geometric prior" may be a methodology commitment. A switch from hand-tuned edge
thresholding to a more robust surface matcher can be a same-tradition revision.
A switch to an end-to-end learned pose model may be tradition drift or a rival
tradition. It is a Lakatos `different_programme` only if it also violates the
programme's declared hard core.

## Implementation Plan

1. Add `lakatos/programme/tradition.py` with the four objects above.
2. Keep `authority == "diagnostic_only"` in `TraditionAppraisal`.
3. Add OOPTDD tests for routine/costly/identity-boundary revisions.
4. Add Longinus bindings for each public object.
5. Only after that, wire optional tradition pressure into
   `programme_series_appraisal`.
