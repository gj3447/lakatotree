# Longinus Industrial Dimension Judgement

Date: 2026-06-24

This is the hard industrial metrology judgement for the current 3D programmes.
It is intentionally stricter than research-progress appraisal.

Longinus rule:

> Do not call a branch production-accurate because the tree looks progressive.
> Production dimensional judgement requires CAD/CMM/independent-feature
> accuracy, tolerance, uncertainty, decision rule, gauge capability, replay, and
> negative controls.

## Judgement Scale

| Verdict | Meaning |
|---|---|
| PASS-PRODUCTION-CANDIDATE | dimension result can be considered for production after formal PPAP/MSA review |
| CONDITIONAL | useful, but only inside stated tolerance/class/guardrail |
| RESEARCH-ONLY | scientifically useful, not a production dimensional claim |
| NO-GO | do not use for industrial dimensional judgement |
| BLOCKED | missing source/data/interface/test contract |

## Branch Verdicts

| Branch | Industrial Verdict | Reason |
|---|---|---|
| BPC | CONDITIONAL | strong feature-level report, but uncertainty/MSA conflicts block blanket industrial release |
| LX3 | NO-GO for production accuracy; RESEARCH-ONLY for precision | ArUco/turntable precision exists, but CAD bush accuracy is not closed and some evidence is over tolerance |
| SX3i | NO-GO for industrial dimensions | C1 marker detection is not C2/C3 dimensional accuracy; markerless C3 is refuted/blocked |
| OMD | BLOCKED | no source/interface/test contract |

## BPC Industrial Dimension Judgement

Evidence reviewed:

- `BPC_ICP_SPEC/evidence/production_inspection_report_182_HONEST_V6.json`
- `BPC_ICP_SPEC/evidence/tolerance_policy_summary.json`
- `BPC_ICP_SPEC/evidence/aiag_rr_simulation_summary.json`
- `BPC_ICP_SPEC/evidence/noise_floor_summary.json`
- `BPC_ICP_SPEC/evidence/iter_post_pause_124_gum_type_b_subcomponent_decomp_summary.json`
- `BPC_ICP_SPEC/evidence/summary_v5.json`
- `BPC_ICP_SPEC/evidence/mac_production_verify_result.json`
- `BPC_ICP_SPEC/evidence/bpc_reg_verify_20260623.json`

Feature result:

| Group | Tol mm | n | p50 dev mm | p95 dev mm | max dev mm | Observed Verdict |
|---|---:|---:|---:|---:|---:|---|
| plate_standard | 0.8 | 33 | 0.331 | 0.495 | 0.629 | pass |
| bush_clean | 1.5 | 52 | 0.419 | 1.058 | 1.239 | pass |
| bush_panel_hole | 0.8 | 6 | 0.397 | 0.457 | 0.459 | pass |
| bush_large_ring | 1.5 | 2 | 0.182 | 0.236 | 0.242 | pass |
| washer_screw | 0.8 | 80 | 0.303 | 0.659 | 0.745 | pass |
| big_circles | 0.8 | 10 | 0.326 | 0.775 | 1.012 | 1 fail: `BIG_09` |

Good:

- 183 inspected, 182 pass, 1 fail, 0 not detected.
- Feature deviations against CAD are mostly below group tolerances.
- BPC has a real production-adjacent path: frozen per-view transforms plus
  measure-lot feature fusion.
- Negative evidence is preserved: free global ICP and per-view 6-DOF refinement
  are known collapse paths, not hidden failures.

Longinus cut:

- Do not hide the MSA conflict. `production_inspection_report_182_HONEST_V6`
  looks good, but `aiag_rr_simulation_summary` says repeatability is not
  acceptable for tight tolerances:
  - `sigma_repeat_xy_mm = 0.644`
  - `p95_sigma_per_hole_mm = 0.840`
  - AIAG matrix reports unacceptable even at 1.5mm when using repeatability
    sigma, and the separate tolerance policy only becomes acceptable around
    1.5mm after the SW3 interpretation.
- Do not sell `±0.8mm` as clean production capability without a decision rule.
  `tol=0.8` is still borderline/failing depending on which uncertainty model is
  used.
- Do not confuse feature-pass count with measurement-system capability.
  A part can pass a report while the gauge is too weak to make near-limit calls
  defensibly.
