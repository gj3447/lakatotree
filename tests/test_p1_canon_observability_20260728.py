"""P1 canon-lag 관측 가드 (plan-lktadv-p1-canon-lag-observability-20260728).

원사고 계보: jp4 = 30커밋 stale CA 서명 → G2 = /version stale 자기보고(부팅 vs 자기 디스크).
07-28 실측(finding_edc0459fcc4b532e/1c1d0d56f91b6672): 그 stale 은 자기참조 1-hop 프레임이라
라이브가 origin 의 보안 remediation 6커밋 뒤에서 stale:false 초록을 켰다. 봉합 = 감지 확장이
아니라 **overclaim 제거**(scope 명시 + canon_lag 정직 unknown) + freshness gate 자세 노출.

  guard_defect     : stale 필드가 scope 무명시로 'canon 대비 신선'으로 오독되던 결함 —
                     stale_scope/canon_lag 부재면 RED.
  guard_mechanism  : freshness gate 무장 여부가 어떤 GET 표면에도 없던 결함(built-then-disarmed
                     판별 불가) — /version 이 게이트 자세를 실보고해야 GREEN.
# KG: plan-lktadv-p1-canon-lag-observability-20260728 / finding_042e2ea2a6e3b55d
"""
from __future__ import annotations

import os

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from server import version as ver  # noqa: E402


def test_version_exposes_stale_scope_and_honest_canon_lag():
    """stale 의 referent 를 계약에 명시: process_vs_disk 1-hop 뿐 — canon(origin) 대비는
    측정하지 않으며 'unknown' 으로 정직 공시(감지 없이 신선 주장 금지). 대조는 외부 watchdog(P2) 몫."""
    v = ver.served_version()
    assert v['stale_scope'] == 'process_vs_disk'
    assert v['canon_lag'] == 'unknown'


def test_version_reports_freshness_gate_posture(monkeypatch):
    """/version 이 판관 신선도 게이트 무장 여부를 실보고 — env 자세와 1:1.
    (기본 ON flip 후: 미설정=on, 명시적 거짓만 opt_out.)"""
    from server.app import _freshness_gate_posture
    monkeypatch.delenv('LAKATOS_JUDGE_FRESHNESS_GATE', raising=False)
    assert _freshness_gate_posture() == 'on'
    monkeypatch.setenv('LAKATOS_JUDGE_FRESHNESS_GATE', '0')
    assert _freshness_gate_posture() == 'opt_out'
    monkeypatch.setenv('LAKATOS_JUDGE_FRESHNESS_GATE', 'true')
    assert _freshness_gate_posture() == 'on'


def test_version_endpoint_carries_gate_posture(monkeypatch):
    """엔드포인트 조립까지 관통 — served_version 필드와 gate 자세가 한 응답에 동봉."""
    monkeypatch.delenv('LAKATOS_JUDGE_FRESHNESS_GATE', raising=False)
    from server.app import version
    out = version()
    assert out['freshness_gate'] == 'on'
    assert out['stale_scope'] == 'process_vs_disk'
