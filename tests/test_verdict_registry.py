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
    import lakatos.quant.metrics as m
    import lakatos.verdicts as v
    assert m.PROGRESS_VERDICTS is v.PROGRESS_VERDICTS
    assert m.NONPROGRESSIVE is v.NONPROGRESSIVE_VERDICTS

def test_judge_outputs_are_scripted_verdicts():
    # judge() 가 뱉는 4개 리터럴이 SCRIPTED 어휘 집합과 정확히 일치(출력 drift 차단)
    from lakatos.verdicts import SCRIPTED_VERDICTS
    assert {'progressive', 'partial', 'equivalent', 'rejected'} == SCRIPTED_VERDICTS

def test_rebuild_verdicts_in_registry():
    for v in ('rebuildable', 'rebuildable_static', 'progressive_conditional',
              'metric_mismatch', 'env_drift', 'step_failed'):
        assert is_registered_verdict(v)

def test_no_orphan_emitted_verdict():
    # #7: 정적 /rebuild-verify 는 rebuildable_static(재실행 아님)·progressive_conditional 을,
    # executor 재실행 영수증은 rebuildable 을 뱉는다 — 셋 다 레지스트리에 (영수증급 토큰을 정적 체크서 분리).
    assert is_registered_verdict('rebuildable_static') and is_registered_verdict('progressive_conditional')
    assert is_registered_verdict('rebuildable')   # executor 재실행 영수증


def test_engine_enum_is_strict_subset_of_engine_verdicts():
    # enum↔registry 계약 (engine-unify 2026-07-23): LakatosVerdict(게이트 출력 5) ⊂ ENGINE_VERDICTS(7).
    # 초과 2개는 spine 합성 판결(progressive_unverified=reconcile, withdrawn=pnr) — 게이트가 뱉지 않는다.
    from lakatos.verdicts import ENGINE_VERDICTS
    enum_values = {v.value for v in LakatosVerdict}
    assert enum_values < ENGINE_VERDICTS
    assert ENGINE_VERDICTS - enum_values == {'progressive_unverified', 'withdrawn'}


def test_consumer_classification_sets_are_registered():
    # engine-unify 흡수분(2026-07-23): 소비자 정책 집합도 전부 등록 어휘의 부분집합이어야 한다.
    import lakatos.verdicts as v
    for name in ('CANONICAL_STATE_VERDICTS', 'SCORED_PROGRESS_VERDICTS', 'FRONTIER_EXPLANATION_VERDICTS',
                 'FRONTIER_PROGRESS_VERDICTS', 'TESTED_CORE_VERDICTS', 'DEMOTABLE_PROGRESS_VERDICTS',
                 'SERIES_PROGRESS_VERDICTS', 'SERIES_NONPROGRESS_VERDICTS', 'SERIES_OFF_AXIS_VERDICTS',
                 'SERIES_NEUTRAL_VERDICTS', 'SERIES_KNOWN_VERDICTS', 'REJECTING_VERDICTS',
                 'STANDING_VERDICTS', 'SCRIPTED_DIALECTICAL_VERDICTS',
                 'METRIC_IMPROVED_FAMILY_VERDICTS', 'DIALECTIC_OVERRIDE_VERDICTS',
                 'PNR_CONDITIONAL_SOURCE_VERDICTS'):
        assert frozenset(getattr(v, name)) <= VERDICT_REGISTRY, name


def test_consumers_import_registry_not_local_literals():
    # SSOT: 흡수된 소비자 모듈이 정본 객체를 *그대로* 가리키는가 (지역 리터럴 재정의 차단).
    import lakatos.node_state as ns
    import lakatos.verdicts as v
    import server.contexts.tree.validation as val
    import server.contexts.audit.fsck as fsck
    assert ns._REJECTING_VERDICTS is v.REJECTING_VERDICTS
    assert val.SCORED_PROGRESS_VERDICTS is v.SCORED_PROGRESS_VERDICTS
    assert fsck._STANDING_VERDICTS is v.STANDING_VERDICTS
