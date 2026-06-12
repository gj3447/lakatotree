# consumer_b PrismV2 Segmentation Longinus Pack

> KG: `SA_LakatoTree_BPC_PrismV2_Segmentation_20260612`,
> `CT_LakatoTree_BPC_PrismV2_KnowledgePack_20260612`
> LONGINUS: sourceId=`LakatoTree.BpcPrismV2SegKnowledgePack`,
> sourcePath=`docs/BPC_CONSUMER_A_LONGINUS_20260612.md:1`

이 문서는 consumer_b segmentation/consumer_a 기반지식을 Lakatotree 개발 루프에 꽂는
Longinus 기준점이다. 목표는 Lakatotree가 consumer_b 작업을 단순 메모가 아니라
사전등록 예측, 재현 가능한 judge, 계보, code reference로 추적하게 만드는 것이다.

## Hard Core

- 2D segmentation은 위치와 coarse decision만 담당한다.
- 치수 측정은 3D geometry/RecipeV2/HALCON 또는 기존 classical detector가 담당한다.
- `PLATE_HOLE`, `OUTER_HOLE`, `EXTERNAL_HOLE`은 독립 물체가 아니라 parent plane의 void boundary다.
- hole 3종의 production observation은 center XY와 parent/base Z면 충분하다. per-view fitted center를 물리 truth로 쓰지 않는다.
- `CUP`은 CAD band Z와 bore edge 규칙을 분리한다. z는 nadir-only, `BIG_02/09`는 calibration anchor가 아니라 defect다.
- `TAB_BOLT`/washer는 `base_tab`, `washer_top`, `head_top` 3층을 보존한다.
- `LABEL` segmentation은 ROI helper다. decoded lot truth는 v16 DataMatrix policy가 결정한다.

## Segmentation Classes

| Class | YOLO id | PrismV2 role | Measurement contract |
|---|---:|---|---|
| `CUP` | 1 | cup ROI, defect gate | CAD-prior bore edge r ~= 22.08 plus per-cup delta, nadir-only z |
| `EXTERNAL_HOLE` | 2 | lower/external void boundary | center XY + parent/base Z; deep bore uses plane z-gated void edge only |
| `LABEL` | 3 | label ROI only | v16 label decode remains gated by `MODBUS_LABEL_VIEW_ID` |
| `OUTER_HOLE` | 4 | lower outer void boundary | center XY + parent/base Z after STEP/margin gate |
| `PLATE_HOLE` | 5 | upper plate void boundary | center XY + parent/base Z; not an independent object |
| `TAB_BOLT` | 6 | washer/bolt stack | base_tab, washer_top, head_top; washer height fields preserved |

`consumer_b` id 0 and `ZIG` id 7 are training/context classes, not production measurement classes.

## Lakatotree Binding

Use the pack as one Lakatotree branch under `LakatosTree_BPC_20View_20260612`.

- Theory gate: `LakatosGate.evaluate` in `lakatos/engine.py:264`.
- Structured prediction: `Prediction`, `NovelTarget`, `judge` in `lakatos/judge.py:20`, `:39`, `:65`.
- Data replay: `LineageReplayGate.evaluate` in `lakatos/engine.py:412`.
- Provenance: `prov_triples` and `replay_command` in `lakatos/prov.py:10`, `:28`.
- Cycle orchestration: `LakatoHarness.run_cycle` in `lakatos/harness.py:60`.

Recommended first Lakatotree node:

- tree: `LakatosTree_BPC_20View_20260612`
- tag: `seg_v3_consumer_a_contract`
- parent: current consumer_b canonical node
- metric: `contract_missing_count`
- direction: `lower`
- novel target: class-map drift count equals `0` and required contracts exist
- build command: `python -m pytest tests/test_bpc_consumer_a_longinus_manifest.py -q`

After consumer_a implementation starts, replace the metric with result-level judges:

