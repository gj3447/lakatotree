"""통합티어(LAKATOS_IT): producer replay *live e2e* — 실 Neo4j + 실 sandbox 실행으로 위조 metric 적발.

나생문 #1 근본 봉합의 끝단 영수증: 채점 스크립트를 *실제 재실행*(LAKATOS_REPLAY_EXEC)해 client 가 보고한
metric_value 를 검증하고, 그 결과(measurement_externally_anchored)를 CANONICAL 노드에 *persist* 함을 실 그래프로
확인한다. hermetic 단위(tests/fix_harness/test_fix_producer_replay_live.py)는 판정/배선을 포트 주입으로 핀하나,
'실 Neo4j 에 persist 된 anchor 를 readback' 은 여기서만 — 영수증 없는 green 금지(gated, LAKATOS_IT 필요).

정직 측정(재실행==recorded) → anchored True · 위조(재실행≠recorded) → anchored False.
# KG: span_lakatotree_engine / span_lakatotree_rebuild
"""
import pytest

from lakatos.node_state import NodeState
from server.container import AppContainer
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import VerdictIn

pytestmark = pytest.mark.integration


class _DummyMongo:
    def close(self):
        pass


def _seed_candidate(kg, *, tag, judge_script, recorded_metric):
    """CANONICAL_CANDIDATE 후보 노드 직접 셋업 — progressive/scripted, 실 scorer 경로 + recorded metric.
    (submit→judge 전 과정 대신 후보 상태를 그래프에 직접 둬 set_verdict 승격경로만 e2e 한다.)"""
    kg('''MERGE (t:LakatosTree {name:'T'})
          MERGE (t)-[:HAS_NODE]->(e {tag:$tag})
          SET e.verdict='progressive', e.verdict_source='scripted', e.node_state=$st,
              e.judge_script=$js, e.metric_value=$mv, e.result_path='x', e.pred_noise_band=0.0,
              e.qualitative_self_report=false, e.novel_confirmed=true, e.author='',
              e.measurement_externally_anchored=null''',
       tag=tag, st=NodeState.CANONICAL_CANDIDATE.value, js=judge_script, mv=recorded_metric)


def _service(container, monkeypatch):
    """실 app._producer_replay_for_node 를 컨테이너 kg 로 — 게이트 ON. 실 _replay_run(subprocess) 사용."""
    import server.app as app
    monkeypatch.setenv('LAKATOS_REPLAY_EXEC', '1')
    monkeypatch.setattr(app, 'kg', container.kg)   # app 함수가 컨테이너 그래프를 읽게
    return JudgementService(kg=container.kg, kg_tx=container.kg_tx, hist=container.hist,
                            foundation=lambda _n: None,
                            reproducible_for_node=lambda _n, _t: None,
                            producer_replay_for_node=app._producer_replay_for_node)


def _anchored(kg, tag):
    rows = kg('MATCH (e {tag:$tag}) RETURN e.measurement_externally_anchored AS mea', tag=tag)
    return rows[0]['mea'] if rows else None


def test_live_producer_replay_persists_true_for_honest_metric(neo4j_driver, tmp_path, monkeypatch):
    """정직: 실 scorer 가 recorded 와 같은 metric 을 재생성 → 재실행 검증 → anchored=True 가 노드에 persist."""
    c = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw={})
    scorer = tmp_path / "scorer.py"
    scorer.write_text("import sys\nprint('metric=0.50')\n")   # args 무시, recorded 와 동일
    _seed_candidate(c.kg, tag='honest', judge_script=str(scorer), recorded_metric=0.50)
    svc = _service(c, monkeypatch)

    svc.set_verdict('T', 'honest', VerdictIn(verdict='CANONICAL'))

    assert _anchored(c.kg, 'honest') is True   # 실 재실행이 측정을 외부검증 → persist True


def test_live_producer_replay_persists_false_for_forged_metric(neo4j_driver, tmp_path, monkeypatch):
    """위조: client 가 recorded=0.99 로 보고했으나 실 scorer 재실행은 0.50 → 불일치 → anchored=False persist.
    이것이 #1 forge 의 런타임 봉합: 서버가 숫자를 신뢰하지 않고 현실(재실행)이 끊는다."""
    c = AppContainer(neo=neo4j_driver, mongo=_DummyMongo(), pg_kw={})
    scorer = tmp_path / "scorer.py"
    scorer.write_text("import sys\nprint('metric=0.50')\n")   # 실제값 0.50
    _seed_candidate(c.kg, tag='forged', judge_script=str(scorer), recorded_metric=0.99)   # client 위조 0.99
    svc = _service(c, monkeypatch)

    svc.set_verdict('T', 'forged', VerdictIn(verdict='CANONICAL'))

    assert _anchored(c.kg, 'forged') is False   # 재실행 0.50 ≠ 위조 0.99 → 외부검증 실패 → persist False
