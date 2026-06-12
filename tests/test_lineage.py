"""데이터 계보 TDD — 버퍼는 임시, 완성본은 root data 서 재생성.
# KG: span_lakatotree_lineage
"""
import pytest
from lakatos.lineage import (Derivation, by_output, roots, rebuild_plan,
                             reproducibility_gaps, stale_inputs, is_reproducible)

# root(source) → cache(buffer) → final
ROOT = Derivation(output='raw://experiment/lot-0060', output_sha='raw0', producer='', producer_sha='',
                  inputs=[], params={}, kind='source', ts='t0')
CACHE = Derivation(output='cache://observations-0060', output_sha='cache0',
                   producer='extract_observations.py', producer_sha='sha-extract',
                   inputs=[('raw://experiment/lot-0060', 'raw0')],
                   params={'stride': 2}, kind='intermediate', ts='t1')
FINAL = Derivation(output='artifact://model-v22', output_sha='model0',
                   producer='solve_model.py', producer_sha='sha-solve',
                   inputs=[('cache://observations-0060', 'cache0')],
                   params={'lots': 6}, kind='final', ts='t2')

def test_roots_trace_to_root_data():
    bo = by_output([ROOT, CACHE, FINAL])
    assert roots('artifact://model-v22', bo) == {'raw://experiment/lot-0060'}

def test_rebuild_plan_topo_order():
    bo = by_output([ROOT, CACHE, FINAL])
    plan = rebuild_plan('artifact://model-v22', bo)
    outs = [d.output for d in plan]
    assert outs.index('cache://observations-0060') < outs.index('artifact://model-v22')
    assert 'raw://experiment/lot-0060' not in outs   # source 는 재생성 안 함

def test_reproducibility_gap_when_link_missing():
    # 버퍼 derivation 없으면 완성본 재생성 불가 (계보 끊김)
    bo = by_output([ROOT, FINAL])   # CACHE 누락
    gaps = reproducibility_gaps('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})
    assert 'cache://observations-0060' in gaps
    assert not is_reproducible('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})

def test_full_chain_reproducible():
    bo = by_output([ROOT, CACHE, FINAL])
    assert is_reproducible('artifact://model-v22', bo, sources={'raw://experiment/lot-0060'})

def test_stale_when_input_changed():
    # root data 가 바뀌면(sha 변경) 하류 버퍼가 stale → 완성본 재생성 필요
    bo = by_output([ROOT, CACHE, FINAL])
    bad = stale_inputs(CACHE, current_shas={'raw://experiment/lot-0060': 'raw_NEW'})
    assert bad and bad[0][0] == 'raw://experiment/lot-0060'
    assert not stale_inputs(CACHE, current_shas={'raw://experiment/lot-0060': 'raw0'})

def test_cycle_guard():
    a = Derivation('a', 'a0', 'p', 'sp', [('b', 'b0')], {}, 'intermediate', 't')
    b = Derivation('b', 'b0', 'p', 'sp', [('a', 'a0')], {}, 'intermediate', 't')
    with pytest.raises(ValueError):
        rebuild_plan('a', by_output([a, b]))


# === 스크립트 버전 이력 (생산 코드도 중간에 바뀐다) ===
def test_script_history_tracks_versions():
    from lakatos.lineage import script_history
    # 생산 스크립트가 수정되면 각 버전이 만든 산출물을 시간순으로 추적
    ds = [
        Derivation('cache://run-A', 'rA', 'extract.py', 'sha_v1', [('raw://lot','raw0')], {}, 'intermediate', 't1'),
        Derivation('cache://run-B', 'rB', 'extract.py', 'sha_v1', [('raw://lot','raw0')], {}, 'intermediate', 't2'),
        Derivation('cache://run-C', 'rC', 'extract.py', 'sha_v2', [('raw://lot','raw0')], {}, 'intermediate', 't3'),
    ]
    h = script_history(ds, 'extract.py')
    assert len(h) == 2                          # 2개 버전
    assert h[0]['sha'] == 'sha_v1' and set(h[0]['outputs']) == {'cache://run-A', 'cache://run-B'}
    assert h[1]['sha'] == 'sha_v2' and h[1]['outputs'] == ['cache://run-C']
    assert h[0]['first_seen'] < h[1]['first_seen']   # 시간순

def test_script_history_empty():
    from lakatos.lineage import script_history
    assert script_history([], 'x.py') == []
