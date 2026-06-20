"""prom-honesty/1 + /3 (적대감사 2026-06-20) — 헤드라인 불변식의 *런타임* 강제 회귀가드.

감사 발견(가장 중대): "neither subsystem scores its own output" 은 Lean 모델에서만 참이고,
런타임 노드-쓰기 경로(writer.add_node/upsert_nodes)는 NodeIn.verdict 자유문자열을 judge() 없이
그대로 KG 에 써서 클라이언트가 verdict='progressive' 를 self-report 주입할 수 있었다(metrics 가
이를 진짜 진보로 집계). 또 결합 게이트(set_verdict 403)는 *행동 테스트가 0개*였다.

이 파일이 그 두 구멍을 영수증으로 고정한다:
  - 노드 생성/업서트 경로는 스크립트 판결을 422 로 거부(self-report 불가).
  - writer 는 validator 를 우회해도 by-construction(ValueError) 으로 거부.
  - 행정/구조 어휘는 정상 통과(judge 경로의 정직한 채점은 막지 않는다).
  - set_verdict 는 스크립트 판결에 403(결합 불변식의 첫 행동 테스트).
# KG: span_lakatotree_verdict_registry
"""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from server.contexts.tree.mutations import TreeMutationService, TreeSpec
from server.contexts.tree.schemas import NodeIn, VerdictIn
from server.contexts.tree.validation import LakatosSemanticValidator
from server.contexts.tree.writer import TreeKgWriter
from lakatos.verdicts import SCRIPTED_VERDICTS, ENGINE_VERDICTS, REBUILD_VERDICTS

# 노드-쓰기 게이트가 막아야 하는 *스코어링* 어휘 전체 (judge=scripted ∪ engine ∪ rebuild).
# scripted 만 막으면 progressive_conditional(engine, PROGRESS_VERDICTS) 로 같은 주입이 뚫린다.
SCORED = sorted(SCRIPTED_VERDICTS | ENGINE_VERDICTS | REBUILD_VERDICTS)


def _service():
    """노드 쓰기를 기록(writes)하는 mutation service — 거부 시 writes 가 비어 있어야 한다."""
    writes: list = []
    svc = TreeMutationService(
        writer=TreeKgWriter(lambda ops: writes.append(ops) or [[]]),
        validator=LakatosSemanticValidator(),
        hist=lambda *a, **k: None,
    )
    return svc, writes


def _scored_node(verdict, *, tag="child", parent=None):
    """*완전 채운* scored 노드 — 감사의 실제 주입과 동형. 빈약한 노드는 정책(progressive_metric_required
    등)이 *우발적으로* 422 를 내 게이트를 가려버리므로(재검증서 발견), 정책이 받아들이는 완전 노드로
    게이트를 *격리* 테스트한다."""
    return NodeIn(tag=tag, parent=parent, verdict=verdict, metric_name="m", metric_value=1.0,
                  metric_scope="s", script="run.py", result_path="o.json",
                  algorithm="a", comment="c", limitation="l")


_GATE_SIG = "judge/engine 전용"   # 내 게이트 고유 메시지 — 정책 메시지(Lakatos policy violation)와 구분


# ── prom-honesty/1: 노드-쓰기 경로는 스코어링 판결을 거부(self-report 차단) ──────────────
@pytest.mark.parametrize("verdict", SCORED)
def test_add_node_rejects_every_scored_verdict_422(verdict):
    svc, writes = _service()
    with pytest.raises(HTTPException) as exc:
        svc.add_node("T", _scored_node(verdict), tree_data={"nodes": []})
    assert exc.value.status_code == 422
    assert _GATE_SIG in exc.value.detail   # *내 게이트*가 거부(정책 우발 거부 아님) — 격리
    assert writes == []   # 거부는 *쓰기 이전* — 한 줄도 KG 에 안 들어간다


@pytest.mark.parametrize("verdict", SCORED)
def test_upsert_tree_rejects_scored_verdict_422(verdict):
    svc, writes = _service()
    spec = TreeSpec(name="T", nodes=(NodeIn(tag="root"),
                                     _scored_node(verdict, parent="root")))
    with pytest.raises(HTTPException) as exc:
        svc.upsert_tree(spec)
    assert exc.value.status_code == 422
    assert _GATE_SIG in exc.value.detail
    assert writes == []


# ── judge 의 정직한 채점은 막지 않는다: 행정/구조 어휘는 통과 ─────────────────────────────
def test_node_create_allows_nonscripted_verdict():
    """비-스크립트 어휘는 게이트를 통과해 실제로 KG 에 쓰인다(judge 의 정직한 채점/구조 노드는 안 막힘).
    ('proof' 는 추가 정책요건이 없는 중립 어휘 — canonical_* 등은 metric/provenance 요건이 별도다.)"""
    svc, writes = _service()
    out = svc.add_node("T", NodeIn(tag="n", verdict="proof"), tree_data={"nodes": []})
    assert out["ok"] is True
    assert writes   # 정상 어휘는 실제로 KG 에 쓰인다


def test_default_proof_verdict_is_allowed():
    svc, _ = _service()
    assert svc.add_node("T", NodeIn(tag="n"), tree_data={"nodes": []})["ok"] is True


# ── writer by-construction 백스톱: validator 를 우회해도 막힌다 ────────────────────────────
@pytest.mark.parametrize("verdict", SCORED)
def test_writer_add_node_byconstruction_rejects_scored(verdict):
    writer = TreeKgWriter(lambda ops: [[]])
    with pytest.raises(ValueError, match="prom-honesty/1"):
        writer.add_node("T", NodeIn(tag="x", verdict=verdict), [])


@pytest.mark.parametrize("verdict", SCORED)
def test_writer_upsert_nodes_byconstruction_rejects_scored(verdict):
    writer = TreeKgWriter(lambda ops: [[]])
    with pytest.raises(ValueError, match="prom-honesty/1"):
        writer.upsert_nodes("T", [NodeIn(tag="x", verdict=verdict)])


def test_writer_passes_admin_verdict_through():
    txs: list = []
    writer = TreeKgWriter(lambda ops: txs.append(ops) or [[]])
    writer.add_node("T", NodeIn(tag="x", verdict="CANONICAL"), [])
    assert txs   # 행정 어휘는 통과


# ── prom-honesty/3: 결합 게이트(set_verdict)의 첫 행동 테스트 ──────────────────────────────
def _judgement_service():
    from server.contexts.tree.judgement_service import JudgementService
    return JudgementService(kg=lambda *a, **k: [], kg_tx=lambda ops: None,
                            hist=lambda *a, **k: None, foundation=lambda n: None,
                            reproducible_for_node=lambda n, t: None)


@pytest.mark.parametrize("verdict", sorted(SCRIPTED_VERDICTS))
def test_set_verdict_403_on_scripted_verdict(verdict):
    """스크립트 판결을 수동 지정하려 하면 403 — 채점은 judge(test_result)만. (회귀 무방비였던 게이트)"""
    svc = _judgement_service()
    with pytest.raises(HTTPException) as exc:
        svc.set_verdict("T", "p1", VerdictIn(verdict=verdict))
    assert exc.value.status_code == 403


def test_set_verdict_gate_allows_admin_vocabulary():
    """행정 판결은 set_verdict 게이트를 통과한다(false-403 회귀가드). 노드 부재 등 다른 사유(404)는 무관 —
    검사 대상은 *어휘 게이트가 403 으로 막지 않는다*는 것뿐."""
    svc = _judgement_service()
    try:
        svc.set_verdict("T", "p1", VerdictIn(verdict="canonical_stage"))
    except HTTPException as exc:
        assert exc.status_code != 403
