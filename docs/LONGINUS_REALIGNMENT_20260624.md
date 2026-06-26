# Longinus Realignment - 2026-06-24

> KG: `lesson-longinus-prom-review-realignment-20260624`,
> `CT_LakatoTree_3D_PROM_LonginusReview_20260624`
> LONGINUS: sourceId=`LakatoTree.LonginusPromReviewRealignment`,
> sourcePath=`docs/LONGINUS_REALIGNMENT_20260624.md:1`

This note corrects the 2026-06-24 3D/BPC review artifacts. Those files contain useful
industrial critique, but critique text is not Longinus by itself.

In `bhgman_tool`, Longinus means KG <-> source binding:

- `sourceId` is the semantic identifier, Frege Sinn.
- `sourcePath` is the physical location, Frege Bedeutung.
- A valid piercing needs a KG anchor plus code/doc location, not just a strong comment.
- `PIERCED` is a verified state, not a tone.
- `EXTRACTED`, `INFERRED`, and `AMBIGUOUS` are confidence tiers; `AMBIGUOUS` needs a human verdict.
- Drift is a lens-law violation: Missing, Orphan, SigMismatch, PatternDiv, or LabelRot.

## Correction

The following files are review evidence, not fully pierced Longinus bindings:

- `LONGINUS_INDUSTRIAL_DIMENSION_JUDGEMENT_20260624.md`
- `LONGINUS_ROOT_CAUSE_KUSARI_20260624.md`
- `LONGINUS_KUSARI_COMMENTARY_20260624.md`
- `LONGINUS_SELF_VERIFICATION_HELP_20260624.md`
- `BPC_Z_HEIGHT_CAD_SURFACE_PROM_20260624.md`
- `PROM_MEASUREMENT_AUDIT_20260624.md`

Their machine-readable status is kept in
`docs/longinus_prom_review_bindings_20260624.json`.

## Operating Rule

For 3D measurement review, do not mark a claim as `PIERCED` unless all of these are true:

1. The exact review claim has a `sourceId`.
2. The file location has a resolvable `sourcePath`.
3. The KG anchor is declared.
4. Evidence files are listed with the claim.
5. The claim has a drift risk and lens-law failure mode.
6. The acceptance check can be rerun.

If any condition is missing, the state is `CANDIDATE` or `PRELIMINARY`, never `PIERCED`.

## BPC Z-Height Specific Warning

The prior issue "CAD alignment was accepted even when z-height was wrong" must remain
`AMBIGUOUS` until the production path proves all three checks:

- rigid registration residual is separated from per-feature z residual,
- CAD surface membership is separated from measured surface contact,
- self-check thresholds include sign, frame, and per-feature distribution.

Until then, calling the alignment "good" is a Longinus error: it collapses `sourceId`
and `sourcePath`, then treats a surface hit as dimensional truth.
