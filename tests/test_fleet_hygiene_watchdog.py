"""fleet hygiene watchdog 가드 — 시계열/정체검출/경보의 순수 로직 (네트워크·ntfy 0).

  guard_mechanism : 정체(카운터 3회 연속 불변 & >0) 와 신규 abandon 발화가 검출된다 —
                    07-25→07-28 침묵 정체(finding_ed8257ad6a2e6bf1)를 잡을 수 있는 최소 기계.
  guard_defect    : 음성 오라클 — 카운터가 움직이면(이행 진행) 정체 경보 금지, 0 불변도 금지
                    (완치 상태를 정체로 오보 금지), abandon 소멸은 경보 아님(과잉 경보 회귀가드).
# KG: plan-lktadv-p2-fleet-hygiene-watchdog-20260728
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fleet_hygiene_watchdog as wd  # noqa: E402


def _snap(green=19, close=7, ep_trees=(), laudan=0, errors=()):
    return dict(ts="t", tree_count=91, tier_dist={"notebook": 31},
                scrape_errors=list(errors),
                unreceipted_green_total=green, unreceipted_close_total=close,
                alerts_total=5, laudan_abandon_total=laudan,
                eprocess_abandon_trees=list(ep_trees), per_tree={})


def test_stall_detected_after_n_identical_snapshots():
    hist = [_snap(), _snap()]
    findings = wd.detect(_snap(), hist, stall_n=3)
    assert any("정체" in f and "unreceipted_green_total=19" in f for f in findings), findings
    assert any("unreceipted_close_total=7" in f for f in findings), findings


def test_no_stall_when_counter_moves_or_zero():
    hist = [_snap(green=19, close=9), _snap(green=15, close=8)]
    assert not any("정체" in f for f in wd.detect(_snap(green=12, close=6), hist, stall_n=3)), \
        "카운터가 움직이면(이행 진행) 정체 경보 금지"
    hist0 = [_snap(green=0, close=0), _snap(green=0, close=0)]
    assert not any("정체" in f for f in wd.detect(_snap(green=0, close=0), hist0, stall_n=3)), \
        "완치(0 불변)를 정체로 오보 금지"


def test_new_eprocess_abandon_fires_and_disappearance_is_silent():
    hist = [_snap(ep_trees=["A"])]
    up = wd.detect(_snap(ep_trees=["A", "B"]), hist, stall_n=3)
    assert any("신규 발화" in f and "B" in f and "A" not in f.split(":")[1] for f in up), up
    down = wd.detect(_snap(ep_trees=[]), hist, stall_n=3)
    assert not any("신규 발화" in f for f in down), "소멸은 경보 아님 (과잉 경보 회귀가드)"


def test_laudan_increase_fires_decrease_silent():
    hist = [_snap(laudan=2)]
    assert any("laudan" in f for f in wd.detect(_snap(laudan=4), hist, stall_n=3))
    assert not any("laudan" in f for f in wd.detect(_snap(laudan=1), hist, stall_n=3))


def test_scrape_errors_are_counted_not_silent():
    findings = wd.detect(_snap(errors=["T1: boom"]), [], stall_n=3)
    assert any("스크레이프 실패 1건" in f for f in findings)


def test_run_once_appends_jsonl_and_dry_run_never_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "scrape_fleet", lambda: _snap())
    posted = []
    monkeypatch.setattr(wd, "notify", lambda *a, **k: posted.append(1) or True)
    for _ in range(3):
        out = wd.run_once(tmp_path, dry_run=True, stall_n=3)
    lines = (tmp_path / "snapshots.jsonl").read_text().splitlines()
    assert len(lines) == 3 and json.loads(lines[0])["unreceipted_green_total"] == 19
    assert out["findings"] and not posted, "dry-run 은 발송 금지 + 3회째 정체 검출"


def test_run_once_posts_on_findings(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "scrape_fleet", lambda: _snap())
    posted = []
    monkeypatch.setattr(wd, "notify", lambda f, s, ntfy_url=None: posted.append(f) or True)
    for _ in range(3):
        wd.run_once(tmp_path, dry_run=False, stall_n=3)
    assert posted and any("정체" in x for x in posted[-1]), posted


def test_calibration_gates_unreceipted_and_orders_deterministically():
    """ADR D2 가드 — calibration 은 FORCEFUL 판정 결과만 계상 + judged_at 결정론 정렬.
    (raw novel_confirmed 소비는 무영수증 self-report 로 판관 보정을 오염시켰다.)"""
    from lakatos.verdicts import FORCEFUL_SOURCES
    from server.contexts.tree.programme_service import ProgrammeService
    captured = {}

    def kg(query, **params):
        captured['query'] = query
        captured['params'] = params
        return [dict(p=0.8, o=True), dict(p=0.3, o=False)]

    svc = object.__new__(ProgrammeService)
    svc.kg = kg
    out = svc.calibration('T')
    assert 'ORDER BY e.judged_at' in captured['query'], '결정론 정렬 필수(순차 소비 전제)'
    assert 'verdict_source IN $forceful' in captured['query']
    assert set(captured['params']['forceful']) == set(FORCEFUL_SOURCES)
    assert out['n'] == 2 and 'self-report' in out['note']
