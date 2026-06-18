"""출처추적 TDD — W3C PROV-O 트리플 (판결의 검증가능 계보).
# KG: span_lakatotree_prov
"""
from lakatos.io.prov import prov_triples, replay_command

def test_prov_triples_structure():
    t = prov_triples(tree='T', tag='v4', script='judges/x.py', result_path='out.json',
                     verdict='progressive', script_sha='abc', ts='2026-06-12T00:00:00Z')
    kinds = {x.get('kind') for x in t}
    assert {'Entity', 'Activity', 'Agent'} <= kinds
    rels = {x['rel'] for x in t if x.get('rel')}
    assert 'wasGeneratedBy' in rels and 'used' in rels and 'wasAttributedTo' in rels

def test_replay_command_reproducible():
    cmd = replay_command(script='judges/bpc_loo_p95.py', result_path='r.json')
    assert 'judges/bpc_loo_p95.py' in cmd and 'r.json' in cmd
