"""F-CON-1 TDD — 노드 result_path↔계보 링크 → 재현성 게이트 자동 공급.

_reproducible_for_node 가 완성본을 raw source 까지 추적해 재현가능 여부를 낸다.
엄격 source(kind='source' 만): dangling intermediate=재현불가=차단. 비파이프라인 노드=None(비적용).
# KG: span_lakatotree_reproducibility_wire / q-lkt-foundation-credibility-wire
"""
import importlib
import os

import pytest

from lakatos.io.lineage import Derivation


def load_app():
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "test")
    return importlib.import_module("server.app")


def _patch(monkeypatch, app, *, result_path, derivations, verify=True):
    monkeypatch.setattr(app, "kg", lambda q, **p: [{"rp": result_path}])
    monkeypatch.setattr(app, "_load_lineage", lambda: derivations)
    # ★R-AUDIT-1: source sha 의 *서버 디스크 재계산*을 시뮬레이션. verify=True 면 현실이 기록과 일치(파일 존재·
    #   sha 일치), verify=False 면 검증 불가(파일 부재) = client 자기선언만 — forge.
    recorded = {d.output: d.output_sha for d in derivations}
    monkeypatch.setattr(app, "_path_sha",
                        (lambda path: recorded.get(path)) if verify else (lambda path: None))


REPRODUCIBLE = [
    Derivation(output="raw.zdf", output_sha="z", producer="", producer_sha="",
               inputs=[], kind="source"),
    Derivation(output="final.json", output_sha="f", producer="solve.py", producer_sha="ps",
               inputs=[("raw.zdf", "z")], kind="final"),
]
GAP = [  # mid.json 은 derivation 없고 source 도 아님 → dangling → 재현불가
    Derivation(output="final.json", output_sha="f", producer="solve.py", producer_sha="ps",
               inputs=[("mid.json", "m")], kind="final"),
]
# 나생문 CON-1/F-CON-1-A: derivation 기록은 됐지만 inputs 빈 비-source = dangling leaf (가짜 reproducible 함정)
DANGLING_FINAL = [  # final 인데 inputs 비어있음 — 아무 source 서도 재생성 불가
    Derivation(output="final.json", output_sha="f", producer="", producer_sha="",
               inputs=[], kind="final"),
]
DANGLING_VIA_INTERMEDIATE = [  # source 있지만 final 이 inputs-빈 intermediate 경유 → 끊김
    Derivation(output="raw.zdf", output_sha="z", producer="", producer_sha="", inputs=[], kind="source"),
    Derivation(output="mid.json", output_sha="m", producer="", producer_sha="", inputs=[], kind="intermediate"),
    Derivation(output="final.json", output_sha="f", producer="solve.py", producer_sha="ps",
               inputs=[("mid.json", "m")], kind="final"),
]


def test_no_result_path_is_none(monkeypatch):
    app = load_app()
    _patch(monkeypatch, app, result_path="", derivations=REPRODUCIBLE)
    assert app._reproducible_for_node("tree", "n1") is None


def test_result_path_not_in_lineage_is_none(monkeypatch):
    app = load_app()
    _patch(monkeypatch, app, result_path="unrecorded.json", derivations=REPRODUCIBLE)
    assert app._reproducible_for_node("tree", "n1") is None


def test_traceable_to_raw_source_is_reproducible(monkeypatch):
    app = load_app()
    _patch(monkeypatch, app, result_path="final.json", derivations=REPRODUCIBLE)
    assert app._reproducible_for_node("tree", "n1") is True


def test_dangling_intermediate_is_not_reproducible(monkeypatch):
    # 핵심: leaf-root 관대해석이 아니라 엄격 source — mid.json 갭이 차단으로 살아야
    app = load_app()
    _patch(monkeypatch, app, result_path="final.json", derivations=GAP)
    assert app._reproducible_for_node("tree", "n1") is False


def test_dangling_final_with_empty_inputs_not_reproducible(monkeypatch):
    # 나생문 CON-1: final 인데 inputs 빈 비-source = 가짜 reproducible 차단돼야
    app = load_app()
    _patch(monkeypatch, app, result_path="final.json", derivations=DANGLING_FINAL)
    assert app._reproducible_for_node("tree", "n1") is False


def test_dangling_via_empty_intermediate_not_reproducible(monkeypatch):
    # 나생문 F-CON-1-A: source 있어도 inputs-빈 intermediate 경유면 끊긴 사슬 → 재현불가
    app = load_app()
    _patch(monkeypatch, app, result_path="final.json", derivations=DANGLING_VIA_INTERMEDIATE)
    assert app._reproducible_for_node("tree", "n1") is False


def test_result_path_is_declared_source_reproducible(monkeypatch):
    app = load_app()
    _patch(monkeypatch, app, result_path="raw.zdf", derivations=REPRODUCIBLE)
    assert app._reproducible_for_node("tree", "n1") is True


def test_forged_source_unverifiable_sha_is_not_reproducible(monkeypatch):
    # ★R-AUDIT-1 봉쇄: 계보 SHAPE 는 맞아도(client 가 kind='source' 자기선언) 서버가 source 파일을 해시 못 하면
    #   (파일 부재) reproducible 영수증 못 줌 → None. client 자기선언만으론 floor 영수증 절대 못 만든다.
    app = load_app()
    _patch(monkeypatch, app, result_path="final.json", derivations=REPRODUCIBLE, verify=False)
    assert app._reproducible_for_node("tree", "n1") is None


def test_mismatched_source_sha_is_not_reproducible(monkeypatch):
    # source 파일은 있으나 서버 재계산 sha 가 기록값과 다름(content 위조/변조) → 영수증 못 줌
    app = load_app()
    monkeypatch.setattr(app, "kg", lambda q, **p: [{"rp": "final.json"}])
    monkeypatch.setattr(app, "_load_lineage", lambda: REPRODUCIBLE)
    monkeypatch.setattr(app, "_path_sha", lambda path: "DIFFERENT")   # 현실 ≠ 기록
    assert app._reproducible_for_node("tree", "n1") is None


def test_self_declared_source_forge_requires_real_file(monkeypatch):
    # ★최단 forge(감사 지적): 노드 자기 result_path 를 kind='source' 로 선언 → 전엔 즉시 True.
    #   이제 서버 디스크 검증 통과해야만 True; 파일 없으면 None(자기선언 무력화).
    app = load_app()
    _patch(monkeypatch, app, result_path="raw.zdf", derivations=REPRODUCIBLE, verify=False)
    assert app._reproducible_for_node("tree", "n1") is None


def test_gate_blocks_canonical_when_not_reproducible(monkeypatch):
    # _reproducible_for_node=False → synthesize_promotion 이 not_reproducible 로 차단
    app = load_app()
    from lakatos.verdict.spine import synthesize_promotion
    d = synthesize_promotion(scripted_verdict="progressive", stands=True, reproducible=False)
    assert not d["ok"] and "not_reproducible" in d["reasons"]


def test_node_missing_returns_none(monkeypatch):
    app = load_app()
    monkeypatch.setattr(app, "kg", lambda q, **p: [])
    monkeypatch.setattr(app, "_load_lineage", lambda: REPRODUCIBLE)
    assert app._reproducible_for_node("tree", "ghost") is None
