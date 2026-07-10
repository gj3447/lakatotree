"""OOPTDD emit-adapter — jp1 판관 정체성(engine_rule_sha) 영수증 (이벤트 리터럴은 이 파일에만).

verify(backend, cid)가 *실코드* 구동(재구현 금지):
  (A) v2 봉인: 실 receipt_content_sha 로 v2 mint → engine_rule_sha 봉인·재유도 일치
  (B) carve-out: v1 입력(부재/None)이 변경-전 실측 골든과 바이트 동일
  (C) 스윕: 실 JudgementService.demote_stale_canonical(fake KG) — v1 익명 CANONICAL 강등 ≥1
  (D) 음성 오라클: strip/주입 위조 recompute 검출 + floor 무력화 시 강등 0(load-bearing 증명)

# KG: LakatosTree_JudgeProprioception_20260708 / jp1-engine-rule-sha
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

from lakatos.engine_identity import ENGINE_RULE_SHA  # noqa: E402
from lakatos.verdicts import receipt_content_sha  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402

_BASE = {"tree": "T", "tag": "n", "target_id": "n", "verdict": "progressive",
         "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
         "novel_confirmed": True, "lakatos_status": "progressive",
         "judged_at": "2026-07-08T00:00:00+00:00", "judge_script_sha": "0" * 64,
         "prev_receipt_sha": None, "measurement_grade": "client_asserted"}
_V1_GOLDEN_BASE = "0fc94e9ab94d06bdc5ea857b2d432eb01e45ccfa79ab3e445a89d7f18fcfd2bf"


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.jp1.engine_identity", "event": name, **attrs}


class _SweepKg:
    def __init__(self):
        self.rows = [{"tag": "legacy_v1", "prev_rsha": "p1", "ers": None, "vur": True}]
        self.demoted = []

    def __call__(self, query, **p):
        if "verdict:'CANONICAL'" in query and "RETURN e.tag AS tag" in query:
            return [dict(r) for r in self.rows]
        if "SET e.verdict='former_canonical'" in query:
            if (self.rows[0].get("prev_rsha") or "") != (p.get("prev") or ""):
                return []
            self.demoted.append(p["tag"])
            return [{"tag": p["tag"]}]
        return []


def _svc(kg):
    return JudgementService(kg=kg, kg_tx=lambda ops: [], hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def verify(backend, cid):
    # (A) v2 봉인 + 재유도 일치
    v2f = dict(_BASE, engine_rule_sha=ENGINE_RULE_SHA)
    v2sha = receipt_content_sha(v2f)
    assert v2sha != _V1_GOLDEN_BASE and receipt_content_sha(dict(v2f)) == v2sha
    backend.ship([_ev(cid, "jp1_engine_identity_sealed", v2_sha=v2sha[:12])])

    # (B) carve-out 바이트 안정(부재 == 명시 None == 변경-전 골든)
    assert receipt_content_sha(_BASE) == _V1_GOLDEN_BASE
    assert receipt_content_sha(dict(_BASE, engine_rule_sha=None)) == _V1_GOLDEN_BASE
    backend.ship([_ev(cid, "jp1_v1_carveout_stable", golden=_V1_GOLDEN_BASE[:12])])

    # (C) 스윕: v1 익명 CANONICAL 이 재심 강등 ≥1 (novel 오라클 기제)
    kg = _SweepKg()
    run = _svc(kg).demote_stale_canonical("T", dry_run=False)
    assert run["demoted"] == ["legacy_v1"], run
    backend.ship([_ev(cid, "jp1_stale_canonical_demoted", demoted=len(run["demoted"]))])

    # (D) 음성 오라클 — 위조 검출 + floor load-bearing
    stripped_matches = receipt_content_sha(dict(v2f, engine_rule_sha=None)) == v2sha
    injected_matches = receipt_content_sha(dict(_BASE, engine_rule_sha="f" * 64)) == _V1_GOLDEN_BASE
    assert not stripped_matches and not injected_matches, "위조가 recompute 를 통과(봉인 구멍)"
    # floor 무력화(전체 허용) 재현: effective_floor 를 '모든 sha 포함' 으로 치환하면 강등 0 —
    # 강등이 floor 대조에 인과적으로 매달림(vacuous green 차단). 소비 사이트 네임스페이스를 패치.
    import server.contexts.tree.judgement_service as js_mod

    class _Universe(frozenset):
        def __contains__(self, item):
            return True

    orig = js_mod.effective_floor
    try:
        js_mod.effective_floor = lambda *a, **k: _Universe()
        kg2 = _SweepKg()
        run2 = _svc(kg2).demote_stale_canonical("T", dry_run=False)
        assert run2["demoted"] == [], "floor 무력화에도 강등 발생 — 강등이 floor 와 무관(가짜 기제)"
    finally:
        js_mod.effective_floor = orig
    backend.ship([_ev(cid, "jp1_negative_oracle", checks_load_bearing=True)])
