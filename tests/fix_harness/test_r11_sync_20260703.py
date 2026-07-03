"""R11-SYNC — G4 잔여: staging 격리·명명 레지스트리·notebook 스탬프 가드 (후속 PROM 2026-07-03).

  guard_defect(음성)     : test_naming_registry_fail_loud_and_notebook_stamp
        — ①미등록 프리픽스/허브 = fail-loud(명명 드리프트 봉합 — 한계비용 0) ②미러 행이 손기록
          verdict_source 를 FORCEFUL 로 위조해도 engine_scored 는 파생(진위 KG 판정) + assurance_tier=
          'notebook' 스탬프(공유 KG 미러는 엔진 판결이 아니라 노트북 tier — 소급 CANONICAL 위장 봉쇄).
  guard_mechanism(양성)  : test_staging_quarantine_atomic_migrate
        — receive-pack 격리 이식: staging 배치는 :LakatosNodeStaging{import_batch} 로만 write(라이브
          라벨 불변) → 전행 content-sha verify green 일 때만 *단일 Cypher statement* 로 원자 migrate.
          변조 배치는 격리 잔존(부분 공개 없음 — apoc 없이 단일 statement 만 원자).

# KG: LakatosTree_GitAbsorption_20260702 / followup-R11-sync
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    'sync_lakatos_programme_to_kg', ROOT / 'scripts' / 'sync_lakatos_programme_to_kg.py')
assert _spec and _spec.loader
sync = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sync   # @dataclass 의 __module__ 해석용(로더 전 등록)
_spec.loader.exec_module(sync)


# ── guard_defect (음성): 명명 드리프트 + 미러 위조 봉쇄 ──────────────────────────────────────
def test_naming_registry_fail_loud_and_notebook_stamp():
    # (1) 등록된 허브는 정본 프리픽스로 resolve.
    assert sync.resolve_prefix(sync.DEFAULT_HUB_NAME) == sync.DEFAULT_NODE_PREFIX
    # (2) 미등록 허브 = fail-loud(조용한 임의 프리픽스 금지 — 드리프트 봉합).
    with pytest.raises(sync.NamingRegistryError):
        sync.resolve_prefix('LakatosTree_Unregistered_Hub_9999')
    # (3) 미러 행: 손기록 verdict_source 를 'scripted'(FORCEFUL)로 위조해도 assurance_tier='notebook'
    #     스탬프 — 공유 KG 미러는 엔진 판결이 아니라 노트북 tier(소급 CANONICAL 위장 봉쇄).
    row = sync._node_row({'tag': 'x', 'verdict': 'CANONICAL', 'verdict_source': 'scripted'},
                         name='lk-bpc-ac-x', branch='canonical_path')
    assert row['assurance_tier'] == 'notebook', '미러 행에 notebook tier 스탬프 부재'
    # engine_scored 는 파생이지만 — 미러는 실제 서버 원장(receipt)이 아니므로 content_sha 로만 무결성.
    assert 'content_sha' in row and row['assurance_tier'] in sync._MIRROR_TIER_ALLOWED


# ── guard_mechanism (양성): staging 격리 + 원자 migrate ─────────────────────────────────────
def test_staging_quarantine_atomic_migrate():
    rows = [dict(name='lk-bpc-ac-a', tag='a', content_sha='deadbeef00000000'),
            dict(name='lk-bpc-ac-b', tag='b', content_sha='cafebabe00000000')]
    batch = 'sync-20260703-test'
    # (1) staging write = :LakatosNodeStaging{import_batch} 라벨만(라이브 :LakatosNode 불변).
    stmts = sync.build_staging_cypher(rows, import_batch=batch, hub_name=sync.DEFAULT_HUB_NAME)
    joined = ' '.join(c for c, _ in stmts)
    assert ':LakatosNodeStaging' in joined and 'import_batch' in joined
    assert ':LakatosNode {' not in joined and 'MERGE (n:LakatosNode)' not in joined, \
        'staging 이 라이브 라벨을 건드림(격리 위반)'
    # (2) migrate = *단일* statement(apoc 없이 원자 — 부분 공개 불가).
    migrate = sync.build_migrate_cypher(import_batch=batch, hub_name=sync.DEFAULT_HUB_NAME)
    assert isinstance(migrate, tuple) and len(migrate) == 2, 'migrate 가 단일 (cypher, params) 아님'
    mc = migrate[0]
    assert mc.count(';') == 0, 'migrate 가 멀티 statement(원자성 훼손)'
    assert ':LakatosNodeStaging' in mc and 'REMOVE' in mc and ':LakatosNode' in mc, \
        'migrate 가 staging→live 라벨 스왑을 안 함'
    assert '$import_batch' in mc and migrate[1]['import_batch'] == batch
    # (3) migrate 는 verify 게이트를 계약으로 — verify 실패 배치는 migrate 금지(가드 함수 존재).
    assert sync.migrate_is_gated_by_verify() is True
