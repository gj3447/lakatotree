# Longinus Root-Cause Kusari

Date: 2026-06-24

Question: why are the current 3D programmes not yet perfectly accurate and
precise for industrial dimensional judgement?

Short answer:

> Because the system is mixing three different truths: registration truth,
> feature measurement truth, and conformity truth. Those are not interchangeable.

This document records the PROM root-cause critique and the required correction
path.

## Root-Cause Stack

| Layer | Failure Mode | Evidence In Current Work | Longinus Comment |
|---|---|---|---|
| Sensor physics | structured-light point clouds are not a CMM; accuracy varies with distance, surface, feature size, view angle, exposure | BPC noise floor and GUM components; SX3i XL250 precision floor; LX3 flat patch RMS and turntable/runout concerns | Stop promising sub-0.1mm unless the hardware evidence says it is physically available |
| Registration geometry | flat/repetitive/symmetric parts create null spaces and local minima | BPC free ICP collapse, 6-DOF degeneration; LX3 markerless identity basin; SX3i markerless C3 failure | ICP residual is not a GD&T certificate |
| CAD correspondence | CAD nominal frame and scan frame are not automatically the same datum system | LX3 bush nominal ruler exists but bush-vs-CAD accuracy is over tolerance; BPC global cloud p95 remains rough | CAD overlay looking plausible is not datum conformance |
| Feature extraction | detection/segmentation is not measurement | SX3i C1 marker detection passes but C3 is still blocked/refuted; BPC segmentation is ROI/helper only | Detection can open a gate; it cannot close an industrial dimension |
| Measurement system | repeatability and uncertainty are too large for tight tolerance calls | BPC sigma_repeat_xy 0.644mm; p95 sigma 0.840mm; tight tolerance MSA conflict | 182/183 PASS is not enough if the gauge cannot defend near-limit calls |
| Conformity decision | pass/fail lacks guard band and decision rule | current reports often have deviation/tolerance but no explicit U/decision rule | Near tolerance must support `indeterminate`, not forced PASS/FAIL |
| Evidence plumbing | narrative and Python node comments still carry too much measurement meaning | PROM record schema exists but does not yet require uncertainty/decision-rule/gauge for adoption | The tree needs executable receipts, not heroic prose |

## Why Perfect Accuracy Is Not Closing

### 1. The Scanner Is Not The Datum

Structured-light scanners produce dense point clouds, but their useful
measurement accuracy is task-specific. NIST scanner-error work explicitly warns
that lateral resolution from pixels/FOV is not the same as the smallest
measurable feature, and that one scanner accuracy value may be inadequate
because accuracy varies by artifact location and distance.

Local consequence:

- SX3i can see markers at 89.6px median side length, but that does not prove
  sub-0.1mm feature accuracy.
- BPC can have feature deviations under nominal tolerance while the measurement
  system remains too noisy for tight near-limit calls.
- LX3 can have good marker geometry and still fail bush-vs-CAD accuracy.

Kusari:

> Stop treating point density as metrology. Dense wrong points are still wrong.

### 2. Registration Is A Source Of Error, Not Just A Solver Step

Point-cloud registration literature treats degeneracy as a first-class problem.
Flat panels, repeated holes, symmetric shapes, and low overlap create null
directions and false minima.

Local consequence:

- BPC free/global ICP collapse is expected, not surprising.
- LX3 markerless identity basin is the same disease in a different part.
- SX3i markerless C3 gives median 13.1754mm where 0.1mm was required. That is a
  rejected measurement route, not an almost-finished route.

Kusari:

> If the geometry is underconstrained, more ICP iterations just polish the wrong
> answer.

### 3. Precision Was Mistaken For Accuracy Too Often

Precision answers: "do repeated measurements agree?" Accuracy answers: "do they
agree with truth?" Industrial conformance needs the second.

Local consequence:

- LX3 known-axis ArUco precision: RMS median 0.993mm, wrong-axis control 64.3mm.
  Good precision evidence.
- LX3 bush-vs-CAD: -2.343mm error against 1093.3mm nominal, over ±1mm.
  Accuracy not closed.
- SX3i marker detection: good C1. Accuracy still open.

Kusari:

> Repeatable wrong is still wrong. Do not promote it.

### 4. CAD Datum Is Not Yet A Contract Everywhere

Industrial dimensioning is not just "distance to CAD mesh." You need the exact
feature, datum frame, nominal, tolerance, extraction rule, and decision rule.

Local consequence:

- BPC global scan-to-CAD p95 can be rough while feature-fusion remains the only
  defensible path.
- LX3 CAD nominal ruler is a good step, but it only becomes production evidence
  after registered bush features match it.
- SX3i CAD registration RMSE 1.06mm is not C3 sub-0.1mm feature coincidence.

Kusari:

> CAD is not magic truth unless the datum and feature extraction contract are
> explicit.

### 5. MSA Is Not Optional

Measurement System Analysis exists because a measuring system can make bad
decisions even when the measured part looks plausible. MSA/Gage R&R evaluates
whether measurement variation is acceptable relative to tolerance.

Local consequence:

