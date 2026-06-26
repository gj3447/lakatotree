# Workspace Longinus Piercing - 2026-06-24

> KG: `CT_LakatoTree_3D_Workspace_LonginusPiercing_20260624`,
> `lesson-3d-workspace-longinus-piercing-20260624`
> LONGINUS: sourceId=`Workspace3D.LonginusPiercing`,
> sourcePath=`docs/WORKSPACE_LONGINUS_PIERCING_20260624.md:1`

This file binds the local 3D work environment to the actual Longinus method used by
`bhgman_tool`: ReferenceSite, dual reference, confidence tier, binding state, and
drift law. It is not a critique memo. It is the map of what is pierced, what is only
candidate, and what is still missing.

Machine-readable state:

- `docs/workspace_longinus_manifest_20260624.json`
- `tests/test_workspace_longinus_manifest.py`

## Workspace Boundary

| Layer | Repo | Role | Longinus risk |
|---|---|---|---|
| L0 | `PI/bhgman_tool` | Canonical Longinus method and audit engine | Misusing Longinus as tone instead of binding |
| L1 | `PI/lakatotree` | Research tree, PROM docs, judges, binding guards | Review claims can look pierced while only inferred |
| L2 | `3D/prismv2` | PrismV2 production/research implementation | Global CAD alignment can be confused with feature-dimensional truth |
| L3 | `3D/3d_vision_jg_bpc` | Legacy/current BPC runtime, DT, connector, PLC/UI surface | Runtime outputs may drift from PrismV2 contracts |

## Current Pierce Judgement

### PIERCED

- `bhgman_tool` Longinus skill is the canonical rule source.
- `lakatotree` code binding audit is live: `python -m lakatos.longinus`.
- `lakatotree` reverse-orphan guard is live for code `# KG:` anchors.
- BPC/prismv2 knowledge pack has a tested manifest.

### CANDIDATE / PRELIMINARY

- BPC production path is bound to PrismV2 files, but measurement acceptance still needs a
  stronger gate that separates rigid registration residual from feature z residual.
- BPC z-height critique is intentionally `AMBIGUOUS`: it names a plausible failure mode,
  but does not yet carry production result evidence.
- LX3 has source surfaces and placeholders; the 12-bolt spec is explicitly pending user
  input and must not be treated as final dimensional truth.

### NO_SOURCE

- OMD is not defined in the local PrismV2/LakatoTree/BPC checkout. It must stay
  `NO_SOURCE` until a contract, source path, or owner document appears.

## Longinus Cuts For This Environment

1. Do not say "CAD registration is good" unless the report also shows per-feature
   residuals, frame/sign convention, and z-layer attribution.
2. Do not say "z is measured" when the code only falls back to `spec.cad_z`.
3. Do not say "industrial precision" without uncertainty, repeatability, calibration,
   and traceability fields.
4. Do not let `line_hint` become the anchor. Symbol/sourceId is the anchor; line is cache.
5. Do not mark inferred critique as `PIERCED`.
6. Do not let OMD enter the roadmap as a ghost node. It is `NO_SOURCE` until materialized.

## Immediate Gates To Add Next

- PrismV2 BPC result judge: fail when `measured_z is None` but verdict passes as if z
  were measured.
- PrismV2 BPC alignment judge: record `rigid_rmse`, `feature_z_residual_p95`,
  `frame_id`, `datum_id`, and `sign_convention`.
- JG BPC bridge judge: compare DT/UI displayed z fields against PrismV2 result fields.
- LX3 migration judge: fail if placeholder bolt coordinates are used in production mode.
- OMD definition gate: block any `omd` programme from `pending-port` or `adopted` until
  a source file and contract are declared.

## The Real Warning

The dangerous failure here is not low test count. The dangerous failure is semantic:

> A global surface alignment can look numerically good while the feature-level
> dimensional claim is false.

Longinus must prevent that collapse. The manifest therefore treats global alignment,
feature measurement, CAD nominal data, runtime display, and research critique as
separate ReferenceSite candidates.
