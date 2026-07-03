"""dogfood: runtime-lean PROM 이 과장 없이 pending/receipt 규율을 지키는지 검사한다.

실제 runtime-lean guard 는 아직 착륙 전이다. 이 테스트는 PROM 하네스 자체가
손입력 verdict 를 쓰지 않고, receipt 없이는 가짜 green 을 만들지 않음을 고정한다.
# KG: span_lakatotree_runtime_lean_20260626
"""
from __future__ import annotations

from examples.runtime_lean_20260626_programme import NODES_DEF, run

_L3_GUARD = "test_uncertified_verdict_write_is_rejected"


def _by_tag(rc):
    return {r["tag"]: r for r in run(rc)}


def test_runtime_lean_findings_pending_without_receipts():
    scored = [r for r in run({}) if r["status"] != "ROOT"]
    assert len(scored) == 6
    assert all(r["verdict"] == "pending(no-receipt)" for r in scored)
    assert not any(r["status"] == "CLOSED" for r in scored)


def test_root_states_certificate_hardcore_not_python_total_verification():
    root = _by_tag({})["certificate_hardcore"]
    assert root["verdict"] == "canonical_stage"
    assert root["status"] == "ROOT"


def test_guard_landing_generates_progressive_via_judge():
    row = _by_tag({_L3_GUARD: True})["L3_python_write_gate"]
    assert row["verdict"] == "progressive"
    assert row["improved"] is True and row["novel"] is True


def test_failed_guard_does_not_generate_progressive():
    row = _by_tag({_L3_GUARD: False})["L3_python_write_gate"]
    assert row["verdict"] != "progressive"
    assert row["novel"] is False


def test_novel_metric_independent_from_improvement_metric():
    for node in NODES_DEF:
        if node.prediction is not None and node.novel_target is not None:
            assert node.prediction.metric_name != node.novel_target.metric_name, node.tag


def test_prom_source_has_no_literal_scored_verdict_assignment():
    import examples.runtime_lean_20260626_programme as mod

    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', 'verdict="partial"', 'verdict="equivalent"'):
        assert bad not in src, bad