- `loo_p95_worstlot`: lower is better; existing script `judges/bpc_loo_p95.py`.
- `seg_contract_missing_count`: lower is better; expected `0`.
- `defect_flag_recall_BIG_02_09`: higher is better; expected `1.0`.
- `normal_washer_cup_z_lot_repeat_p95`: lower is better; target `<= 0.1`.

## PrismV2 Source Binding

Primary implementation surfaces:

- `services/inspection/src/adapters/bpc/bpc_feature_contract.py:10`: production class contract.
- `services/inspection/src/adapters/bpc/detect_registry.py:76`: RecipeV2 detect/measure signatures.
- `services/inspection/src/adapters/bpc/detect_registry.py:302`: `tab_bolt_z_layers`.
- `services/inspection/src/adapters/bpc/pipeline_runner.py:45`: `StageConfig` opt-in algorithms.
- `services/inspection/src/adapters/bpc/pipeline_runner.py:438`: per-kind output extraction.
- `services/inspection/src/adapters/bpc/v16_label_adapter.py:37`: v16 label view gate.
- `services/inspection/src/adapters/bpc/label_decode_policy.py:146`: bounded label decode policy.
- `services/neural/config/neural-registry.yaml:14`: neural model registry.
- `tests/neural/test_registry_catalog.py:36`: registry catalog pin.

Do not widen the old hole-centered `DetectionBackend` for mask segmentation. The better
contract is a separate segmentation adapter that emits mask instances, then a
`SegInstance -> FeatureObservation` bridge that RecipeV2 can consume.

## Evidence Binding

Core evidence files in the shared workspace:

- `PROMPTS/06.11_problem.txt:50`: geometry truth table requirement.
- `consumer_b/2dmaskedbase/ultracode1/GEOMETRY_TRUTH.json:5`: `CUP` truth.
- `consumer_b/2dmaskedbase/ultracode1/GEOMETRY_TRUTH.json:76`: `PLATE_HOLE` truth.
- `consumer_b/2dmaskedbase/ultracode1/GEOMETRY_TRUTH.json:251`: `OUTER_HOLE` truth.
- `consumer_b/2dmaskedbase/ultracode1/GEOMETRY_TRUTH.json:331`: `EXTERNAL_HOLE` truth.
- `consumer_b/2dmaskedbase/ultracode1/GEOMETRY_TRUTH.json:802`: `TAB_BOLT`/washer truth.
- `consumer_b/2dmaskedbase/ultracode1/CAD_FACTOR_SPEC_v1.md:5`: raw residuals against CAD primitives.
- `consumer_b/2dmaskedbase/ultracode1/BASE_PLANE_WASHER_Z.md:93`: washer z production fields.
- `consumer_b/seg_train/dataset_v3/bpc_seg_v3.yaml:6`: YOLO class map.
- `consumer_b/scripts/271_zlayer_clean_seg.py:70`: z-layer class generation map.
- `consumer_b/seg_train/train_v3.log:817`: segmentation validation metrics.
- `consumer_b/2dmaskedbase/ultracode1/SOLVER_PKG_v12/README.md:19`: v12 solver decisions.

## Development Checklist

1. Add a consumer_a neural registry entry for the consumer_b YOLO segmentation model.
2. Add a segmentation adapter contract with stable class map validation.
3. Bridge `SegInstance` to RecipeV2 feature observations without making masks the measurement truth.
4. Implement hole 3-class void-boundary observation: center XY + parent/base Z.
5. Keep cup/washer geometry output fields aligned with `GEOMETRY_TRUTH`.
6. Keep v16 label decode as the authoritative label recognition path; segmentation only provides ROI fallback.
7. Register Lakatotree predictions before running judge scripts.
8. Preserve lineage from ZDF/source images through masks, feature observations, and final result JSON.

The machine-readable form of this pack is `docs/bpc_consumer_a_longinus_manifest.json`.
