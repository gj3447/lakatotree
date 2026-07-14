"""OOPTDD emit-adapter — jp4 CA fail-closed 영수증 (이벤트 리터럴은 이 파일에만).

verify(backend, cid)가 실 JudgementService.submit_test_result 를 fake kg/kg_tx + 주입 provider 로 구동:
  (A) stale provider → progressive-급 제출이 partial/provisional_stale_engine 강등 + 신원 스탬프
  (B) fresh provider → progressive 무변경 통과 + judged_by_boot_git_sha 스탬프
  (C) 음성 오라클 — *소비 사이트*(judgement_service.engine_freshness_fires, by-name import 바인딩)를
      무조건-False 로 절제하면 같은 stale 제출이 progressive 부활 = 게이트가 일하고 있음을 검출,
      try/finally 원복 후 강등 재현 확인 (vacuous green 차단)

# KG: LakatosTree_JudgeProprioception_20260708 / jp4-ca-fail-closed
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import server.contexts.tree.judgement_service as js_mod  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import TestResultIn as Result  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.jp4.ca_fail_closed", "event": name, **attrs}


def _stale():
    return {"stale_code": True, "capable": True, "missing": [],
            "boot_git_sha": "aaaa111", "disk_head_sha": "bbbb222"}


def _fresh():
    return {"stale_code": False, "capable": True, "missing": [],
            "boot_git_sha": "cccc333", "disk_head_sha": "cccc333"}


def _drive(provider):
    cap = []

    def kg(query, **p):
        if "pred_metric AS m" in query:
            return [{"m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio",
                     "novel": "novel claim", "vsrc": None,
                     "nmet": "novelaxis", "ndir": "higher", "nthr": 1.0, "psha": None,
                     "closes": None, "n_opened": 0, "pred_registered_at": "2026-07-10",
                     "node_state": "PREDICTED", "judged_at": None,
                     "existing_metric_value": None, "existing_verdict": None,
                     "existing_lstat": None, "prev_receipt_sha": None,
                     "hard_core": "", "require_novel_anchor": False,
                     "assurance_tier": None, "attestor_dids": None}]
        return []

    svc = JudgementService(kg=kg, kg_tx=lambda ops: (cap.append(ops), [[{"claimed": "n"}] for _ in ops])[1],
                           hist=lambda *a, **k: None, foundation=lambda n: None,
                           reproducible_for_node=lambda n, t: None, engine_freshness=provider)
    svc.submit_test_result("T", "n", Result(metric_value=1.0, script="inline", novel_measured=1.0))
    return cap[0][0][1]


def verify(backend, cid):
    # (A) stale → provisional 강등 + 신원 스탬프
    p = _drive(_stale)
    assert p["v"] == "partial" and p["lstat"] == "provisional_stale_engine", p
    assert p["efresh"] == "stale_code" and p["boot_sha"] == "aaaa111", p
    backend.ship([_ev(cid, "jp4_stale_progressive_demoted", boot=p["boot_sha"])])

    # (B) fresh → freshness 강등 없이 PU 통과 + 스탬프
    p2 = _drive(_fresh)
    assert (p2["v"] == "progressive_unverified" and p2["efresh"] == "fresh"
            and p2["boot_sha"] == "cccc333"), p2
    backend.ship([_ev(cid, "jp4_fresh_passthrough_stamped", boot=p2["boot_sha"])])

    # (C) 음성 오라클 — 소비 사이트 절제 → 결함 부활 검출, 원복 → 강등 재현
    orig = js_mod.engine_freshness_fires
    try:
        js_mod.engine_freshness_fires = lambda f: False       # 게이트 절단(결함 재주입)
        p3 = _drive(_stale)
        revived = p3["v"] == "progressive_unverified"         # 절제된 게이트가 결함을 되살림 = 검출
    finally:
        js_mod.engine_freshness_fires = orig
    assert revived, "게이트 절제에도 강등 유지 — 검사가 다른 곳에 위장(음성 오라클 실패)"
    p4 = _drive(_stale)
    assert p4["lstat"] == "provisional_stale_engine", "원복 후 강등 미복원"
    backend.ship([_ev(cid, "jp4_negative_defect_detected", checks_load_bearing=True)])
