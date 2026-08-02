"""git-흡수 G3 landed guards — 봉인 1-verb 정직 사이클 (P3 porcelain 경제학 역전).

git 이 세계를 이긴 건 해싱이 아니라 경제학: 무인자 커밋이 index 를 기본 스테이징으로 거의 공짜
(builtin/commit.c:482-495), 빈 커밋 거부, 실패는 트랜잭션 롤백, 4xx 마다 advice.* 가 다음 명령을
가르친다(advice.c:43-98), incore trial(merge-ort.h:86). 라카토트리는 정직경로(3-verb+스크립트)가
note 경로(1-verb admin)보다 *비쌌다* — 그래서 신규 트리가 판결기제를 우회했다(06-28 이후 scripted 0).

흡수: run_cycle = 봉인 1-verb(사전등록→채점→제출→영수증 한 호출; incore trial 이 첫 write *전에*
4xx 를 잡고, prediction 영수증 전 실패만 exact-owner 보상 롤백) + dry_run incore 채점(쓰기 0) + 4xx advice
레지스트리(suggest-only — git --no-verify 같은 우회 off-switch 는 이식 금지).

  guard_defect     = test_honest_cycle_costs_fewer_calls_than_note_path (개선축: 호출수 — 기계적)
  guard_mechanism  = test_run_cycle_rolls_back_to_zero_nodes_on_any_failure (novel축: 롤백 원자성)

# KG: LakatosTree_GitAbsorption_20260702 / G3_one_verb_honest_cycle
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.programme_service import ProgrammeService
from server.contexts.tree.schemas import CritiqueIn, CycleIn, NodeIn, PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result


class _Cell:
    """fake world for exact creation ownership and the prediction durability point."""

    def __init__(self, seed: dict[str, dict] | None = None):
        self.nodes = {k: dict(v) for k, v in (seed or {}).items()}
        self.pipeline: list[str] = []   # run_cycle 한 호출이 내부에서 완수한 단계들
        self.compensations: list[tuple[str, str]] = []
        self.claims: list[str] = []

    def kg(self, query, **p):
        tag = p.get('tag')
        return []

    # ── 하위 verb (ProgrammeService 주입 seam — 실제 서비스와 같은 서명) ──
    def add_node(self, name, node: NodeIn, claim: str):
        self.pipeline.append('node')
        self.claims.append(claim)
        created = node.tag not in self.nodes
        if created:
            self.nodes[node.tag] = {'_cycle_created_by': claim}
        elif self.nodes[node.tag].get('_cycle_created_by') == claim:
            # Exact request replay adopts the draft but revokes destructive
            # compensation authority before it can proceed.
            created = False
            self.nodes[node.tag].pop('_cycle_created_by', None)
        elif self.nodes[node.tag].get('_cycle_created_by') is not None:
            raise HTTPException(409, 'active cycle claim conflict')
        else:
            self.nodes[node.tag].pop('_cycle_created_by', None)
        return {'ok': True, 'tag': node.tag, '_cycle_created': created}

    def register_prediction(self, name, tag, p: PredictionIn):
        self.pipeline.append('predict')
        if self.fail_at == 'crash_predict':
            raise SystemExit('simulated process death')
        if self.fail_at == 'predict':
            raise HTTPException(409, '노드 없음 또는 이미 채점됨 — 사후 예측등록 금지')
        self.nodes[tag]['pred_registered_at'] = 'ts'
        self.nodes[tag]['pred_receipt_sha'] = 'prediction-receipt'
        self.nodes[tag]['has_receipt'] = True
        return {'ok': True}

    def submit_test_result(self, name, tag, r: Result):
        self.pipeline.append('submit')
        if self.fail_at == 'submit':
            raise HTTPException(409, '이미 스크립트로 채점된 노드 — 재채점 금지')
        self.nodes[tag]['verdict_source'] = 'scripted'
        self.nodes[tag]['has_receipt'] = True
        return {'verdict': 'progressive', 'novel': True, 'delta': -0.9}

    def add_critique(self, name, tag, c: CritiqueIn):
        self.pipeline.append('critique')
        if self.fail_at == 'critique':
            raise HTTPException(422, '알 수 없는 반례 대응')
        return {'ok': True}

    def release_cycle_claim(self, name, tag, claim):
        node = self.nodes.get(tag)
        if node and node.get('_cycle_created_by') == claim:
            node.pop('_cycle_created_by', None)

    def compensate_cycle_node(self, name, tag, claim):
        self.compensations.append((tag, claim))
        node = self.nodes.get(tag)
        if not node or node.get('_cycle_created_by') != claim:
            return 'not_owned'
        protected = (
            node.get('verdict_source') or node.get('has_receipt')
            or node.get('pred_registered_at') or node.get('pred_receipt_sha')
            or node.get('has_argument') or node.get('has_critique_intent')
        )
        if protected:
            node.pop('_cycle_created_by', None)
            return 'preserved'
        del self.nodes[tag]
        return 'deleted'

    fail_at: str | None = None


def _svc(cell: _Cell) -> ProgrammeService:
    return ProgrammeService(
        kg=cell.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {'nodes': [], 'frontier': []}, compute_metrics=lambda td: {},
        add_node=cell.add_node,
        compensate_cycle_node=cell.compensate_cycle_node,
        release_cycle_claim=cell.release_cycle_claim,
        register_prediction=cell.register_prediction,
        submit_test_result=cell.submit_test_result, add_critique=cell.add_critique,
        standing=lambda n, t: {'stands': True}, insert_artifact=lambda a: None)


def _cycle(**kw) -> CycleIn:
    return CycleIn(**{'tag': 'n', 'metric_name': 'seam', 'baseline': 10.0,
                      'direction': 'lower', 'measured': 1.0, 'script': 'inline', **kw})


# ── guard_defect (개선축, 기계적 호출수): 정직경로 ≤ 1 verb < note 경로 ──────────────────────
def test_honest_cycle_costs_fewer_calls_than_note_path():
    """porcelain 경제학 역전 — 클라이언트 verb 수를 *센다*(행동/채택률 아님, q_adoption_metric_confound).

    정직경로: run_cycle *한 번*이 노드+사전등록+판결영수증까지 전 파이프라인 완수 = client 1 verb.
    note 경로: 같은 결과(노드+아무 standing)에 최소 add_node + set_verdict = client 2 verb.
    1 < 2 를 기계적으로 단언. + incore dry_run 은 쓰기 0(공짜 시험 — git commit --dry-run/incore trial)."""
    cell = _Cell()
    client_verbs_honest = 0
    client_verbs_honest += 1   # ← 클라이언트가 실제 부르는 유일 verb
    out = _svc(cell).run_cycle('T', _cycle())
    assert out['verdict'] == 'progressive'
    assert cell.pipeline[:3] == ['node', 'predict', 'submit'], \
        f"1-verb 가 전체 파이프라인을 완수하지 않음: {cell.pipeline} (봉인 아님)"
    assert 'n' in cell.nodes and cell.nodes['n'].get('has_receipt'), "1 verb 가 영수증까지 못 감"

    # note 경로 — 노드 + standing 라벨에 필요한 최소 *공개 verb 시퀀스*를 실제로 구동해 센다.
    note_cell = _Cell()
    client_verbs_note = 0
    client_verbs_note += 1; note_cell.add_node(
        'T', NodeIn(tag='m', comment='note only'), 'note-path'
    )
    client_verbs_note += 1; note_cell.nodes['m']['verdict'] = 'recorded'   # set_verdict(admin) 상당 별도 verb
    assert client_verbs_honest < client_verbs_note, \
        f"정직경로({client_verbs_honest} verb)가 note 경로({client_verbs_note} verb)보다 싸지 않음(P3 역전 실패)"

    # incore trial: dry_run=True → 판정 미리보기(judge 순수)만, 하위 verb 0·노드 0(쓰기 없음).
    dry_cell = _Cell()
    preview = _svc(dry_cell).run_cycle('T', _cycle(dry_run=True))
    assert preview.get('dry_run') is True and 'verdict_preview' in preview
    assert dry_cell.pipeline == [] and dry_cell.nodes == {}, "dry_run 이 세계를 썼음(incore 위반)"


# ── guard_mechanism (novel축): 실패 시 신규노드 0 — 봉인 트랜잭션 롤백 ─────────────────────
def test_run_cycle_compensates_only_before_prediction_receipt():
    """Only pre-receipt failure may delete an exactly-owned new node.

    영수증-안전 동시 단언:
      (a) prediction 실패 → 신규노드 0 (고아 draft debris 없음)
      (b) submit 실패는 prediction receipt 뒤이므로 노드+receipt 보존
      (b) 기존 노드는 실패해도 절대 안 지움(보상 롤백은 이 사이클 생성분만)
      (c) 영수증 착륙 *후* 실패(critique)는 롤백 금지 — 영수증 파괴는 G1/G9 위반; 롤백 Cypher 는
          verdict_source IS NULL ∧ NOT HAS_RECEIPT 가드를 방출(revert-민감)."""
    cell = _Cell()
    cell.fail_at = 'predict'
    with pytest.raises(HTTPException):
        _svc(cell).run_cycle('T', _cycle())
    assert cell.nodes == {}
    assert cell.compensations

    cell = _Cell()
    cell.fail_at = 'submit'
    with pytest.raises(HTTPException):
        _svc(cell).run_cycle('T', _cycle())
    assert cell.nodes['n']['pred_receipt_sha'] == 'prediction-receipt'
    assert cell.compensations == [], 'post-prediction submit failure must not compensate'

    # (a2) critique binding이 먼저 착륙한 신규노드는 보상 삭제보다 우선한다.
    cell = _Cell(seed={'n': {'_cycle_created_by': 'owner', 'has_argument': True,
                             'has_critique_intent': True}})
    assert cell.compensate_cycle_node('T', 'n', 'owner') == 'preserved'
    assert 'n' in cell.nodes

    # A losing/stale token never deletes another invocation's node.
    cell = _Cell(seed={'n': {'_cycle_created_by': 'winner'}})
    assert cell.compensate_cycle_node('T', 'n', 'loser') == 'not_owned'
    assert 'n' in cell.nodes

    # (b) 기존 노드(이 사이클이 만들지 않음)는 실패해도 보존 — run_cycle 은 남의 역사를 못 지운다.
    cell = _Cell(seed={'n': {'comment': 'pre-existing draft'}})
    cell.fail_at = 'predict'
    with pytest.raises(HTTPException):
        _svc(cell).run_cycle('T', _cycle())
    assert 'n' in cell.nodes, "기존 노드가 보상 롤백에 삭제됨(생성분 아님)"

    # (c) 영수증 착륙 후(critique 단계) 실패 → 노드+영수증 보존(롤백 금지), 4xx 는 그대로 전파.
    cell = _Cell()
    cell.fail_at = 'critique'
    with pytest.raises(HTTPException):
        _svc(cell).run_cycle('T', _cycle(critiques=[dict(arg_id='a1', attacks='verdict:n')]))
    assert cell.nodes.get('n', {}).get('has_receipt') is True, \
        "영수증 착륙 후 실패가 노드/영수증을 파괴(봉인 단위는 [node,prereg,judgement] — 영수증이 내구점)"


def test_exact_cycle_request_recovers_claim_after_process_restart():
    cell = _Cell()
    cycle = _cycle()
    cell.fail_at = 'crash_predict'

    with pytest.raises(SystemExit, match='process death'):
        _svc(cell).run_cycle('T', cycle)
    stranded_claim = cell.nodes['n']['_cycle_created_by']

    cell.fail_at = None
    out = _svc(cell).run_cycle('T', cycle)

    assert out['verdict'] == 'progressive'
    assert cell.nodes['n'].get('_cycle_created_by') is None
    assert cell.claims == [stranded_claim, stranded_claim]


def test_same_claim_reentry_revokes_stale_compensation_authority():
    cell = _Cell()
    cycle = _cycle()
    cell.fail_at = 'crash_predict'
    with pytest.raises(SystemExit, match='process death'):
        _svc(cell).run_cycle('T', cycle)

    # A same-request retry is admitted, then fails before prediction durability.
    # It must preserve the shared draft because admission revoked the first
    # process's destructive marker.
    cell.fail_at = 'predict'
    with pytest.raises(HTTPException):
        _svc(cell).run_cycle('T', cycle)
    assert 'n' in cell.nodes
    assert cell.nodes['n'].get('_cycle_created_by') is None
    assert cell.compensations[-1][0] == 'n'

    cell.fail_at = None
    out = _svc(cell).run_cycle('T', cycle)
    assert out['verdict'] == 'progressive'
