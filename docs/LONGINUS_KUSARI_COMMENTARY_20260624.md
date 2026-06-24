# Longinus Kusari Commentary

Date: 2026-06-24

Purpose: aggressive but useful critique for the current 3D PROM/LakatoTree
industrial metrology work.

Tone rule:

> This is not blame. This is claim hygiene. Every green claim must survive
> datum, uncertainty, gauge, replay, and negative-control pressure.

## Global Kusari

### KSR-0001 — Stop Saying "Accurate" Without Naming Truth

Problem:

- Several branches use words like accuracy, alignment, registration, and
  production in ways that are too close together.

Kusari:

- Accurate against what?
  - CAD nominal?
  - CMM?
  - calibrated artifact?
  - cross-camera feature coincidence?
  - marker board geometry?
  - ICP self-consistency?
- If the answer is not explicit, the word "accuracy" is banned.

Required replacement:

- Say `registration repeatability`, `marker geometry repeatability`,
  `feature-vs-CAD error`, or `conformity decision`.

### KSR-0002 — ICP Residual Is Not A Part Verdict

Problem:

- ICP/FGR/HALCON residuals are being treated as if they can imply dimensional
  correctness.

Kusari:

- ICP residual tells you how well a solver minimized its own correspondence
  model. It does not tell you whether a bush, hole, washer, datum, or GD&T
  characteristic conforms.
- If the correspondences are wrong, symmetric, low-overlap, or datum-ambiguous,
  the residual can be a polished lie.

Required gate:

- Every ICP metric must be paired with at least one independent feature metric.

### KSR-0003 — Detection Is Not Metrology

Problem:

- Marker/segmentation detection wins are sometimes written as if they close
  measurement.

Kusari:

- A detector can find a thing. A metrology chain measures a characteristic with
  a datum, uncertainty, and decision rule.
- C1/C2 detection progress may open the door. It does not close the room.

Required gate:

- Detection branch may become `progressive`; it may not become `adopted`
  without feature measurement and conformity receipts.

### KSR-0004 — No More Binary PASS Near Tolerance

Problem:

- Current production-style reports tend to emit PASS/FAIL using deviation <
  tolerance.

Kusari:

- If uncertainty is comparable to margin, binary PASS is not honest.
- Near-limit parts need `indeterminate` or guard-banded decisions.

Required gate:

```text
margin_mm = tolerance_mm - abs(deviation_mm)
if margin_mm <= U_k2_mm:
    conformity_state = "indeterminate"
```

### KSR-0005 — Green Counts Do Not Cancel Red MSA

Problem:

- BPC has a good 182/183 feature pass report, but MSA/uncertainty evidence is
  weaker for tight tolerances.

Kusari:

- Pass count is sample outcome. MSA is measurement-system capability.
- A weak gauge can generate a pretty pass table and still be unfit for
  production decisions near spec limits.

Required gate:

- Report both:
  - part result
  - measurement-system status
- If they disagree, the UI and tree must surface the disagreement.

## BPC Kusari

### KSR-BPC-001 — The Production Path Is Feature Fusion, Not Free CAD ICP

Claim to block:

- "BPC CAD registration is solved."

Kusari:

- Too vague. Free global CAD/cloud registration is not solved. The defensible
  path is frozen per-view transform plus measure-lot feature fusion.
- Evidence already shows free/6-DOF/GICP-style paths can collapse.

Allowed claim:

- "BPC feature inspection is conditionally viable through the frozen per-view
  measure-lot path for demonstrated feature classes."

Required receipt:

- `register_backend = frozen_per_view_measure_lot`
- `gicp_fallback = false`
- `feature_measurements[]`
- `uncertainty`
- `decision_rule`

### KSR-BPC-002 — 182/183 PASS Is Not A PPAP Stamp

Claim to block:

- "BPC is production-grade because 182 of 183 passed."

Kusari:

- That is outcome evidence, not full measurement capability.
- `sigma_repeat_xy_mm = 0.644` and `p95_sigma_per_hole_mm = 0.840` put tight
  tolerance claims under pressure.
- `BIG_09` already fails at 1.012mm against 0.8mm. Near-limit logic matters.

Allowed claim:

- "BPC has strong conditional feature-level evidence; tight tolerances require
  guard-banded conformity and MSA review."

### KSR-BPC-003 — CAD Mesh Distance Is A Diagnostic, Not The Verdict

Claim to block:

- "scan-to-CAD p50/p95 proves BPC measurement accuracy."

Kusari:

- Global scan-to-CAD distance mixes occlusion, mesh sampling, view coverage,
  surface selection, datum choice, and solver residual.
- It can diagnose a route. It cannot replace per-feature conformance.

Required action:

- Keep global cloud metrics in `registration_metrics`.
- Keep feature deviations in `feature_measurements`.
- Keep PASS/FAIL/INDETERMINATE in `conformity_decisions`.

## LX3 Kusari

### KSR-LX3-001 — ArUco Precision Is Not Bush Accuracy

Claim to block:

- "LX3 is accurate because ArUco/turntable precision is good."

Kusari:

- Known-axis ArUco RMS median 0.993mm is useful. It is not a part accuracy
  verdict.
- The bush-vs-CAD evidence has an over-tolerance result: -2.343mm against
  ±1.0mm.
