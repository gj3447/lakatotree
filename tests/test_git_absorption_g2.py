"""git-흡수 G2 landed guards — 서빙 신원 관측가능성 + 감독 latch 러너 (S5 봉합).

  guard_defect(개선축)     : test_served_code_sha_is_observable_at_version_endpoint
        — /version 이 부팅 커밋 sha 를 노출하고 disk HEAD 와 비교해 stale 을 자기보고(6커밋 stale 감지불가 봉합). ✅
  guard_mechanism(novel축) : test_maintenance_runner_latches_on_failure_and_lock
        — 유지보수 러너가 실패를 latch 해 재실행 차단 + lock 경합/실패를 무음 아니게 기록(git gc 패턴). ✅

두 축 독립·둘 다 착륙 → judge() 가 G2 를 progressive 로 채점.
# KG: LakatosTree_GitAbsorption_20260702 / G2_version_supervised_serving
"""
from __future__ import annotations

import importlib
import itertools
import os

from server.maintenance import MaintenanceRunner


def _load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


# ── guard_defect (개선축) — 착륙 ─────────────────────────────────────────────────────────
def test_served_code_sha_is_observable_at_version_endpoint():
    """/version 이 부팅 커밋 sha·부팅시각·디스크 HEAD·stale 을 노출 → 프로세스 코드 신원이 관측가능(S5 봉합)."""
    from fastapi.testclient import TestClient

    app = _load_app()
    r = TestClient(app.app).get('/version')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['boot_git_sha'] and body['boot_git_sha'] != 'unknown', body
    assert 'boot_time' in body and 'disk_head_sha' in body and 'stale' in body, body


def test_version_reports_stale_when_boot_sha_differs_from_disk(monkeypatch):
    """stale 자기보고: 부팅 스냅샷 sha 가 현 디스크 HEAD 와 다르면 stale=True — 6커밋 stale 서빙을 배포프로브가 탐지."""
    import server.version as ver

    monkeypatch.setattr(ver, 'BOOT_GIT_SHA', 'aaaaaaa')          # 부팅은 옛 커밋
    monkeypatch.setattr(ver, 'disk_head_sha', lambda: 'bbbbbbb')  # 디스크는 전진
    v = ver.served_version()
    assert v['stale'] is True, v
    # 같은 sha 면 stale=False(과잉경보 아님)
    monkeypatch.setattr(ver, 'disk_head_sha', lambda: 'aaaaaaa')
    assert ver.served_version()['stale'] is False


# ── guard_mechanism (novel축) — 착륙 ─────────────────────────────────────────────────────
def _runner(tasks, *, latch=None, lock=None, alive=True, clock=None):
    clk = clock or itertools.count(1000.0, 1.0)
    return MaintenanceRunner(
        tasks=tasks,
        lock_store=(lock if lock is not None else {}),
        latch_store=(latch if latch is not None else {}),
        now=lambda: next(clk),
        host='h1', pid=42,
        is_alive=lambda _pid: alive,
    )


def test_maintenance_runner_latches_on_failure_and_lock():
    """실패는 latch → 다음 실행 차단(clear 전까지), 잔여 태스크 skip, 모든 skip 기록(무음 아님)."""
    calls = {'a': 0, 'b': 0}

    def a():
        calls['a'] += 1

    def boom():
        raise RuntimeError('rebuild_verify mismatch')

    def b():
        calls['b'] += 1

    latch: dict = {}
    r = _runner({'a': a, 'boom': boom, 'b': b}, latch=latch)

    out1 = r.run()
    assert out1.ran == ['a'], out1                       # a 실행
    assert out1.latched == 'boom', out1                  # boom 이 latch 걸음
    assert ('after_latch', 'b') in out1.skipped, out1    # b 는 latch 이후 skip(무음 아님)
    assert r.is_latched()

    out2 = r.run()                                        # 재실행: latch 가 통째로 차단
    assert out2.ran == [], out2
    assert any(reason == 'latched' for reason, _ in out2.skipped), out2

    assert r.clear_latch() is True                        # 사람이 acknowledge
    calls['a'] = 0
    out3 = r.run()
    assert 'a' in out3.ran and 'boom' in [out3.latched]   # clear 후 재실행(boom 이 다시 latch)


def test_maintenance_lock_yields_to_live_owner_but_steals_dead():
    """lock: 살아있는 타 소유자에겐 양보(skip 기록), 죽은 pid/stale 은 탈취."""
    # 살아있는 타 프로세스가 lock 보유 → skip(무음 아님)
    live_lock = {'maintenance': {'host': 'h1', 'pid': 999, 'acquired_at': 1000.0}}
    r_live = _runner({'x': lambda: None}, lock=live_lock, alive=True)
    out = r_live.run()
    assert out.ran == [] and any(reason == 'lock_contended' for reason, _ in out.skipped), out

    # 같은 host 의 죽은 pid → 탈취해 실행
    dead_lock = {'maintenance': {'host': 'h1', 'pid': 999, 'acquired_at': 1000.0}}
    ran = {'x': 0}
    r_dead = _runner({'x': lambda: ran.__setitem__('x', ran['x'] + 1)}, lock=dead_lock, alive=False)
    out = r_dead.run()
    assert out.ran == ['x'], out
    assert ran['x'] == 1
