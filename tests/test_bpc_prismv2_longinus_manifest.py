"""BPC/prismv2 Longinus knowledge pack drift checks.

The manifest is intentionally a development artifact: it lets Lakatotree keep
the BPC segmentation contracts, prismv2 source references, and judge entrypoints
in one machine-readable place.
# KG: CT_LakatoTree_BPC_PrismV2_KnowledgePack_20260612
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "bpc_prismv2_longinus_manifest.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_has_required_class_contracts() -> None:
    data = _load()
    classes = {item["name"]: item for item in data["segmentation_classes"]}

    assert {name for name, item in classes.items() if item["production"]} == {
        "CUP",
        "EXTERNAL_HOLE",
        "OUTER_HOLE",
        "PLATE_HOLE",
        "TAB_BOLT",
    }
    assert classes["LABEL"]["production"] is False
    assert "roi_helper" in classes["LABEL"]["role"]

    ids = {item["yolo_id"] for item in data["segmentation_classes"]}
    assert ids == {1, 2, 3, 4, 5, 6}
    assert {item["yolo_id"] for item in data["ignored_training_classes"]} == {0, 7}


def test_hole_classes_keep_void_boundary_contract() -> None:
    data = _load()
    by_name = {item["name"]: item for item in data["segmentation_classes"]}

    for cls in ("PLATE_HOLE", "OUTER_HOLE", "EXTERNAL_HOLE"):
        contract = by_name[cls]["measurement_contract"]
        assert "center_xy" in contract
        assert "base_z" in contract or "parent_or_base_z" in contract

    assert "deep_bore" in by_name["EXTERNAL_HOLE"]["measurement_contract"]


def test_contract_targets_cover_prismv2_integration_surface() -> None:
    data = _load()
    names = {item["name"] for item in data["contracts"]}

    assert {
        "CT_BPC_SegModelRegistry",
        "CT_BPC_YoloSegAdapter",
        "CT_BPC_SegToCadObservation",
        "CT_BPC_Hole3ClassVoidBoundary",
        "CT_BPC_CupGeometry",
        "CT_BPC_TabBoltWasherGeometry",
        "CT_BPC_LabelRecognition",
        "CT_BPC_RecipeOptIn",
    } <= names

    targets = {item["target_file"] for item in data["contracts"]}
    assert "services/neural/config/neural-registry.yaml" in targets
    assert "services/inspection/src/adapters/bpc/pipeline_runner.py" in targets


def test_lakatotree_references_resolve_inside_this_repo() -> None:
    data = _load()

    for ref in data["lakatotree_bindings"]:
        path = ref["sourcePath"].split(":", 1)[0]
        assert (ROOT / path).exists(), ref

    doc_path = data["longinus"]["sourcePath"].split(":", 1)[0]
    manifest_path = data["longinus"]["manifestSourcePath"].split(":", 1)[0]
    assert (ROOT / doc_path).exists()
    assert (ROOT / manifest_path).exists()


def test_workspace_evidence_is_declared_but_not_required_for_public_ci() -> None:
    data = _load()
    evidence = data["workspace_evidence"]

    assert {item["sourceId"] for item in evidence} >= {
        "GEOMETRY_TRUTH.CUP",
        "GEOMETRY_TRUTH.PLATE_HOLE",
        "GEOMETRY_TRUTH.OUTER_HOLE",
        "GEOMETRY_TRUTH.EXTERNAL_HOLE",
        "GEOMETRY_TRUTH.TAB_BOLT",
        "BPC_SEG_V3.class_map",
    }

    workspace = ROOT.parents[1]
    if not (workspace / "BPC").exists():
        return

    for ref in evidence:
        path = ref["sourcePath"].split(":", 1)[0]
        assert (workspace / path).exists(), ref


def test_manifest_contract_judge_reports_zero_missing_contracts() -> None:
    script = ROOT / "judges" / "bpc_prismv2_manifest_contracts.py"
    result = subprocess.run(
        [sys.executable, str(script), str(MANIFEST)],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "metric=0" in result.stdout.splitlines()