- Quad evidence with max error 155mm is a blocker, not a footnote.

Allowed claim:

- "LX3 has precision-progress and a CAD nominal ruler, but production accuracy
  remains open/failed until independent bush features close."

### KSR-LX3-002 — Do Not Celebrate Marker Counts Past The Enabler Gate

Claim to block:

- "121 views / 2088 detections means the branch is basically solved."

Kusari:

- Marker detection closed the enabler question. It did not close the measurement
  question.
- After marker visibility is established, additional marker-count celebration is
  low-value. The next unit of progress is bush error in mm.

Required action:

- Convert marker pose into part feature measurements.
- Report all six inter-bush CAD distance errors.
- Fail the branch if max error exceeds tolerance after uncertainty.

### KSR-LX3-003 — Merged CAD Match Evidence Is Not Production Alignment

Claim to block:

- "Open3D/HALCON merged CAD alignment validates LX3."

Kusari:

- Reviewed merged-match numbers are too rough:
  - Open3D residual medians in hundreds/thousands of mm.
  - HALCON residual median around 191mm in reviewed evidence.
- That is a diagnostic saying "this route is not the production datum."

Required action:

- Keep these as negative/diagnostic receipts.
- Do not use them as green evidence.

## SX3i Kusari

### KSR-SX3I-001 — C1 Is Not C3

Claim to block:

- "SX3i is close because marker detection recovered."

Kusari:

- C1 proves readable markers. C3 proves independent feature coincidence.
- The target is not "markers visible"; the target is dimensional repeatability
  and accuracy under 0.1/0.15mm bands.

Allowed claim:

- "SX3i recovered C1 detection and reader provenance; dimensional metrology is
  still research-only."

### KSR-SX3I-002 — 13mm Against 0.1mm Is Not A Tuning Gap

Claim to block:

- "markerless C3 just needs some tuning."

Kusari:

- C3 markerless evidence says:
  - target median <= 0.1mm
  - target p95 <= 0.15mm
  - observed median 13.1754mm
  - observed p95 21.3771mm
- That is not "almost." That is a route failure by two orders of magnitude.

Required action:

- Preserve as negative evidence.
- Do not spend more time polishing this route unless a new datum/feature
  hypothesis is preregistered.

### KSR-SX3I-003 — Sub-0.1mm Language Must Be Locked

Claim to block:

- "SX3i sub-0.1mm path."

Kusari:

- Until C2 connected assembly and C3 feature coincidence close, that phrase must
  be written only as `open target`, never as capability.

Required wording:

- "SX3i open target: sub-0.1mm feature coincidence after C2/C3."

## OMD Kusari

### KSR-OMD-001 — No Object, No Claim

Claim to block:

- Any OMD measurement claim.

Kusari:

- There is no source/interface/test contract. A blocked branch has no
  measurement rights.

Required action:

- First artifact must be one of:
  - source file
  - interface contract
  - test fixture
  - evidence record

## Promotion Ban List

These phrases should fail review unless backed by the required receipt:

| Phrase | Required Receipt |
|---|---|
| production accurate | independent feature/CAD or CMM accuracy + uncertainty |
| sub-0.1mm | C3 or equivalent feature metric with p50/p95 and MSA |
| CAD aligned | datum frame + transform + residual + independent feature check |
| PASS | tolerance + uncertainty + decision rule |
| solved | replay receipt + negative controls + branch status |
| robust | perturbation sweep + failure envelope |
| precision | repeated measurements with sigma/p95 |
| accuracy | comparison to independent truth |

## Required Review Questions

Ask these before accepting any green node:

1. What exactly is the measurand?
2. What datum frame owns the value?
3. What is the CAD/CMM/independent nominal?
4. What is the measured value?
5. What is the deviation?
6. What is the tolerance?
7. What is the uncertainty?
8. What decision rule converts value to conformity?
9. What is the gauge/MSA status?
10. What negative control failed in the expected direction?
11. Can the result be replayed from raw inputs?
12. Is this registration, measurement, or conformity?

If answer 12 is unclear, reject the claim.

## Immediate Patch Demands

1. Add `conformity_state = pass|fail|indeterminate`.
2. Add `U_k2_mm` and `decision_rule` to production feature output.
3. Block `adopted` status if gauge/MSA is absent.
4. Block `accuracy` wording if `independent_truth` is absent.
5. Split dashboards into:
   - registration health
   - feature measurement
   - conformity decision
6. Keep every failed route visible as a negative-control branch.

## Final Kusari

The tree is useful because it remembers failures. Do not ruin that by turning
research progress into production claims too early.

The next win is not another clever registration trick. The next win is a result
surface that says:

```text
measured = x
nominal = y
deviation = z
tolerance = t
uncertainty = U
decision_rule = r
conformity = pass/fail/indeterminate
negative_controls = passed
replay = available
```

Until then, the honest status is:

- BPC: conditional production candidate.
- LX3: precision-progress, accuracy NO-GO.
- SX3i: detection-progress, dimensional NO-GO.
- OMD: blocked.

For the specific BPC Z-height / CAD surface layer failure mode, see
`docs/BPC_Z_HEIGHT_CAD_SURFACE_PROM_20260624.md`.

For the day-to-day self-verification help sheet and reusable review macros, see
`docs/LONGINUS_SELF_VERIFICATION_HELP_20260624.md`.
