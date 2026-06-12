"""데이터 계보 TDD — 버퍼는 임시, 완성본은 ZDF서 재생성. 데이터 바뀌면 stale 감지.
# KG: span_lakatotree_lineage
"""
import pytest
from lakatos.lineage import (Derivation, by_output, roots, rebuild_plan,
                             reproducibility_gaps, stale_inputs, is_reproducible)

# ZDF(source) → _rimobs(buffer) → perview(final)
ZDF = Derivation(output='VFEZ0060.zdf', output_sha='z0', producer='', producer_sha='',
                 inputs=[], params={}, kind='source', ts='t0')
RIM = Derivation(output='_rimobs_0060.npz', output_sha='r0', producer='319.py', producer_sha='s319',
                 inputs=[('VFEZ0060.zdf', 'z0')], params={'stride': 2}, kind='intermediate', ts='t1')
PV = Derivation(output='perview_v22.json', output_sha='p0', producer='334.py', producer_sha='s334',
                inputs=[('_rimobs_0060.npz', 'r0')], params={'lots': 6}, kind='final', ts='t2')

def test_roots_trace_to_zdf():
    bo = by_output([ZDF, RIM, PV])
    assert roots('perview_v22.json', bo) == {'VFEZ0060.zdf'}

def test_rebuild_plan_topo_order():
    bo = by_output([ZDF, RIM, PV])
    plan = rebuild_plan('perview_v22.json', bo)
    outs = [d.output for d in plan]
    assert outs.index('_rimobs_0060.npz') < outs.index('perview_v22.json')   # 버퍼 먼저
    assert 'VFEZ0060.zdf' not in outs   # source 는 재생성 안 함 (이미 존재)

def test_reproducibility_gap_when_link_missing():
    # 버퍼 derivation 없으면 완성본 재생성 불가 (계보 끊김)
    bo = by_output([ZDF, PV])   # RIM(_rimobs) 누락
    gaps = reproducibility_gaps('perview_v22.json', bo, sources={'VFEZ0060.zdf'})
    assert '_rimobs_0060.npz' in gaps
    assert not is_reproducible('perview_v22.json', bo, sources={'VFEZ0060.zdf'})

def test_full_chain_reproducible():
    bo = by_output([ZDF, RIM, PV])
    assert is_reproducible('perview_v22.json', bo, sources={'VFEZ0060.zdf'})

def test_stale_when_input_changed():
    # ZDF 가 바뀌면(sha 변경) 하류 버퍼가 stale → 완성본 재생성 필요
    bo = by_output([ZDF, RIM, PV])
    bad = stale_inputs(RIM, current_shas={'VFEZ0060.zdf': 'z_NEW'})
    assert bad and bad[0][0] == 'VFEZ0060.zdf'
    assert not stale_inputs(RIM, current_shas={'VFEZ0060.zdf': 'z0'})

def test_cycle_guard():
    a = Derivation('a', 'a0', 'p', 'sp', [('b', 'b0')], {}, 'intermediate', 't')
    b = Derivation('b', 'b0', 'p', 'sp', [('a', 'a0')], {}, 'intermediate', 't')
    with pytest.raises(ValueError):
        rebuild_plan('a', by_output([a, b]))


# === 스크립트 버전 이력 (생산 코드도 중간에 바뀐다) ===
def test_script_history_tracks_versions():
    from lakatos.lineage import script_history
    # 319.py 가 s319_v1 → s319_v2 로 수정됨. 각 버전이 만든 산출물 추적
    ds = [
        Derivation('_rim_A.npz', 'rA', '319.py', 's319_v1', [('zdf','z0')], {}, 'intermediate', 't1'),
        Derivation('_rim_B.npz', 'rB', '319.py', 's319_v1', [('zdf','z0')], {}, 'intermediate', 't2'),
        Derivation('_rim_C.npz', 'rC', '319.py', 's319_v2', [('zdf','z0')], {}, 'intermediate', 't3'),
    ]
    h = script_history(ds, '319.py')
    assert len(h) == 2                          # 2개 버전
    assert h[0]['sha'] == 's319_v1' and set(h[0]['outputs']) == {'_rim_A.npz', '_rim_B.npz'}
    assert h[1]['sha'] == 's319_v2' and h[1]['outputs'] == ['_rim_C.npz']
    assert h[0]['first_seen'] < h[1]['first_seen']   # 시간순

def test_script_history_empty():
    from lakatos.lineage import script_history
    assert script_history([], 'x.py') == []
