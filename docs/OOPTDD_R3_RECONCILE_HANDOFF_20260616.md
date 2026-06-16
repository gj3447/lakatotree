# OOPTDD R3 Reconcile Handoff

Date: 2026-06-16
KG plan: `plan-ooptdd-R3-reconcile-20260616`

## Current Verdict

Stop further re-vendor writes until the current consumer WIP ownership is clear.

This is not a consumer bug. The vendor drift check is doing its job: consumer
vendored copies are lagging behind canonical HEAD.

Follow-up inspection on 2026-06-16 found that canonical `src/ooptdd` is clean and
committed at `01a3a09`, while all three consumers are behind canonical HEAD on
the same six files:

- `__init__.py`
- `model.py`
- `gate.py`
- `ontology.py`
- `backends/__init__.py`
- `backends/otel.py`

So the blocker is not "canonical gate.py is uncommitted" anymore. The blocker is
coordination: the current consumer vendored WIP is a partial/mixed snapshot, and
batch re-vendor would overwrite that WIP. The next owner should either preserve
that WIP intentionally or replace it with canonical HEAD via the reconcile script.

## Root Cause

Canonical `gate.py` is evolving toward OpenSLO support:

- `indicators`
- `ratioMetric`
- `present`
- operator aliases

Canonical HEAD already includes later tier work beyond the partial consumer WIP,
including MTL intervals / HMAC hash-chain / ontology compatibility / GenAI
dogfood. Re-vendoring now from canonical HEAD would not copy uncommitted WIP, but
it would replace the current partial consumer WIP. That replacement should be
deliberate and coordinated.

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
- Follow-up read-only inspection:
  - canonical ooptdd: `01a3a09`, `src/ooptdd` clean
  - `sync_consumers_from_head.py` dry-run: all three consumers would sync 6 files
  - `reconcile_consumers.py` dry-run: all three consumers behind on the same 6 files
  - current lakatotree dirty vendor state still passes local tests:
    `python -m pytest tests/ -q` => `584 passed, 1 skipped`

## Reconcile Order

1. Decide who owns the current consumer vendored WIP.
2. If the WIP is disposable, re-vendor consumers from committed canonical HEAD:
   - `consumer_a`
   - `consumer_b`
   - `lakatotree`
3. Prefer the divergence-aware script:
   - `python ooptdd/scripts/reconcile_consumers.py --apply`
4. Run each consumer's vendored drift test.
5. Run each consumer's relevant test suite.
6. In `lakatotree`, reconcile `ooptdd-migration` with server refactor commit
   `db4d7ef` before final re-vendor commit.
7. Record final re-vendor commit/test evidence in KG.

## Guardrails

- Do not re-vendor over active consumer WIP without an explicit ownership decision.
- Do not sweep/reset another worker's changes.
- Canonical `src/ooptdd` is currently clean at `01a3a09`; if that changes, check
  `git status --short src/ooptdd` again before applying.
- Treat current consumer drift as a correct signal, not an emergency fix.

## Next Trigger

When the current consumer WIP ownership is resolved, run the batch re-vendor and
drift test workflow for all three consumers.
