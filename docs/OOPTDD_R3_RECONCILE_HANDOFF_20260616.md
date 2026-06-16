# OOPTDD R3 Reconcile Handoff

Date: 2026-06-16
KG plan: `plan-ooptdd-R3-reconcile-20260616`

## Current Verdict

Stop further re-vendor writes until canonical ooptdd `gate.py` OpenSLO work is
committed and stable.

This is not a consumer bug. The vendor drift check is doing its job: consumer
vendored copies are lagging behind canonical work that is still uncommitted.

## Root Cause

Canonical `gate.py` is evolving toward OpenSLO support:

- `indicators`
- `ratioMetric`
- `present`
- operator aliases

That canonical work is currently WIP and not yet a committed source of truth.
Re-vendoring now would copy an unstable worktree snapshot into consumers.

## Done So Far

- Identified the vendor drift as intended lag detection, not a consumer-side
  logic failure.
- Stopped additional re-vendor commits to avoid copying uncommitted canonical
  WIP and colliding with concurrent workers.
- Lakatotree server/tree/lineage context refactor committed:
  `db4d7ef refactor(server): extract tree and lineage contexts`
- Post-commit lakatotree verification:
  - `python -m pytest tests/ -q` => `584 passed, 1 skipped`
  - `python -m lakatos.longinus` => `67/67 OK`
  - ooptdd cid: `pytest-bfbdd7c67639`
- KG updated:
  - `patch-lakatotree-postroadmap-lineage-service-extraction-20260616`
  - `longinus-audit-lakatotree-lineage-service-extraction-20260616`
  - `plan-ooptdd-R3-reconcile-20260616`

## Reconcile Order

1. Wait for canonical ooptdd `gate.py` OpenSLO commit/stabilization signal.
2. Verify canonical HEAD contains intended OpenSLO gate semantics.
3. Re-vendor consumers from committed canonical HEAD:
   - `consumer_a`
   - `consumer_b`
   - `lakatotree`
4. Use the canonical vendor script, for example:
   - `python ooptdd/scripts/vendor_ooptdd.py <consumer>`
   - or `python ooptdd/scripts/sync_consumers_from_head.py --apply`
5. Run each consumer's vendored drift test.
6. Run each consumer's relevant test suite.
7. In `lakatotree`, reconcile `ooptdd-migration` with server refactor commit
   `db4d7ef` before final re-vendor commit.
8. Record final re-vendor commit/test evidence in KG.

## Guardrails

- Do not re-vendor from uncommitted canonical WIP.
- Do not sweep/reset another worker's changes.
- Do not commit consumer re-vendor changes until canonical OpenSLO `gate.py` is
  committed.
- Treat current consumer drift as a correct signal, not an emergency fix.

## Next Trigger

When canonical ooptdd `gate.py` is committed, run the batch re-vendor and drift
test workflow for all three consumers.

