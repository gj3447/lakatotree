"""P7-E: BPC/prismv2 Longinus manifest 무결성 (TDD).

INT-2  in-repo lakatotree_bindings 의 file:line 이 실제 심볼을 가리키는지 (자가검증 drift guard)
INT-5  binding/contract 구조형태(필수키) 검증 — JSON Schema 의존 없이
INT-1/INT-4  prismv2 cross-repo refs 는 point-in-time(stale 허용)로 정직표기 — CI 미검증
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "bpc_prismv2_longinus_manifest.json"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# ── INT-2: in-repo binding line 이 실제 심볼을 가리킨다 (Longinus L1/L6 drift guard) ──
def test_lakatotree_binding_lines_resolve_to_symbol():
    data = _load()
    for ref in data["lakatotree_bindings"]:
        path, _, line_s = ref["sourcePath"].partition(":")
        assert line_s, f"line 번호 없음: {ref}"
        line_no = int(line_s)
        symbol = ref["sourceId"].split(".")[-1]      # 마지막 컴포넌트 = 실제 심볼명
        src = (ROOT / path).read_text(encoding="utf-8").splitlines()
        assert 1 <= line_no <= len(src), f"line 범위 밖: {ref}"
        target = src[line_no - 1]
        assert symbol in target, (
            f"Longinus drift: {ref['sourceId']} 가 {path}:{line_no} 에 없음 "
            f"(실제 라인: {target.strip()!r})")


# ── INT-5: 구조형태 검증 (필수키) — jsonschema 의존 없이 ──
def test_all_bindings_have_sourceid_and_file_line():
    data = _load()
    for group in ("lakatotree_bindings", "prismv2_bindings"):
        for ref in data[group]:
            assert ref.get("sourceId"), f"{group}: sourceId 누락 {ref}"
            sp = ref.get("sourcePath", "")
            assert ":" in sp, f"{group}: sourcePath 가 file:line 형식 아님 {ref}"
            assert sp.rsplit(":", 1)[1].isdigit(), f"{group}: line 번호 비정수 {ref}"


def test_contracts_have_name_and_target_file():
    data = _load()
    for c in data["contracts"]:
        assert c.get("name", "").startswith("CT_"), f"contract name 규약 위반 {c}"
        assert c.get("target_file"), f"contract target_file 누락 {c}"


# ── INT-1/INT-4: prismv2 cross-repo refs = point-in-time 정직표기 (CI 미검증) ──
def test_prismv2_bindings_declared_point_in_time_not_ci_validated():
    data = _load()
    state = data["prismv2_binding_state"]
    assert state["ci_validated"] is False, "cross-repo prismv2 refs 를 CI 가 검증하면 브리틀 결합"
    assert "POINT_IN_TIME" in state["state"]
    assert "drift" in state["note"] or "stale" in state["note"]
