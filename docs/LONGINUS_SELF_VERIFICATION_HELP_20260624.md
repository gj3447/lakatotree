# Longinus Self-Verification Help

Date: 2026-06-24

Purpose: keep every 3D PROM claim sharp. This is the reviewer help sheet for
agents and humans so nobody hides behind vague words like "good alignment",
"accurate", "robust", or "production-ready".

## Prime Directive

Do not summarize a measurement claim before splitting it into:

1. registration
2. surface/layer selection
3. feature measurement
4. conformity decision

If these four are mixed, the claim is rejected.

## Forbidden Vague Claims

| Vague Claim | Required Replacement |
|---|---|
| registration is good | state metric: RMSE, p95, fitness, degeneracy, negative control |
| CAD aligned | state datum frame, transform, residual, independent feature check |
| accurate | state independent truth: CAD nominal, CMM, artifact, cross-camera |
| precise | state repeatability: sigma, p95, n, confidence |
| robust | state perturbation sweep and failure envelope |
| production-ready | state tests, uncertainty, decision rule, gauge/MSA, replay |
| PASS | state deviation, tolerance, U_k2, guard band, conformity rule |
| sub-0.1mm | state measurand, p50/p95, n, uncertainty, gauge, negative controls |
| solved | state branch status and receipts; otherwise say "partial" |

## Self-Verification Questions

Ask these before writing any green sentence:

1. What is the exact measurand?
2. Which datum frame owns the value?
3. Which CAD layer or feature is intended?
4. What value was measured?
5. What is the CAD/CMM/independent nominal?
6. What is the deviation?
7. What is the tolerance?
8. What is the uncertainty?
9. What decision rule was used?
10. What is the gauge/MSA state?
11. What negative control failed as expected?
12. Can the result be replayed from raw inputs?
13. Is this registration, measurement, or conformity?
14. What would falsify this claim?

If any answer is missing, downgrade the claim.

## Green Claim Contract

A production green claim must include:

```json
{
  "claim_type": "registration|surface_layer|feature_measurement|conformity",
  "programme": "bpc|lx3|consumer_d|omd",
  "branch": "branch_id",
  "measurand": "specific feature or GD&T characteristic",
  "datum_frame": "cad_drf|fixture|view|unknown",
  "cad_nominal": {"value": 0.0, "unit": "mm", "source": "path"},
  "measured": {"value": 0.0, "unit": "mm", "source": "path"},
  "deviation": {"value": 0.0, "unit": "mm"},
  "tolerance": {"lower": null, "upper": 0.0, "unit": "mm"},
  "uncertainty": {"u_c": 0.0, "U_k2": 0.0, "method": "GUM|MSA|repeatability"},
  "decision_rule": "guard_band|shared_risk|customer_defined",
  "conformity_state": "pass|fail|indeterminate",
  "gauge": {"status": "acceptable|borderline|unacceptable", "rr_percent_tolerance": 0.0},
  "negative_controls": ["wrong_axis", "wrong_layer", "free_icp", "missing_marker"],
  "replay": {"command": "exact command", "inputs": [], "outputs": []}
}
```

No schema, no green.

## Branch-Specific Help

### consumer_b

Good wording:

- "consumer_b feature-fusion path is conditionally viable for demonstrated feature
  classes under frozen per-view measure-lot."

Bad wording:

- "consumer_b CAD registration is solved."
- "consumer_b Z is aligned."
- "182/183 pass means production-grade."

Self-check:

- Did the claim use frozen per-view feature fusion, or did it accidentally use
  free GICP?
- Is the intended CAD layer named?
- Are Z signed errors and surface layer ambiguity visible?
- Is uncertainty smaller than the margin to tolerance?
- If not, is the result `indeterminate`?

Longinus help:

> consumer_b can be a production candidate only when feature-fusion is the named path.
> Global cloud alignment is diagnostic. It is not the production truth.

### consumer_c

Good wording:

- "consumer_c has precision progress through known-axis ArUco; production accuracy is
  still open."

Bad wording:

- "consumer_c is accurate because marker registration repeats."
- "Marker count proves measurement."
- "CAD match looks good."

Self-check:

- Did the result compare actual bush features against CAD nominal?
- Are all six inter-bush distances reported?
- Is max error within tolerance after uncertainty?
- Did wrong-axis or shuffled-correspondence controls fail?

Longinus help:

> consumer_c is not production-accurate until bush-vs-CAD closes. Marker precision is
> an enabler, not a verdict.

### SX3i

Good wording:

- "SX3i recovered C1 marker detection; C2/C3 dimensional gates remain open."

Bad wording:

- "SX3i is near sub-0.1mm."
- "C1 proves metrology."
- "Markerless C3 just needs tuning."

Self-check:

- Is C2 connected assembly closed?
- Is C3 feature coincidence measured independently?
- Are median and p95 inside the 0.1/0.15mm band?
- If observed error is in millimeters, is the route preserved as negative
  evidence instead of polished?

Longinus help:

> C1 is visibility. C3 is metrology. Do not confuse the door with the room.

### OMD

Good wording:

- "OMD is blocked pending source/interface/test contract."

Bad wording:

- Any measurement claim.

Self-check:

- Is there a source file?
- Is there an interface contract?
- Is there a test fixture?

Longinus help:

> No artifact, no claim.

## consumer_b Z-Layer Special Warning

For consumer_b Z/height:

- Same XY does not mean same feature.
- Nearest CAD triangle does not mean intended CAD surface.
- A broad panel can make ICP residual look good while washer/boss/cup height is
  wrong.
- A Z-frame winner is not a Z-height certificate.

Required fields:

- `intended_cad_layer`
- `candidate_layers`
- `selected_layer`
- `layer_selection_rule`
- `z_signed_error_mm`
- `wrong_layer_control`

Longinus help:

> If a result says "Z aligned" but cannot name the selected CAD layer, reject it.

## Review Macros

Use these as review comments.

### Macro: Split The Claim

This claim mixes registration, measurement, and conformity. Split it into
separate metrics before marking it green.

### Macro: Name The Truth

"Accuracy" is not allowed without independent truth. Name the truth source:
CAD nominal, CMM, calibrated artifact, cross-camera, or feature coincidence.

### Macro: Add Uncertainty

Deviation and tolerance are not enough. Add `U_k2` and a decision rule, or
downgrade PASS to unreviewed.

### Macro: Wrong Metric

The metric shown is a solver metric. It does not prove the feature measurand.
Add an independent feature measurement.

### Macro: Near-Limit

The result is near tolerance. Use guard-banding and allow `indeterminate`.

### Macro: Detection Only

This is detection evidence. It may open a branch, but it cannot close a
dimensional claim.

### Macro: Negative Control Missing

No negative control is attached. Run wrong-axis/wrong-layer/free-ICP/missing
marker control before promotion.

## Daily PROM Discipline

At the start of every 3D measurement session:

1. Register the claim.
2. Register the kill criterion.
3. Record raw input paths.
4. Record command and code version.
5. Record datum frame.
6. Record expected CAD layer.
7. Run the real measurement.
8. Run the negative control.
9. Emit structured record.
10. Let the judge decide; do not hand-write a verdict.

At the end:

- Update branch status only from structured records.
- Preserve rejected branches.
- Put missing evidence into frontier, not into prose.

## Final Reminder

The enemy is not a red result. The enemy is a vague green result.

Red results teach the tree. Vague green results corrupt it.