- The CAD alignment evidence is mixed:
  - `summary_v5`: scan-to-CAD p50 4.008mm, p95 7.993mm.
  - `mac_production_verify_result`: post-MAC p50 1.400mm, sigma 2.236mm.
  - `bpc_reg_verify_20260623`: some frames have ICP fitness 0.0 and centroid
    outside CAD bounds.
  These numbers are not feature-level CAD deviations. They say global cloud
  alignment is not the production truth path. The feature-fusion path is.

BPC verdict:

- `CONDITIONAL` for current production-style feature inspection.
- Production claims should be limited to the feature classes and tolerance
  bands already demonstrated.
- Require explicit `uncertainty_mm`, `decision_rule`, and `gauge_class` on every
  production result before calling this industrially complete.

Required BPC action:

1. Split report verdict into:
   - `measured_value`
   - `cad_nominal`
   - `deviation`
   - `tolerance`
   - `uncertainty`
   - `guard_band`
   - `decision_rule`
   - `conformity_state`: pass/fail/indeterminate
2. Near-limit calls must become `indeterminate` if `abs(tolerance - deviation)`
   is smaller than the expanded uncertainty.
3. Treat free GICP fallback as an alarm, not an alternate production path.

## LX3 Industrial Dimension Judgement

Evidence reviewed:

- `LX3_ICP_SPEC/evidence/lx3_aruco_50mm_independent_verify_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_aruco_register_precision_knownaxis_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_bush_nominal_lx3local_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_bush_accuracy_20260623.json`
- `LX3_ICP_SPEC/evidence/lx3_bush_accuracy_quad_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_bush_accuracy_via_register_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_merged_open3d_match_20260624.json`
- `LX3_ICP_SPEC/evidence/lx3_merged_halcon_match_20260624.json`

Good:

- Marker detection and 50mm marker geometry are real:
  - 121 views
  - 2,088 detections
  - 17.3 markers/view
  - 50.0mm side median by plane raycast
  - within-id sigma 0.37mm to 0.96mm depending on method
- Known-axis precision is real research progress:
  - 59 physical tracks
  - 2,017 points
  - RMS median 0.993mm
  - RMS p95 2.36mm
  - wrong-axis negative control: 64.3mm
- CAD nominal ruler is coherent:
  - rigid distance preservation max error 0.0mm
  - FRT pair vs measured nominal error 0.7mm

Longinus cut:

- Precision is not accuracy. The current good LX3 numbers mostly prove marker
  geometry and turntable self-consistency.
- CAD bush accuracy is not closed:
  - `lx3_bush_accuracy_20260623`: FRT pair measured 1090.957mm vs nominal
    1093.3mm, error -2.343mm, over ±1.0mm tolerance.
  - repeatability std 0.193mm is not enough; repeatable wrong is still wrong.
  - flat patch plane RMS 5.4mm is ugly for accuracy claims.
  - `lx3_bush_accuracy_quad_20260624`: best quad subset max error 155mm,
    `within_1mm=false`, `within_5mm=false`.
- Global CAD matching is not production-ready:
  - Open3D FGR/ICP residual medians are 847mm and 1783mm in reviewed evidence.
  - HALCON match residual median is 191.765mm, mean 522.66mm, inlier RMSE
    6.297mm.
  Those are diagnostics, not an industrial CAD alignment.

LX3 verdict:

- `RESEARCH-ONLY` for ArUco/turntable precision.
- `NO-GO` for production dimensional accuracy today.
- Keep status `pending-port`; do not promote to production until bush-vs-CAD
  independent accuracy closes within the declared tolerance and uncertainty.

Required LX3 action:

1. Use known-axis ArUco pose only as an initial/replayable alignment.
2. Extract four bush centers from the registered part cloud.
3. Compare all six inter-bush distances to `lx3_bush_nominal_lx3local`.
4. Record:
   - mean/max distance error
   - per-bush center uncertainty
   - runout contribution
   - decision rule
   - wrong-axis and shuffled-correspondence negative controls
5. If max error stays above 1.0mm, stop chasing software polish and mark the
   branch `NO-GO for ±1mm`.

## SX3i Industrial Dimension Judgement

Evidence reviewed:

- `SX3i_ICP_SPEC/evidence/c1_marker_detect_full211_20260624.json`
- `SX3i_ICP_SPEC/evidence/cad_register_20260624.json`
- `SX3i_ICP_SPEC/evidence/markerless_c3_real_20260624.json`
- `SX3i_ICP_SPEC/evidence/markerless_c3_directpair_20260624.json`

Good:

- C1 detection is real:
  - 211 views
  - 170 views with marker
  - 126 views with at least two markers
  - 1,650 total markers
  - side pixel median 89.6px
