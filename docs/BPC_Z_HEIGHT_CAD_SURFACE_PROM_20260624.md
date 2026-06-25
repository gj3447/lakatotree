# BPC Z Height / CAD Surface PROM

Date: 2026-06-24

Question:

> Why did the system say registration was good even when BPC Z height looked
> wrong, the measured surface sat between/near CAD surfaces, or the scan appeared
> to be measuring the wrong surface layer?

Short answer:

> Because the metric being called "registration good" was not the same thing as
> Z-height dimensional truth. It was likely a local/gated success metric:
> feature coverage, BIG pass rate, p2plane residual, or XY feature deviation,
> while the Z-layer/datum/measurand was still ambiguous.

## The Failure Pattern

CAD-based 3D inspection has at least four distinct surfaces of truth:

1. `registration_truth`: did the scan transform into a plausible CAD frame?
2. `surface_truth`: did scan points correspond to the intended CAD surface?
3. `feature_truth`: did the extracted feature match the intended physical
   feature?
4. `conformity_truth`: does the measured characteristic conform after
   uncertainty and decision rule?

The BPC Z issue appears when a result passes layer 1 or part of layer 3, while
layer 2 and layer 4 are not actually closed.

## Local Evidence

### Dual Z-Frame Gate

`BPC_ICP_SPEC/out/dual_z_frame_gate_v1.md` shows two competing Z-frame states:

| Candidate | panel_z mm | z_frame_state | BIG /10 | PASS /183 | Verdict |
|---|---:|---|---:|---:|---|
| aruco_v3 | -208.50 | NORMAL | 10/10 | 168/183 | adopted |
| v15_xmirror | -230.30 | SHIFTED_22MM | 0/10 | 143/183 | rejected |

This gate is useful, but it is not a general Z-height proof. It says the
`aruco_v3` candidate wins according to BIG feature sensitivity and pass count.
It does not say every surface Z layer is correct.

Longinus comment:

> A Z-frame gate can choose the less-wrong frame. It does not certify every
> Z-measurand.

### Feature Z Offset Evidence

`BPC_ICP_SPEC/out/feature_z_offset_per_hole.json` contains examples where plate
features have CAD Z around `-230` to `-232` but signed distances around
`-3.3mm` to `-4.1mm` for the reviewed `v17_vgicp` surface.

This is exactly the warning sign:

- the feature can be in the expected XY neighborhood,
- the candidate can still look plausible,
- but the surface layer can be offset by several millimeters.

Longinus comment:

> If Z signed distance is multiple millimeters, do not call the dimensional
> surface correct just because XY or feature coverage looks green.

### BPC 0.1mm Consolidation

`BPC_ICP_SPEC/evidence/problem_consolidation_v2_20260603.json` records the same
root cause in measurement-stat terms:

- layer-pick systematic bias dominates per-frame floor,
- frame starvation prevents confidence,
- between-session random and systematic terms dominate,
- false optimism came from small-n point estimates and SE-vs-sigma confusion.

This directly explains why a local Z result can look repeatable or plausible
without being industrially correct.

## Why It Said "Good" Anyway

### 1. The Metric Was Probably Not Z-Height

The code/evidence often uses:

- BIG pass rate,
- total pass rate,
- p2plane residual,
- ICP RMSE,
- XY deviation to CAD feature center,
- scan-to-CAD p50/p95,
- feature detection coverage.

Those are not the same as:

- intended Z surface selected,
- washer/head/panel/boss layer separated,
- GD&T datum Z established,
- surface height conformity with uncertainty.

Kusari:

> "Good registration" must say which metric. If it does not name the measurand,
> it is not a metrology claim.

### 2. Best-Fit / ICP Can Hide A Wrong Surface

Point-to-plane ICP and surface matching can reduce residual by sliding or
tilting a cloud toward a large planar surface. If the part has broad plates and
repeated features, a wrong Z layer can still be the nearest or dominant surface
for the solver.

Kusari:

> A broad panel can outvote a washer. A solver that minimizes average residual
> can sacrifice the small feature you actually care about.