- BPC has a good-looking 182/183 feature report.
- BPC also has sigma_repeat_xy 0.644mm and p95 sigma 0.840mm.
- Therefore tight `±0.8mm` calls are not clean industrial green. They need
  guard-banding or indeterminate states.

Kusari:

> A pass table without gauge capability is a pretty spreadsheet, not PPAP-grade
> metrology.

### 6. Decision Rules Are Missing From The Result Surface

JCGM 106 and ISO-style conformity practice require a decision rule because
uncertainty creates false-accept and false-reject risk.

Local consequence:

- Reports often contain measured deviation and tolerance.
- They do not consistently contain expanded uncertainty, guard band, and
  `pass/fail/indeterminate` conformity logic.

Kusari:

> If uncertainty is not in the result, the PASS is not fully auditable.

## Branch-Specific Root Causes

### BPC

Primary problem:

- The production path is feature-fusion, but some evidence still tempts people
  to talk as if global CAD registration is solved.

Why not perfect:

- Global cloud alignment has rough residuals and known degenerate alternatives.
- Tight tolerance MSA is weak.
- Feature result schema lacks explicit uncertainty and decision rule.

Hard advice:

- Keep BPC production only under frozen per-view measure-lot feature fusion.
- Add guard-banded conformity.
- Treat GICP fallback as a fault.
- Do not extend to tighter tolerance classes until MSA says yes.

### LX3

Primary problem:

- The branch has precision evidence but not part accuracy evidence.

Why not perfect:

- Marker geometry is good, but bush-vs-CAD accuracy is over tolerance.
- Turntable/axis/runout and point lift uncertainty are not fully budgeted.
- Merged CAD matching evidence is too rough to support industrial alignment.

Hard advice:

- Stop celebrating marker counts. Use them only to initialize a bush accuracy
  experiment.
- Close all six inter-bush distances against CAD nominal.
- If max error stays above 1mm, mark the current route NO-GO and change datum or
  hardware.

### SX3i

Primary problem:

- Detection recovery is being confused with dimensional progress.

Why not perfect:

- C1 is visible, but C2 assembly is not closed.
- C3 feature-coincidence target is missed by two orders of magnitude in the
  markerless route.
- The hardware/noise floor may not support sub-0.1mm without multi-view
  averaging or a different sensor strategy.

Hard advice:

- No sub-0.1mm language except as an open target.
- Close C2 before touching C3 claims.
- If C3 stays above 0.15mm p95, lower the claim or change hardware.

### OMD

Primary problem:

- There is no object to judge.

Hard advice:

- No source, no claim.

## PROM Corrections

1. Split all result records into three surfaces:
   - `registration_metrics`
   - `feature_measurements`
   - `conformity_decisions`
2. Require these fields for production adoption:
   - `datum_frame`
   - `cad_nominal`
   - `measured_value`
   - `deviation`
   - `tolerance`
   - `uncertainty`
   - `decision_rule`
   - `gauge`
   - `independent_truth`
   - `negative_controls`
3. Add `indeterminate` as a first-class state.
4. Generate PROM maps from structured records only.
5. Keep rejected branches visible as negative controls.

## Source Anchors

- Degeneracy-aware registration: https://arxiv.org/html/2408.11809v2
- NIST structured-light scanner error sources:
  https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=927473
- Point-cloud task-specific uncertainty:
  https://www.mdpi.com/2673-8244/2/4/24
- JCGM 106 conformity and decision risk:
  https://www.bipm.org/documents/20126/2071204/JCGM_106_2012_E.pdf
- JCGM 100/GUM:
  https://www.bipm.org/documents/20126/2071204/JCGM_100_2008_E.pdf
- Gage R&R / MSA overview:
  https://sixsigmastudyguide.com/gage-repeatability-and-reproducibility-rr/

For review-ready claim-level comments, see
`docs/LONGINUS_KUSARI_COMMENTARY_20260624.md`.

## Implementation (2026-06-25) — checklist is now rerunnable

The root-cause checklist is implemented as an executable, fail-closed linter:

- `lakatos/verdict/kusari.py` → `lint_critique(item)` / `lint_checklist(items)` return a `KusariVerdict`:
  - **invalid** unless every critique item carries `target_artifact`, `failure_mode`,
    `expected_observable`, and `blocking_verdict`;
  - `blocking_verdict` must be a **blocking-class** verdict (a passing verdict cannot stand as a
    critique);
  - the critique must name the exact target under attack — at least one of `coordinate_frame`,
    `datum`, `algorithm`, `feature`, `threshold` (else `target_specificity` fails = vague LabelRot
    critique blocked);
  - `lint_checklist` is fail-closed on an empty list ("zero items is not verification").
- Rerunnable acceptance check: `python -m pytest tests/test_root_cause_kusari_gate.py -q` (22 tests).
- This PIERCES Longinus binding `BPC.RootCauseKusariChecklist`
  (`docs/longinus_prom_review_bindings_20260624.json`).
- Frontier (deferred): wiring the gate into the critique-producing surface (mcp critique tool / review
  pipeline) so vague critiques cannot be emitted at all.
