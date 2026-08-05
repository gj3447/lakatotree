# SCHEMA_NOTE — ooptdd Tier-1 arrival receipts

Landed on `master` 2026-08-05 from the orphan branch
`prereg/ooptdd-tier1-arrival-20260724`, which was then retired. Nothing here was
edited during the transplant.

## Registration anchor

**The registration anchor is the tag, not this directory.**

    evidence/ooptdd-tier1-arrival-20260724  ->  506f8aa

`preregistration.json` was amended *after* measurement (commit `5e2d4bc`:
`honesty_boundaries`, Mac-local judge-of-record → Proxmox openobserve-01). The
copy in this directory is therefore the amended one. The original registration
wording, and the register → lock → measure ordering with its ~5 minute margin,
survive only as commit objects reachable from that tag. Anyone auditing whether
the prediction really preceded the measurement must read the tag, not these files.

Timeline as recorded: registered 2026-07-24T17:06:30Z, locked 17:45:39Z,
measured 17:50Z; Proxmox re-measurement 2026-07-25T02:36:03Z.

## Known schema non-conformance — deliberate, do not "fix"

`evidence_record.json` predates `lakato-evidence-record/v1` and does not satisfy
`lakatos.programme.evidence.validate_record`. Five findings as of 2026-08-05:
missing `conjecture`, `measurement` and `provenance` blocks, no `grounding`, and
`registered_before_measurement` sitting at top level rather than inside the
measurement block.

It is landed unmodified anyway. This is a preregistration artefact: retrofitting
it to a schema published after the fact would destroy the only property that
makes it worth keeping — that it says what it said before the numbers existed.
A record that gets tidied to match later expectations is not evidence of a
prediction.

**Treat `tier1_result_*.json` as the verdict of record.** `evidence_record.json`
is historical context, and its non-conformance is expected, not a defect to close.

## Relation to the sibling preregistration

`ooptdd_receipts/ooptdd_efficacy_absorption_20260723/preregistration.json`
carries the honesty boundary *"A real OpenObserve Tier 1 run is required…"*.
That boundary is now satisfied by the receipts here. **Do not edit that file to
say so** — same reason as above. This note is the cross-reference.