### 3. CAD Has Multiple Nearby Z Layers

BPC has plate, washer, boss, ring, cup, and counterbore-like layered geometry.
A single XY neighborhood can contain several valid CAD Z surfaces. If the
pipeline picks the densest or nearest surface without a feature-specific layer
contract, it can measure the wrong layer very consistently.

Kusari:

> Same XY does not mean same feature. Z-layer identity is a contract, not a side
> effect of nearest-neighbor lookup.

### 4. The Gate Was Optimized For Branch Selection, Not Full Conformity

`dual_z_frame_gate_v1` made a branch decision: `aruco_v3` is better than
`v15_xmirror`. That was useful. But branch selection is not final conformance.

Kusari:

> A branch winner is not a production certificate.

### 5. Repeatability Can Be A Wrong-Layer Repeatability

If the same wrong CAD layer is chosen repeatedly, sigma can look good. That is
precision, not accuracy.

Kusari:

> Repeatable layer-pick error is still layer-pick error.

## CAD-Based 3D Dimension Measurement: Correct Workflow

The industrial workflow should be:

1. Define the measurand:
   - example: washer top height, boss rim height, cup nadir, hole center XY,
     plate surface Z, counterbore depth.
2. Define datum frame:
   - 3-2-1, fixture datum, CAD DRF, or calibrated artifact.
3. Define intended CAD surface/layer:
   - not just "nearest CAD triangle."
4. Capture and register:
   - record transform, backend, residual, degeneracy score.
5. Extract feature:
   - feature-specific fitting, not global cloud distance.
6. Compare to nominal:
   - CAD nominal or CMM/calibrated truth.
7. Estimate uncertainty:
   - sensor, registration, surface fit, layer selection, calibration, repeatability.
8. Apply decision rule:
   - pass/fail/indeterminate.
9. Run negative controls:
   - wrong Z layer, wrong axis, free ICP, missing marker, shuffled feature ID,
     perturbed datum.

## Required BPC Z Guards

Add these fields to any BPC Z/height result:

```json
{
  "measurand": "washer_top_height|boss_height|plate_z|cup_nadir|...",
  "datum_frame": "cad_drf|fixture_datum|frozen_view_frame",
  "intended_cad_layer": "washer_top|panel_surface|boss_top|cup_nadir",
  "candidate_layers": [
    {"name": "panel_surface", "cad_z_mm": -232.0, "distance_mm": 3.7},
    {"name": "washer_top", "cad_z_mm": -200.2, "distance_mm": 0.4}
  ],
  "selected_layer": "washer_top",
  "layer_selection_rule": "nearest_expected_step|feature_specific_prior|manual_verified",
  "z_signed_error_mm": 0.0,
  "xy_error_mm": 0.0,
  "surface_fit_rmse_mm": 0.0,
  "registration_residual_mm": 0.0,
  "uncertainty": {"u_c_mm": 0.0, "U_k2_mm": 0.0},
  "decision_rule": "guard_band",
  "conformity_state": "pass|fail|indeterminate"
}
```

## Required Negative Controls

For BPC Z-height claims, require these before green:

| Control | Expected Result |
|---|---|
| wrong Z layer | selected-layer test must fail |
| wrong axis / mirrored frame | chirality or feature class must fail |
| free ICP fallback | must be flagged as alarm for BPC production |
| panel-only fit | should not pass washer/boss height claims |
| nearest CAD triangle only | should fail multilayer features |
| shuffled feature IDs | should fail feature-specific nominal comparison |

## Open-Source / Practical Tooling

| Tool | Use |
|---|---|
| CloudCompare | visual inspection, cloud-to-mesh distances, M3C2 signed robust distance |
| M3C2 plugin | robust signed cloud-to-cloud distances with local roughness/uncertainty style outputs |
| Open3D | scripted point cloud registration, point-to-plane ICP, distance metrics, reproducible checks |
| PCL | second implementation stack for ICP, filters, segmentation, RANSAC primitives |
| MeshLab | mesh inspection/cleanup, surface sanity checks |
| trimesh / OpenCascade / pythonocc | CAD/STL/mesh geometry parsing and feature extraction |
| DVC | raw scan and derived metric artifact versioning |

