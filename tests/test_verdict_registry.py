"""판결 어휘 단일화 가드 — engine/rebuild verdict 가 레지스트리에 (나생문 F-ARCH-2).
# KG: span_lakatotree_verdict_registry
"""
from lakatos.verdicts import (VERDICT_REGISTRY, ENGINE_VERDICTS, REBUILD_VERDICTS,
                              PROGRESS_VERDICTS, NONPROGRESSIVE_VERDICTS, is_registered_verdict)
from lakatos.engine import LakatosVerdict

def test_engine_verdicts_in_registry():
    assert {v.value for v in LakatosVerdict} <= VERDICT_REGISTRY   # 분기 차단

def test_progress_and_nonprogress_are_registered():
    # 의미 분류(진보/비진보)에 쓰인 모든 어휘는 등록 어휘여야 — 미등록 drift 차단
    assert PROGRESS_VERDICTS <= VERDICT_REGISTRY
    assert NONPROGRESSIVE_VERDICTS <= VERDICT_REGISTRY

def test_progress_nonprogress_disjoint():
    # 한 판결이 진보∧비진보일 수 없다 — 분류 모순 차단
    assert PROGRESS_VERDICTS.isdisjoint(NONPROGRESSIVE_VERDICTS)

def test_metrics_consumes_registry_not_local_tuples():
    # metrics 가 자체 어휘를 재정의하지 않고 verdicts 정본을 그대로 가리키는가(SSOT)
    import lakatos.metrics as m
    import lakatos.verdicts as v
    assert m.PROGRESS_VERDICTS is v.PROGRESS_VERDICTS
    assert m.NONPROGRESSIVE is v.NONPROGRESSIVE_VERDICTS

def test_judge_outputs_are_scripted_verdicts():
    # judge() 가 뱉는 4개 리터럴이 SCRIPTED 어휘 집합과 정확히 일치(출력 drift 차단)
    from lakatos.verdicts import SCRIPTED_VERDICTS
    assert {'progressive', 'partial', 'equivalent', 'rejected'} == SCRIPTED_VERDICTS

def test_rebuild_verdicts_in_registry():
    for v in ('rebuildable', 'progressive_conditional', 'metric_mismatch', 'env_drift', 'step_failed'):
        assert is_registered_verdict(v)

def test_no_orphan_emitted_verdict():
    # /rebuild-verify 가 뱉는 두 단어가 레지스트리에 있는가
    assert is_registered_verdict('rebuildable') and is_registered_verdict('progressive_conditional')
