# LX3 Next Action Board

Date: 2026-06-25

## Current Position

LX3 is no longer in the old "geometry collapse" state.

The current LakatoTree reading is:

- Precision recovered: `selfconsist_rms_after_bugfix_mm = 0.993`.
- Jig removal improved: final CAD-distance crop preserves the LX3 body much
  better than the earlier honeycomb crop.
- Best crop band from visual sweep: `D=25..40mm`; `D=12mm` is too destructive,
  `D=70mm` leaks jig/fixture.
- CMM reference exists for five specimens.
- CMM truth tables are exported:
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_cmm_truth_table_20260625.json`
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_cmm_feature_axis_truth_20260625.csv`
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_cmm_pair_distance_truth_20260625.csv`
- First scan-minus-CMM residual is exported:
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_scan_minus_cmm_residuals_20260625.json`
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_scan_minus_cmm_pair_distance_20260625.csv`
- Pair-only CMM sweep is exported:
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_pair_sweep_scan_measurements_20260625.json`
  - `/data/kjra/PROJECT/3D/LX3_ICP_SPEC/evidence/lx3_pair_sweep_scan_measurements_20260625.csv`
- Lakato engine node is wired:
  - `examples/lx3_engine_judged.py`: `lx3_pair_only_cmm_sweep`
  - engine verdict: `rejected`
- Mounting-bush CMM comparison is promising: four mounting-bush distances are
  within `0.63mm` of CMM in the latest visual report.
- Global CAD accuracy is still not closed: prior CAD-vs-part registration
  median is recorded as `21mm`.

This means:

> LX3 part isolation and precision are back. Production accuracy must now be
> closed through feature residuals, not global CAD RMSE.

## Closed / Recovered

| Item | Status | Evidence |
|---|---|---|
| ArUco reader/dictionary confusion | recovered | `lx3_aruco_dict4x4_20260624.json` |
| Known-angle registration precision | recovered | `lx3_occam_precision_recovered_20260624.json` |
| 360-merge smear as root cause | downgraded to avoidable bad path | `LX3_360MERGE_CADNOMINAL_FINDINGS_20260624.md` |
| Jig removal visual quality | improved | `output/images/lx3/lx3_PART_jigremoved_FINAL_8views.png` |
| Crop band sanity | improved | `output/images/lx3/lx3_jig_crop_Dcompare.png` |
| CMM reference availability | unblocked | `lx3_cmm_reference_20260624.json` |
| CMM truth table export | done | `lx3_cmm_truth_table_20260625.json`, `lx3_cmm_feature_axis_truth_20260625.csv`, `lx3_cmm_pair_distance_truth_20260625.csv` |
| A/C/D pair-only scan-minus-CMM sweep | done / falsifies current pair estimator | `lx3_scan_minus_cmm_residuals_20260625.json`: 5 CMM specimens, 4 pair NG |
| Lakato engine registration | done | `lx3_pair_only_cmm_sweep` judges `rejected`; `pytest tests/test_lx3_engine_judged.py -q` passes |

## Still Open

| Frontier | Why Open | Close Condition |
|---|---|---|
| `q_lx3_external_trueness` | scan/CMM comparison is not yet a replayable metric record | feature-by-feature scan residuals vs matched CMM specimen |
| `q_lx3_aruco_accuracy` | precision is recovered, but CAD/global accuracy was 21mm | bush/bolt/hole feature residuals pass tolerance |
| `q_lx3_part_jig_separation_non_circular` | CAD-distance crop can be circular if used as proof | non-CAD or two-stage crop reproduces feature residuals |
| `q_lx3_datum_bush_faces` | face-aware method is synthetic-valid, real extraction still data-bound | real front/back bush extraction with provenance |
| LX3 12 bolt production spec | 12 bolt nominals remain placeholders in PrismV2 | confirmed nominal/tolerance table |

## Recommended Sprint

### Sprint A — Feature Residual Truth Table

Goal: turn the good visual result into a replayable industrial measurement
record.

Current first result:

| cmm_id | scan session | measurement | scan | CMM | scan-CMM | verdict |
|---|---|---|---:|---:|---:|---|
| 127 | `LX3RT_20260622_160114` | `FRT_LH-FRT_RH` pair distance | `1090.957mm` | `1092.470226mm` | `-1.513226mm` | NG |
| 128 | `LX3RT_20260622_162343` | `FRT_LH-FRT_RH` pair distance | `1090.411mm` | `1093.098127mm` | `-2.687127mm` | NG |
| 129 | `LX3RT_20260622_164447` | `FRT_LH-FRT_RH` pair distance | `1091.293mm` | `1092.126342mm` | `-0.833342mm` | PASS |
| 130 | `LX3RT_20260622_171253` | `FRT_LH-FRT_RH` pair distance | `1090.816mm` | `1092.827629mm` | `-2.011629mm` | NG |
| 131 | `LX3RT_20260622_173509` | `FRT_LH-FRT_RH` pair distance | `1090.605mm` | `1092.723293mm` | `-2.118293mm` | NG |

