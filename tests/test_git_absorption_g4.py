"""git-흡수 G4 landed guards — KG 미러 provenance 완전성 + 행별 content-sha verify (S4 봉합).

  guard_defect(개선축)     : test_tampered_mirror_row_fails_content_verify
        — 미러 행 변조/부재가 카운트 verify 는 통과해도 *행별 content-sha 재유도*가 잡는다(git commit-graph verify). ✅
  guard_mechanism(novel축) : test_mirror_exports_full_provenance_and_rederives_per_row
        — 미러 행이 provenance 튜플(verdict_source/node_state/judged_at) 전량 export + engine_scored 는
          *파생 전용*(FORCEFUL 출처일 때만 True, 손기록 불가) + content_sha 재유도 계약. ✅

남은 슬라이스(범위 밖 명시): source-of-truth 를 python 모듈→엔진 DB 로 뒤집는 engine→KG projection.
# KG: LakatosTree_GitAbsorption_20260702 / G4_kg_mirror_content_verify
"""
from __future__ import annotations

import importlib

sync = importlib.import_module('scripts.sync_lakatos_programme_to_kg')


# ── guard_defect (개선축) — 착륙 ─────────────────────────────────────────────────────────
def test_tampered_mirror_row_fails_content_verify():
    """카운트는 맞아도 행 내용 변조/부재를 content-sha 재유도가 검출(git commit-graph verify)."""
    src = [
        sync._node_row({'tag': 'a', 'verdict': 'canonical_stage'}, name='lk-a', branch='canonical_path'),
        sync._node_row({'tag': 'b', 'verdict': 'canonical_stage'}, name='lk-b', branch='canonical_path'),
    ]
    # 무결 미러: KG 행이 소스 content_sha 를 그대로 지님 → drift 0.
    clean_kg = {r['name']: {'name': r['name'], 'content_sha': r['content_sha']} for r in src}
    assert sync.verify_content(src, clean_kg) == []

    # 변조: 한 행의 sha 를 조작 → content_sha_mismatch 검출(카운트는 여전히 2==2).
    tampered = dict(clean_kg)
    tampered['lk-b'] = {'name': 'lk-b', 'content_sha': 'deadbeefdeadbeef'}
    drift = sync.verify_content(src, tampered)
    assert len(drift) == 1 and drift[0]['reason'] == 'content_sha_mismatch', drift

    # 부재: KG 에 행이 없음 → missing_in_kg 검출.
    missing = {'lk-a': clean_kg['lk-a']}
    drift2 = sync.verify_content(src, missing)
    assert any(d['reason'] == 'missing_in_kg' and d['name'] == 'lk-b' for d in drift2), drift2


# ── guard_mechanism (novel축) — 착륙 ─────────────────────────────────────────────────────
def test_mirror_exports_full_provenance_and_rederives_per_row():
    """provenance 튜플 전량 export + engine_scored 파생 전용 + content_sha 재유도 계약."""
    # (1) provenance 튜플이 행에 존재(S4: 전엔 verdict 만 export 해 force_of 표현 불가였음).
    scripted = sync._node_row(
        {'tag': 's', 'verdict': 'progressive', 'verdict_source': 'scripted',
         'node_state': 'CANONICAL_CANDIDATE', 'judged_at': '2026-07-02T00:00:00Z'},
        name='lk-s', branch='canonical_path')
    for k in ('verdict_source', 'node_state', 'judged_at', 'engine_scored', 'content_sha'):
        assert k in scripted, f'{k} 미export (S4 provenance 상실)'

    # (2) engine_scored 는 *파생* — verdict_source 가 영수증(FORCEFUL)일 때만 True. 손기록 경로 없음.
    assert scripted['engine_scored'] is True                       # scripted = FORCEFUL
    struct = sync._node_row({'tag': 'c', 'verdict': 'canonical_stage'}, name='lk-c', branch='canonical_path')
    assert struct['engine_scored'] is False                        # verdict_source 없음 → 파생 False(위조 불가)
    struct_admin = sync._node_row(
        {'tag': 'd', 'verdict': 'CANONICAL', 'verdict_source': 'admin'}, name='lk-d', branch='canonical_path')
    assert struct_admin['engine_scored'] is False                  # admin = 구조(STRUCTURAL), 영수증 아님

    # (3) content_sha 재유도 계약: 같은 필드 → 같은 sha; 한 필드만 바뀌어도 sha 변함(민감).
    again = sync._node_row(
        {'tag': 's', 'verdict': 'progressive', 'verdict_source': 'scripted',
         'node_state': 'CANONICAL_CANDIDATE', 'judged_at': '2026-07-02T00:00:00Z'},
        name='lk-s', branch='canonical_path')
    assert again['content_sha'] == scripted['content_sha']         # 결정론
    flipped = dict(scripted, verdict='rejected')
    assert sync._node_content_sha(flipped) != scripted['content_sha']  # 내용 변하면 sha 변함
