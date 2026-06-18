"""엔진 env 인식 — 환경 바뀌면 재현 결과 달라질 수 있음(G-RebuildFromRaw 강화).
# KG: span_lakatotree_envfp
"""
from lakatos.io.lineage import Derivation
from lakatos.io.replay import LineageReplayGate

def _chain(env='E1'):
    return [
        Derivation('zdf', 'z0', '', '', [], {}, 'source', 't0', ''),
        Derivation('buf', 'b0', 'p.py', 's1', [('zdf','z0')], {}, 'intermediate', 't1', env),
        Derivation('final', 'f0', 'q.py', 's2', [('buf','b0')], {}, 'final', 't2', env),
    ]

def test_env_match_passes():
    r = LineageReplayGate.evaluate('final', _chain('E1'), current_env='E1')
    assert r.passed and not r.env_drift

def test_env_drift_blocks():
    r = LineageReplayGate.evaluate('final', _chain('E1'), current_env='E2_DIFFERENT')
    assert not r.passed and r.env_drift and 'env_drift' in r.reasons
    assert 'buf' in r.env_changed and 'final' in r.env_changed

def test_no_current_env_ignores():
    r = LineageReplayGate.evaluate('final', _chain('E1'))   # env 미지정 = 하위호환
    assert r.passed and not r.env_drift
