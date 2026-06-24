# PROM Measurement Audit

Date: 2026-06-24

This audit checks whether the current 3D LakatoTree/PROM work is measuring
industrial dimensions and registration quality in a scientifically defensible
way, rather than only producing attractive prose.

## Repository Size Check

Current LakatoTree counts from the local checkout:

| Surface | Count |
|---|---:|
| `docs/*.md` files | 18 |
| `docs/*.md` total lines | 1,951 |
| `docs/` files total | 24 |
| repository files excluding `.git`, `.venv`, caches, pycache | 366 |
| Python files excluding `.git`, `.venv`, caches, pycache | 279 |
| full test suite | 1,050 passed, 11 skipped |

Assessment:

- The documentation is noticeable but not out of control.
- The risk is not raw document volume. The risk is drift between prose, dogfood
  Python nodes, evidence records, and generated maps.
- New PROM facts should move toward generated records/maps instead of more
  manually repeated prose.

## Industrial Metrology Bar

For production dimensional inspection, a branch should not be promoted by an
ICP residual or a marker repeatability number alone.

Minimum fields for an industrial measurement claim:

| Field | Why It Matters |
|---|---|
| measurand | exact feature/characteristic being measured |
| datum / frame | GD&T or CAD frame used for the value |
| value and unit | measured value in mm/deg/etc. |
| tolerance | upper/lower limit or bilateral tolerance |
| uncertainty | standard or expanded uncertainty, with method |
| decision rule | how uncertainty is handled near tolerance limits |
| gauge/MSA | repeatability/reproducibility vs tolerance |
| independent truth | CMM, calibrated artifact, CAD nominal, cross-camera, or independent feature |
| replay receipt | command, inputs, outputs, code version, environment |
| negative control | wrong-axis, free-ICP, missing-marker, low-overlap, or perturbed transform |

This is aligned with:

- GUM/JCGM uncertainty practice: model the measurement and propagate relevant
  uncertainty contributions.
- ISO 14253-1 style GPS conformity logic: measurement uncertainty matters when
  proving conformity/nonconformity.
- MSA/Gage R&R practice: gauge variation must be small enough relative to the
  tolerance for the result to be useful.

## Current Measurement Health

| Branch | Measurement Maturity | Current Good Evidence | Main Gap |
|---|---|---|---|
| consumer_b | production-adjacent / adopted path | frozen per-view measure-lot path; `v8_pipeline` canonical; registration metric 1.6mm -> 0.9mm, 43.8% improvement; free 6-DOF/GICP collapse preserved as negative evidence | explicit uncertainty fields and decision rules are not yet first-class in result records |
| consumer_c | precision-progress, accuracy still open | known-axis ArUco/corner/turntable precision evidence; CAD bush nominal ruler prepared; GROUND_TRUTH R&R sigma 36.8um and P/T 22.08% documented | independent bush-vs-CAD accuracy must close before production accuracy claim |
| SX3i | research-only | reader bug corrected; C1 marker detection grounded; false speckle/denoise/recapture theory rejected | C2 connected assembly and C3 independent feature-coincidence are still open; no sub-0.1mm accuracy claim allowed |
| OMD | blocked | none | no source/interface/test contract |

## Scientific Registration Health

Current unified 3D tree metrics:

| Metric | Value |
|---|---:|
| nodes | 36 |
| frontier questions | 28 |
| open frontier | 17 |
| closed frontier | 11 |
| canonical node | `v8_pipeline` |
| canonical path | `prob_statement -> aruco_metric -> frozen_calib_reuse -> v8_pipeline` |
| registration improvement | 1.6mm -> 0.9mm, 43.8% |
| max degeneration depth | 3 |
| canonical credence | 0.973 |
| low-credence branches | `pv6dof_c`, `lx3_auto_path_ceiling` |
| frontier balance | -6 |

Assessment:

- Registration is being measured scientifically enough for research steering:
  there are baselines, negative branches, degeneration depth, canonical path,
  credence, and open frontier accounting.
- It is not sufficient by itself for industrial dimensional release because ICP
  fit quality and marker self-consistency do not prove part accuracy.
- The tree correctly preserves failed approaches instead of deleting them:
  `pv6dof_c`, `free_multiview_icp`, `lx3_auto_path_ceiling`,
  `misdiag_reader_frame`, and markerless C3 failure are useful negative controls.

## Self-Measurement / Anti-Self-Scoring

Existing safeguards:

- `docs/EVIDENCE_RECORD.md` defines `lakato-evidence-record/v1`.
- `examples/_evidence.py` rejects records that contain a verdict.
- Evidence records require provenance and pre-registration.
- `examples/record_judge.py` lets the engine produce the verdict from measured
  values instead of accepting hand-entered judgement.
- Tests cover invalid records, metric mismatch abstention, and real-record audit
  behavior.

Current gap:

- Evidence records do not yet require `uncertainty`, `decision_rule`,
  `negative_controls`, or `gauge` for production promotion.
- Some programme files still encode measurement narratives directly in Python
  node comments. That is acceptable for dogfood history, but production
  promotion should consume structured records.

## PROM Verdict

| Question | Verdict |
|---|---|
| Is document volume too high? | Manageable now, but should stop growing by copy-paste. Generate maps/boards from records next. |
| Are professional industrial dimensions being measured? | Partly. consumer_b is closest. consumer_c/SX3i still need independent accuracy gates before production claims. |
| Is scientific registration quality being checked? | Yes for research steering: baselines, negative branches, degeneracy, precision vs accuracy split are present. |
| Is self-measurement/self-scoring controlled? | Partly. Verdict-in-record is blocked and pre-registration is required, but uncertainty/decision-rule/gauge fields need to become hard gates. |

## Required Next Gates

1. Add production-promotion schema fields:
   - `uncertainty.value`
   - `uncertainty.method`
   - `decision_rule`
   - `tolerance`
   - `gauge`
   - `negative_controls`
   - `independent_truth`
2. Make `adopted` promotion fail if those fields are absent.
3. Generate PROM map/docs from a single board/record source.
4. For consumer_b: add uncertainty and decision-rule fields to feature records.
5. For consumer_c: close bush-vs-CAD independent accuracy or keep status
   `pending-port`.
6. For SX3i: close C2 assembly, then C3 feature-coincidence; keep status
   `research-only` until then.

## Bottom Line

The current work is scientifically useful and honest for research steering.
It is not yet uniformly industrial-release-grade dimensional metrology. The
right next move is not more narrative. It is structured evidence records with
uncertainty, decision rules, gauge/MSA, independent truth, and negative controls
as enforced promotion gates.
