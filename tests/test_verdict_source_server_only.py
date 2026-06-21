"""server-set-only 경계 잠금(적대 재검증 2026-06-21): client 가 verdict_source(또는 임의 server 전용 필드)를
write-facing 스키마로 밀어넣지 못함을 *명시 단언*. 전엔 pydantic 기본 extra='ignore' 가 조용히 drop 할 뿐
회귀 가드가 없어, 누군가 필드를 추가하거나 SET e += row 로 바꾸면 'no receipt=green' 이 무성코 재개방됐다.
# KG: span_lakatotree_verdict_registry
"""
import pytest
from pydantic import ValidationError

from server.contexts.tree.schemas import NodeIn, PredictionIn, VerdictIn
from server.contexts.tree.schemas import TestResultIn as ResultIn   # 별칭: pytest 가 'Test*' 로 수집 시도 방지

_MINIMAL = {
    'NodeIn': dict(tag='x'),
    'VerdictIn': dict(verdict='CANONICAL'),
    'PredictionIn': dict(metric_name='m', baseline_value=1.0),
    'TestResultIn': dict(metric_value=0.0, script='s.py'),
}


@pytest.mark.parametrize('model', [NodeIn, VerdictIn, PredictionIn, ResultIn])
def test_client_supplied_verdict_source_is_rejected(model):
    model(**_MINIMAL[model.__name__])                       # 유효 최소 payload 통과
    with pytest.raises(ValidationError):                    # verdict_source 밀어넣으면 422(조용한 drop 아님)
        model(**_MINIMAL[model.__name__], verdict_source='scripted')


@pytest.mark.parametrize('model', [NodeIn, VerdictIn, PredictionIn, ResultIn])
def test_arbitrary_server_only_field_is_rejected(model):
    with pytest.raises(ValidationError):                    # extra='forbid' — 임의 미상 필드도 거부
        model(**_MINIMAL[model.__name__], current_best_pointer=True)


@pytest.mark.parametrize('model', [NodeIn, VerdictIn, PredictionIn, ResultIn])
def test_no_write_model_declares_verdict_source_field(model):
    assert 'verdict_source' not in model.model_fields