Interpretation: the old single-frontal-station pair measurement is falsified as
a production trueness path. It fails 4/5 CMM-mapped specimens, with worst
absolute residual `2.687127mm`. This is not a product NG conclusion; it is an
estimator NG conclusion. Full closure now requires feature-axis scan
measurements, not pair-only distance.

Critical 130 note: CMM 130 is globally NG because `B_LH X = +1.218mm` and
`FRT_BODY_RH_BUSH Z = -1.067mm`. The measured `FRT_LH-FRT_RH` pair itself is
CMM PASS, yet scan says NG by `-2.011629mm`. This does not close the 130 NG
challenge. It proves the current pair estimator can false-reject a passing pair.

Required output:

| Field | Meaning |
|---|---|
| `lot_id` | scan/CMM specimen id |
| `feature_id` | RR/FRT/B/bolt feature id |
| `feature_class` | bush, b_point, bolt |
| `measured_xyz` | scan-derived feature center |
| `cmm_xyz` or `cad_nominal_xyz` | external reference or nominal |
| `residual_xyz_mm` | signed feature residual |
| `residual_norm_mm` | scalar residual |
| `source_view_ids` | views used for the feature |
| `measurement_method` | registration-free, CAD-ICP, face-aware, etc. |
| `frame_id` | LX3_LOCAL / CAD / camera frame |
| `datum_id` | datum construction source |
| `crop_policy` | e.g. `cad_distance_D25_then_feature_roi` |
| `quality_flags` | sparse, occluded, fallback, jig_leakage, etc. |

Acceptance:

- Mounting bushes: residuals within the agreed tolerance, initially `<=1.0mm`.
- B-points: either pass, or be explicitly marked `definition_mismatch` with a
  measured rigid offset/provenance.
- No PASS may be based on `global_rmse_mm` alone.

### Sprint B — Two-Stage Crop Contract

Goal: prevent the honeycomb crop from returning.

Use:

1. Loose CAD-distance crop: `D=25..40mm`.
2. Connected-component or fixture-color cleanup.
3. Optional CAD ICP refinement.
4. Feature-protected tight crop only inside feature ROIs.

Acceptance:

- `D=12mm` destructive crop is rejected by coverage checks.
- `D=70mm` jig-leakage crop is rejected by leakage checks.
- The chosen `D` reports:
  - part point count,
  - jig leakage estimate,
  - feature ROI coverage,
  - before/after residuals.

### Sprint C — Production Port Gate

Goal: move from research evidence into PrismV2 production without weakening the
truth standard.

Required gates:

- `assert_lx3_production_runtime_ready` passes.
- LX3 12 bolt placeholders still block production until confirmed.
- Result schema includes both:
  - `rigid_rmse_mm`
  - per-feature residuals and p95
- UI/DT must display feature residual meaning, not just an ICP score.

## Longinus

- Do not use the pretty jig-removed cloud as a PASS certificate.
- Do not use CAD-distance crop as both classifier and proof without a leakage
  audit.
- Do not call `0.993mm` precision the same thing as CMM trueness.
- Do not call the pair-only estimator production-ready after 4/5 CMM pair
  failures.
- Do not claim the 130 NG challenge from `FRT_LH-FRT_RH`; that pair is CMM
  PASS and the scan result is a false-reject warning.
- Do not let B-point definition mismatch poison the mounting-bush result.
- Do not tighten crop thresholds to hide jig; measure part loss and jig leakage.
- Do not promote LX3 while bolt nominals are placeholders.

## Immediate Command Checklist

1. Generate a feature-axis scan measurement table for the latest jig-removed
   cloud.
2. Join scan measurements against the CMM truth tables with
   `scripts/export_lx3_scan_minus_cmm_residuals.py --scan-json ...`.
3. Re-test 127/128/129/130/131 with full feature-axis residuals; the current
   pair-only method is NG in 4/5 specimens and worst miss is `2.687127mm`.
4. Re-run the crop sweep with numeric point/coverage/leakage stats.
5. Record B-point mismatch as a separate `definition_mismatch` issue.
6. Use the actual 130 NG axes as the false-accept challenge: `B_LH X` and
   `FRT_BODY_RH_BUSH Z`. Do not substitute a FRT pair distance for this test.
7. Update `examples/lx3_icp_programme.py` only after the new metric record
   exists.
