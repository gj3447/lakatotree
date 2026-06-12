"""판결 어휘 단일화 가드 — engine/rebuild verdict 가 레지스트리에 (나생문 F-ARCH-2).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.verdicts import VERDICT_REGISTRY, ENGINE_VERDICTS, REBUILD_VERDICTS, is_registered_verdict
from lakatos.engine import LakatosVerdict

def test_engine_verdicts_in_registry():
    assert {v.value for v in LakatosVerdict} <= VERDICT_REGISTRY   # 분기 차단

def test_rebuild_verdicts_in_registry():
    for v in ('rebuildable', 'progressive_conditional', 'metric_mismatch', 'env_drift', 'step_failed'):
        assert is_registered_verdict(v)

def test_no_orphan_emitted_verdict():
    # /rebuild-verify 가 뱉는 두 단어가 레지스트리에 있는가
    assert is_registered_verdict('rebuildable') and is_registered_verdict('progressive_conditional')