- CAD registration has a partial research result:
  - 9 views
  - 9 segmented
  - merged fine RMSE 1.06mm

Longinus cut:

- C1 detection is not dimensional metrology. It proves markers are visible. It
  does not prove C2 assembly, C3 feature coincidence, or sub-0.1mm accuracy.
- The actual C3 markerless evidence is a hard failure against the stated band:
  - required median <= 0.1mm and p95 <= 0.15mm
  - observed pairwise view-vs-CAD median 13.1754mm
  - observed p95 21.3771mm
  - verdict REFUTED/BLOCKED
  That is not near miss. That is two orders of magnitude off the target.
- `merged_fine_rmse_mm = 1.06` is not a sub-0.1mm dimensional claim. It is a
  coarse registration number.

SX3i verdict:

- `NO-GO` for industrial dimensional judgement.
- `RESEARCH-ONLY` for marker detection and reader provenance correction.

Required SX3i action:

1. Do not mention sub-0.1mm except as an open target.
2. Close C2 connected assembly first.
3. Re-run C3 independent feature coincidence from registered features, not from
   marker self-consistency.
4. If C3 remains above 0.1/0.15mm, change the target or change the hardware.

## OMD Industrial Dimension Judgement

Evidence reviewed:

- No source/interface/test contract found in the current PROM board.

Verdict:

- `BLOCKED`.

Longinus cut:

- No claim is allowed. No status beyond blocked should be generated.

## Cross-Programme Alignment Comments

1. Global CAD-cloud residual is not the same thing as feature-level conformance.
   BPC proves this: global cloud metrics can look rough while a constrained
   feature-fusion path is the only defensible production path.
2. Marker repeatability is not part accuracy. LX3 proves this: the ArUco system
   can be repeatable while bush-vs-CAD accuracy remains open or failed.
3. Detection is not metrology. SX3i proves this: marker visibility is useful,
   but C3 is still refuted/blocked.
4. Do not let a dashboard turn red numbers into green prose. If a branch has
   `within_1mm=false`, `REFUTED`, `BLOCKED`, or p95 100x over target, the tree
   must say that plainly.
5. Industrial release needs `indeterminate`. Binary pass/fail without
   uncertainty is not enough near tolerance.

## Longinus Comments To Attach

### LGN-BPC-001

`BPC` may remain the production candidate only under a guarded feature-fusion
interpretation. It must not claim that free global CAD registration is solved.
Add uncertainty and decision-rule fields before expanding tighter tolerance
claims.

### LGN-BPC-002

The 182/183 pass report is not the whole truth. The MSA evidence says tight
tolerance decisions are weak. Near-limit features need guard-banded
`indeterminate`, not confident PASS.

### LGN-LX3-001

`LX3` has credible precision progress, not production accuracy. The branch
stays `pending-port` until bush-vs-CAD accuracy closes. The -2.343mm FRT error
and 155mm quad failure are not footnotes; they are blockers.

### LGN-LX3-002

The Open3D/HALCON merged CAD alignment residuals are too large for an industrial
alignment claim. Use them as diagnostics only.

### LGN-SX3I-001

`SX3i` C1 is a reader/detection recovery, not a dimensional result. C2/C3 remain
the gates. The 13.1754mm median vs 0.1mm target is a hard NO-GO for current C3.

### LGN-OMD-001

`OMD` has no claim rights until an interface, source, or test contract exists.

## Required Promotion Gate Patch

No branch should become `adopted` unless every production result carries:

```json
{
  "measurand": "feature or GD&T characteristic",
  "cad_nominal": {"value": 0.0, "unit": "mm"},
  "measured": {"value": 0.0, "unit": "mm"},
  "deviation": {"value": 0.0, "unit": "mm"},
  "tolerance": {"lower": null, "upper": 0.0, "unit": "mm"},
  "uncertainty": {"u_c": 0.0, "U_k2": 0.0, "method": "GUM|MSA|repeatability"},
  "decision_rule": "guard_band|shared_risk|customer_defined",
  "conformity_state": "pass|fail|indeterminate",
  "gauge": {"rr_percent_tolerance": 0.0, "status": "acceptable|borderline|unacceptable"},
  "independent_truth": "CMM|CAD_nominal|calibrated_artifact|cross_camera|feature_coincidence",
  "negative_controls": ["wrong_axis", "free_icp", "missing_marker"]
}
```

If any of these fields is missing, the branch may be progressive, but not
industrial-production-adopted.

For the root-cause critique behind these gates, see
`docs/LONGINUS_ROOT_CAUSE_KUSARI_20260624.md`.
