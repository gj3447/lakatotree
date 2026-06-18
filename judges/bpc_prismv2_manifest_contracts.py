#!/usr/bin/env python3
"""Judge consumer_b/consumer_a Longinus manifest contract completeness.

Usage:
    python judges/bpc_consumer_a_manifest_contracts.py docs/bpc_consumer_a_longinus_manifest.json

Output is intentionally simple for LakatoHarness: ``metric=<missing_count>``.
# KG: CT_LakatoTree_BPC_PrismV2_KnowledgePack_20260612
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # lakatos pkg importable as a script
from lakatos.facts import FactQuery, evaluate  # noqa: E402


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


def _class_queries() -> list[FactQuery]:
    """The required-class contracts expressed as DATA — one FactQuery row per rule, in the
    historical emit order. A missing class emits only ``class:<name>`` (the ``field`` checks
    vacuously pass when the row is absent), matching the original ``continue`` behaviour."""
    qs: list[FactQuery] = []
    for name, yid in REQUIRED_PRODUCTION_CLASSES.items():
        qs.append(FactQuery("present", f"class:{name}", (name,)))
        qs.append(FactQuery("field", f"class_id:{name}", (name, "yolo_id", "==", yid)))
        qs.append(FactQuery("field", f"class_production:{name}", (name, "production", "==", True)))
        if name.endswith("_HOLE"):
            qs.append(FactQuery("field", f"hole_center_xy:{name}",
                                (name, "measurement_contract", "contains", "center_xy")))
    for name, yid in REQUIRED_NONPRODUCTION_CLASSES.items():
        qs.append(FactQuery("present", f"class:{name}", (name,)))
        qs.append(FactQuery("field", f"class_id:{name}", (name, "yolo_id", "==", yid)))
        qs.append(FactQuery("field", f"class_nonproduction:{name}", (name, "production", "==", False)))
    return qs


def missing_contracts(manifest: dict, repo_root: Path) -> list[str]:
    # class-completeness rules are DATA, evaluated by the reusable fact-query runner.
    by_class = {item.get("name"): item for item in manifest.get("segmentation_classes", [])}
    missing = evaluate(by_class, _class_queries())
    # structural checks that are not keyed-row field comparisons stay direct:
    contracts = {item.get("name") for item in manifest.get("contracts", [])}
    missing += [f"contract:{name}" for name in sorted(REQUIRED_CONTRACTS - contracts)]
    for ref in manifest.get("lakatotree_bindings", []):
        source_path = str(ref.get("sourcePath", "")).split(":", 1)[0]
        if not source_path or not (repo_root / source_path).exists():
            missing.append(f"lakatotree_ref:{ref.get('sourceId', source_path)}")
    return missing


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: bpc_consumer_a_manifest_contracts.py <manifest.json>", file=sys.stderr)
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
