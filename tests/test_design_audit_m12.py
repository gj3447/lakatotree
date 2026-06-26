"""설계감사 M12(minor, 완성-후 적대감사 2026-06-26) — set_verdict 의 former_canonical 강등이
verdict_source='engine' 을 누락.

결함: set_verdict CANONICAL 승격이 직전 canonical 을 `SET old.verdict='former_canonical'` 로 강등하면서
old.verdict_source 를 안 건드린다 → old 는 CANONICAL 시절의 source('admin')를 그대로 유지. 그러나 다른 모든
강등 경로(app.py:603, evidence_claim_service.py:143, certify.py)는 verdict_source='engine' 을 명시한다.
former_canonical 은 PROGRESS_VERDICTS 라 force_of('former_canonical','admin')는 여전히 SELF_REPORT 로 세어져
메트릭 집계 결과는 불변(그래서 minor)이나, '엔진 강등 vs 인간 admin' provenance 귀속이 이 경로만 틀린다.

수정: 강등 SET 에 old.verdict_source='engine' 추가(다른 강등경로와 정합).
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import server.contexts.tree.judgement_service as js_mod
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import VerdictIn


class _Kg:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def __call__(self, query, **p):
        if "RETURN cur.verdict AS verdict" in query and "HAS_ARGUMENT" in query:
            return [{"verdict": "progressive", "verdict_source": None, "source_trust": None,
                     "novel_confirmed": True, "qualitative_self_report": False, "args": []}]
        if "SET cur.verdict='CANONICAL'" in query:
            self.writes.append(query)
            return [{"tag": p["tag"]}]
        return [{"tag": p.get("tag")}]


def test_former_canonical_demotion_attributes_engine_source(monkeypatch):
    """CANONICAL 승격이 직전 canonical 을 강등할 때 verdict_source='engine' 으로 귀속(provenance 정합)."""
    monkeypatch.setattr(js_mod, "synthesize_promotion",
                        lambda **k: {"ok": True, "reasons": [], "gates": {}})
    kg = _Kg()
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [[{"ok": 1}] for _ in ops],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    svc._eigentrust_credibility = lambda *a, **k: {}
    svc.set_verdict("T", "n", VerdictIn(verdict="CANONICAL"))
    assert kg.writes, "CANONICAL write 미실행"
    wq = kg.writes[0]
    assert "old.verdict='former_canonical'" in wq, "강등 SET 자체가 없음"
    # ★구조적(non-vacuous): 강등에 engine 출처 귀속이 실제로 포함 (수정 없으면 RED)
    assert "old.verdict_source='engine'" in wq, \
        "former_canonical 강등이 verdict_source='engine' 누락 → provenance 귀속 불일치"
