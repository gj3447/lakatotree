"""설계감사 H5(완성-후 적대감사 2026-06-26) — set_verdict CANONICAL 승격이 비원자 TOCTOU.

결함: CANONICAL floor 는 read-snapshot(judgement_service.py:181)에서 stands/credibility/qsr 를 읽어
synthesize_promotion 으로 판정한 뒤, 별개 self.kg 세션의 write(:225)가 *스냅샷 재검증 없이* CANONICAL 을
박는다(유일 WHERE 는 old.tag<>$tag). read 와 write 사이에 동시 submit(verdict_source→scripted) 또는
반박 critique(논증 추가→stands 뒤집힘)가 끼면, 이미 stale 한 floor-pass 스냅샷으로 승격된다. M5 는 같은
TOCTOU 를 submit_test_result 에만 닫았고 set_verdict 는 열어뒀다(감사문서 자신이 'set_verdict도 같은 수술' 연기).

수정: CANONICAL write 에 낙관적 동시성 CAS — 스냅샷(verdict/verdict_source/qualitative_self_report +
논증집합 지문)이 write 시점에도 동일할 때만 0행 아닌 결과. 변했으면 0행 → 409(재평가). 메트릭 코어의
원자 CAS(M5) 를 verdict-승격 경로로 미러.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import server.contexts.tree.judgement_service as js_mod
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import VerdictIn

_SNAP_READ = "RETURN cur.verdict AS verdict"
_CANON_WRITE = "SET cur.verdict='CANONICAL'"


class _StatefulKg:
    """set_verdict CANONICAL 경로의 read→write 사이 *동시변경*을 시뮬하는 상태형 KG.

    snapshot read 는 verdict_source=None(scripted 영수증 전) 노드를 돌려준다. write 시점에 race=True 이면
    동시 재채점으로 verdict_source 가 'scripted' 로 바뀐 상태를 보고, write 쿼리의 원자 CAS(스냅샷 param 대조)가
    0행을 내야 한다(가드 없으면 무조건 1행 → 승격). race=False 면 그대로라 1행.
    """

    def __init__(self, *, race: bool) -> None:
        self.race = race
        self.snapshot_source = "scripted"   # read 시점 노드 verdict_source
        self.writes: list[tuple[str, dict]] = []

    def __call__(self, query, **p):
        if _SNAP_READ in query and "HAS_ARGUMENT" in query:        # :181 스냅샷 read
            return [{"verdict": "progressive", "verdict_source": self.snapshot_source,
                     "node_state": "CANONICAL_CANDIDATE",
                     "source_trust": None, "novel_confirmed": True,
                     "qualitative_self_report": False, "args": []}]
        if _CANON_WRITE in query:                                   # :225 원자 CAS write
            self.writes.append((query, p))
            current_source = "engine" if self.race else self.snapshot_source
            # 원자 CAS: write 쿼리가 스냅샷 param(exp_source)을 현재 state 와 대조 — 불일치면 0행.
            if (p.get("exp_source") or "") != (current_source or ""):
                return []
            return [{"tag": p["tag"]}]
        return [{"tag": p.get("tag")}]


def _svc(kg) -> JudgementService:
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [[{"ok": 1}] for _ in ops],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    svc._eigentrust_credibility = lambda *a, **k: {}   # KG 호출 회피(floor 입력은 아래서 monkeypatch)
    return svc


def _force_floor_pass(monkeypatch):
    """floor 자체가 아니라 *원자 write* 를 시험 — synthesize_promotion 을 ok 로 고정."""
    monkeypatch.setattr(js_mod, "synthesize_promotion",
                        lambda **k: {"ok": True, "reasons": [], "gates": {}})


def test_set_verdict_canonical_is_atomic_cas(monkeypatch):
    """동시변경 없으면(원자 CAS 통과) 정상 승격 — 그리고 write 가 스냅샷 재검증 절을 *구조적으로* 들고 있다."""
    _force_floor_pass(monkeypatch)
    kg = _StatefulKg(race=False)
    out = _svc(kg).set_verdict("T", "n", VerdictIn(verdict="CANONICAL"))
    assert out["ok"] is True
    assert kg.writes, "CANONICAL write 가 실행되지 않음"
    wq = kg.writes[0][0]
    # ★구조적(non-vacuous): write 가 스냅샷(verdict/source/qsr) 원자 CAS + 논증집합 지문을 실제로 포함
    assert "$exp_verdict" in wq and "$exp_source" in wq and "$exp_qsr" in wq, \
        "CANONICAL write 에 스냅샷 재검증 CAS param 누락 → TOCTOU 미봉쇄"
    assert "arg_fp" in wq, "논증집합 지문(arg_fp) 재검증 누락 — 반박 critique race 미봉쇄"
    assert "RETURN cur.tag" in wq, "0행(동시변경) 탐지를 위한 RETURN 누락"


def test_set_verdict_canonical_409_on_concurrent_change(monkeypatch):
    """read→write 사이 동시 재채점(verdict_source→scripted)이 끼면 원자 CAS 0행 → 409(stale 승격 차단)."""
    _force_floor_pass(monkeypatch)
    kg = _StatefulKg(race=True)
    with pytest.raises(HTTPException) as e:
        _svc(kg).set_verdict("T", "n", VerdictIn(verdict="CANONICAL"))
    assert e.value.status_code == 409


def test_non_canonical_set_verdict_unaffected(monkeypatch):
    """과잉차단 회귀가드: CANONICAL 이 아닌 행정 verdict 지정은 원자 CAS 경로를 타지 않는다."""
    _force_floor_pass(monkeypatch)
    kg = _StatefulKg(race=True)   # race 여도 무관 — CANONICAL 분기만 CAS
    out = _svc(kg).set_verdict("T", "n", VerdictIn(verdict="superseded"))
    assert out["ok"] is True