PROM tooling rule:

> Open-source tools can produce diagnostics. Production claims still need the
> local receipt schema: measurand, datum, nominal, uncertainty, decision rule,
> negative controls, and replay.

## Literature / Source Anchors

- PTB high-density 3D point-cloud good practice guide:
  auto/best-fit alignment is suitable for general inspection, while feature
  based 3-2-1 style alignment is more useful for GD&T datum tasks.
  https://www.ptb.de/emrp/fileadmin/documents/tim/GPG_optical_scanning.pdf
- Point-cloud task-specific uncertainty:
  https://www.mdpi.com/2673-8244/2/4/24
- Digital inspection of sheet metal using 3D point clouds:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12349652/
- Degeneracy-aware point-cloud registration:
  https://arxiv.org/html/2408.11809v2
- Plane-to-plane point-cloud registration:
  https://www.ipb.uni-bonn.de/pdfs/foerstner17efficient.pdf
- CloudCompare:
  https://www.cloudcompare.org/
- CloudCompare M3C2 plugin:
  https://www.cloudcompare.org/doc/wiki/index.php/M3C2_%28plugin%29
- Open3D ICP:
  https://www.open3d.org/docs/0.17.0/tutorial/t_pipelines/t_icp_registration.html

## Longinus Comments

### LGN-BPC-Z-001

Do not call BPC Z "aligned" unless the intended CAD layer is named and checked.
`panel_z` branch choice is not enough.

### LGN-BPC-Z-002

If the scan point is between CAD surfaces, nearest-surface matching is
underdefined. The result must become `indeterminate` unless a feature-specific
layer rule selects the intended surface.

### LGN-BPC-Z-003

Any Z-height metric that is green while signed CAD distance is 3-4mm must be
split: the registration metric may be green, but the Z-dimensional metric is
not green.

### LGN-BPC-Z-004

Do not let broad panel residuals vote down washer/boss/cup truth. Feature-level
measurands need feature-level extraction and feature-level uncertainty.

### LGN-BPC-Z-005

The next useful BPC Z work is not another best-fit solver. It is a layer-aware
result contract and negative controls for wrong-layer selection.

## Implementation (2026-06-25) — guard is now rerunnable

The "Required BPC Z Guards" contract is implemented as a fail-closed gate:

- `lakatos/verdict/z_height.py` → `judge_z_height(result)` returns a `ZHeightVerdict`:
  - **BLOCKED** unless the result separates *rigid residual* (`registration_residual_mm`),
    *per-feature z residual* (`z_signed_error_mm`), and *frame/sign audit* (`candidate_layers` with
    ≥2 competing layers/`z_frame_state`) — i.e. it fails when those three are collapsed.
  - **Z-NOT-CERTIFIED** (LGN-BPC-Z-003) when registration is green but
    `|z_signed_error_mm| > registration_residual_mm + U_k2_mm` — registration green cannot certify a
    wrong Z layer. `Z-INDETERMINATE` near the band; `Z-PASS-CANDIDATE` only when z is within U_k2.
- Rerunnable acceptance check: `python -m pytest tests/test_z_height_gate.py -q` (18 tests). It validates
  against the real production evidence `BPC_ICP_SPEC/out/feature_z_offset_per_hole.json`
  (plate_standard signed-z is multi-mm while registration looked green) and
  `out/dual_z_frame_gate_v1.md` (aruco_v3 NORMAL vs v15_xmirror SHIFTED_22MM); it hermetic-skips when
  that external evidence is absent (clean-clone reproducibility preserved).
- This PIERCES Longinus binding `BPC.ZHeightCadSurfaceFailureMode`.
- Still open (separate CANDIDATE binding `BPC.ZLayerNegativeControlsExecuted`): the six negative
  controls below must be *executed* with expected-fail outcomes, not just declared.
