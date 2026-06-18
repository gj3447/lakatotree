# PROM 8 Report: Semantic Surface Hardening

Cycle: `cycle-prom-lakatotree-semantic-surface-20260618`
Lesson: `lesson-lakatotree-semantic-surface-prom-20260618`

## Consensus

The right next move is not to inflate LOC. The enforceable unit is:

`meaning_id -> change_actor -> owner_sourceId -> Longinus binding -> tests -> docs/source refs`

This keeps the user's "meaning/code 1:1" requirement as a responsibility
contract, not as a class-per-slogan rule.

## Findings

1. `finding_lkt_semantic_bdd_actor_20260618`
   Semantic units need the actor/reason of change, not only an owner symbol.

2. `finding_lkt_traceability_bidirectional_20260618`
   Traceability must be persisted in repo artifacts, not only KG memory.

3. `finding_lkt_prov_external_evidence_20260618`
   External evidence and Prom outputs need source references beside the unit
   they justify.

4. `finding_lkt_solid_no_loc_inflation_20260618`
   Meaning-code 1:1 is a responsibility ratchet, not a LOC quota.

5. `finding_lkt_dip_domain_abstractions_20260618`
   Semantic policy should remain pure and domain-shaped, not coupled to HTTP,
   Cypher, or live KG adapters.

6. `finding_lkt_adr_decision_log_20260618`
   This Prom cycle needs a filesystem decision artifact so future audits can
   recover the reasoning.

7. `finding_lkt_registry_scope_gap_20260618`
   `meaning_units.json` and `semantic_surface.json` can coexist only if the
   latter is explicitly a critical architecture subset.

8. `finding_lkt_surface_ratchet_too_thin_20260618`
   The semantic surface test was too thin: it needed to fail on missing actor
   and source metadata.

## Action Plan

- Add `change_actor` and `source_refs` to each semantic surface unit.
- Validate those fields in `lakatos.semantic_surface.validate_surface`.
- Add tests that catch missing actor/source metadata.
- Keep this report and source list under `THEORY/lakatotree-semantic-surface/`.

## Verification Plan

- `pytest -q tests/test_semantic_surface.py tests/test_meaning_srp.py tests/test_longinus_bindings.py`
- `python -m lakatos.longinus`
- Full suite if the focused gates pass.

