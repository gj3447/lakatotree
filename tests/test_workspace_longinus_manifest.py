"""Workspace-level Longinus manifest guard for the local 3D environment.

This keeps the cross-repo 3D workspace honest: a claim may be PIERCED only when
its sourcePath resolves, while undefined programmes such as OMD must remain
NO_SOURCE instead of silently entering the roadmap.
# KG: CT_LakatoTree_3D_Workspace_LonginusPiercing_20260624
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "workspace_longinus_manifest_20260624.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _repo_root(data: dict, repo: str) -> Path:
    return Path(data["roots"][repo])


def test_workspace_manifest_schema_and_paths() -> None:
    import pytest
    data = _load()
    assert data["schema"] == "lakatotree.workspace-longinus.v1"

    # clean-clone 가드: roots 는 형제 PI repo 절대경로(/data/kjra/PROJECT/PI/<repo>)다 — CI clean clone 엔
    #   lakatotree 만 체크아웃돼 형제 repo 가 없다. 부재하면 *파일존재 단언*만 skip(스키마는 위에서 검증,
    #   manifest 내용/불변식은 같은 파일 나머지 4 테스트가 커버; dev box 는 전수 실행). 외부경로 의존 표준 패턴.
    if not all(Path(p).exists() for p in data["roots"].values()):
        pytest.skip("workspace 형제 repo 부재(clean-clone CI) — 경로존재 단언 skip")

    for name, path in data["roots"].items():
        assert Path(path).exists(), (name, path)

    for item in data["bindings"]:
        assert item["sourceId"]
        assert item["repo"] in data["roots"]
        assert item["confidence"] in data["allowed_confidence"]
        assert item["binding_state"] in data["allowed_binding_state"]
        assert item["drift_type"] in data["allowed_drift_type"]
        assert item["lens_law"] in {"GetPut", "PutGet", "PutPut"}
        assert item["kg_anchor"]
        assert item["layer"].startswith(("L0_", "L1_", "L2_", "L3_"))

        if item["binding_state"] == "NO_SOURCE":
            assert item["sourcePath"] == ""
        else:
            path = item["sourcePath"].split(":", 1)[0]
            assert (_repo_root(data, item["repo"]) / path).exists(), item


def test_only_extracted_claims_can_be_pierced() -> None:
    data = _load()
    pierced = [item for item in data["bindings"] if item["binding_state"] == "PIERCED"]
    assert pierced
    assert all(item["confidence"] == "EXTRACTED" for item in pierced)
    assert all(item["sourcePath"] for item in pierced)


def test_bpc_z_risk_is_not_marked_pierced() -> None:
    data = _load()
    risky = [
        item for item in data["bindings"]
        if item["sourceId"] in {
            "prismv2.bpc.AlignmentConfig",
            "prismv2.bpc.PipelineRunner._run_measure_z",
            "prismv2.bpc.PipelineRunner._extract_kind_fields",
            "prismv2.bpc.measure_z_washer_expected_step",
            "prismv2.bpc.ALIGN_PATHS",
        }
    ]
    assert len(risky) == 5
    assert all(item["binding_state"] == "CANDIDATE" for item in risky)
    assert any("global CAD alignment" in item["claim"] for item in risky)
    assert any("CAD/default fallback" in item["claim"] for item in risky)


def test_lx3_and_omd_are_not_overpromoted() -> None:
    data = _load()
    by_id = {item["sourceId"]: item for item in data["bindings"]}

    assert by_id["prismv2.lx3.LX3_SUBFRAME_FEATURES"]["binding_state"] == "PRELIMINARY"
    assert "placeholder" in by_id["prismv2.lx3.LX3_SUBFRAME_FEATURES"]["claim"]

    omd = by_id["Workspace3D.OMD"]
    assert omd["binding_state"] == "NO_SOURCE"
    assert omd["confidence"] == "AMBIGUOUS"
    assert omd["sourcePath"] == ""


def test_hard_blocks_name_the_semantic_failure_modes() -> None:
    data = _load()
    text = "\n".join(data["hard_blocks"])
    assert "global CAD alignment residual" in text
    assert "CAD/default z" in text
    assert "placeholder bolt" in text
    assert "OMD" in text
