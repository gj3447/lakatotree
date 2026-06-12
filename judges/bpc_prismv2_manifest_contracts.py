#!/usr/bin/env python3
"""Judge BPC/prismv2 Longinus manifest contract completeness.

Usage:
    python judges/bpc_prismv2_manifest_contracts.py docs/bpc_prismv2_longinus_manifest.json

Output is intentionally simple for LakatoHarness: ``metric=<missing_count>``.
# KG: CT_LakatoTree_BPC_PrismV2_KnowledgePack_20260612
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


REQUIRED_PRODUCTION_CLASSES = {
    "CUP": 1,
    "EXTERNAL_HOLE": 2,
    "OUTER_HOLE": 4,
    "PLATE_HOLE": 5,
    "TAB_BOLT": 6,
}
REQUIRED_NONPRODUCTION_CLASSES = {"LABEL": 3}
REQUIRED_CONTRACTS = {
    "CT_BPC_SegModelRegistry",
    "CT_BPC_YoloSegAdapter",
    "CT_BPC_SegToCadObservation",
    "CT_BPC_Hole3ClassVoidBoundary",
    "CT_BPC_CupGeometry",
    "CT_BPC_TabBoltWasherGeometry",
    "CT_BPC_LabelRecognition",
    "CT_BPC_RecipeOptIn",
}


def missing_contracts(manifest: dict, repo_root: Path) -> list[str]:
    missing: list[str] = []
    by_class = {item.get("name"): item for item in manifest.get("segmentation_classes", [])}

    for name, yolo_id in REQUIRED_PRODUCTION_CLASSES.items():
        item = by_class.get(name)
        if item is None:
            missing.append(f"class:{name}")
            continue
        if item.get("yolo_id") != yolo_id:
            missing.append(f"class_id:{name}")
        if item.get("production") is not True:
            missing.append(f"class_production:{name}")
        contract = item.get("measurement_contract", "")
        if name.endswith("_HOLE") and "center_xy" not in contract:
            missing.append(f"hole_center_xy:{name}")

    for name, yolo_id in REQUIRED_NONPRODUCTION_CLASSES.items():
        item = by_class.get(name)
        if item is None:
            missing.append(f"class:{name}")
            continue
        if item.get("yolo_id") != yolo_id:
            missing.append(f"class_id:{name}")
        if item.get("production") is not False:
            missing.append(f"class_nonproduction:{name}")

    contracts = {item.get("name") for item in manifest.get("contracts", [])}
    for name in sorted(REQUIRED_CONTRACTS - contracts):
        missing.append(f"contract:{name}")

    for ref in manifest.get("lakatotree_bindings", []):
        source_path = str(ref.get("sourcePath", "")).split(":", 1)[0]
        if not source_path or not (repo_root / source_path).exists():
            missing.append(f"lakatotree_ref:{ref.get('sourceId', source_path)}")

    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bpc_prismv2_manifest_contracts.py <manifest.json>", file=sys.stderr)
        return 2

    manifest_path = Path(argv[1]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = manifest_path.parents[1] if manifest_path.parent.name == "docs" else Path.cwd()
    missing = missing_contracts(manifest, repo_root)

    print(f"metric={len(missing)}")
    if missing:
        print("missing=" + ",".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
