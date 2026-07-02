"""git-흡수 G3 landed guards — 봉인 1-verb 정직 사이클 (P3 porcelain 경제학 역전).

git 이 세계를 이긴 건 해싱이 아니라 경제학: 무인자 커밋이 index 를 기본 스테이징으로 거의 공짜
(builtin/commit.c:482-495), 빈 커밋 거부, 실패는 트랜잭션 롤백, 4xx 마다 advice.* 가 다음 명령을
가르친다(advice.c:43-98), incore trial(merge-ort.h:86). 라카토트리는 정직경로(3-verb+스크립트)가
note 경로(1-verb admin)보다 *비쌌다* — 그래서 신규 트리가 판결기제를 우회했다(06-28 이후 scripted 0).

흡수: run_cycle = 봉인 1-verb(사전등록→채점→제출→영수증 한 호출; incore trial 이 첫 write *전에*
4xx 를 잡고, write 후 실패는 보상 롤백으로 신규노드 0) + dry_run incore 채점(쓰기 0) + 4xx advice
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
    """fake 세계: 노드 store + kg(존재확인/롤백 DETACH DELETE 의미론 충실 재현) + 하위 verb 기록.

    롤백 계약(revert-민감): DETACH DELETE 는 *영수증-안전 가드*(verdict_source IS NULL ∧
    NOT (e)-[:HAS_RECEIPT]->())를 방출해야만 fake 가 삭제를 적용한다 — 가드 없는 블랭킷 삭제로
    되돌리면 영수증 노드 보존 단언이 RED(G1/G9 존중이 쿼리에 묶임).
    """

    def __init__(self, seed: dict[str, dict] | None = None):
        self.nodes = {k: dict(v) for k, v in (seed or {}).items()}
        self.pipeline: list[str] = []   # run_cycle 한 호출이 내부에서 완수한 단계들
        self.rollback_queries: list[str] = []

    def kg(self, query, **p):
        tag = p.get('tag')
        if 'DETACH DELETE' in query:
            self.rollback_queries.append(query)
            node = self.nodes.get(tag)
            guarded = ('verdict_source IS NULL' in query) and ('HAS_RECEIPT' in query)
            if node is not None:
                receipted = node.get('verdict_source') or node.get('has_receipt')
                if not guarded or not receipted:   # 무가드(결함)면 영수증 노드도 지워짐 = 단언 RED
                    del self.nodes[tag]
            return []
        if 'HAS_NODE' in query and tag is not None:   # 존재 확인
            return [{'tag': tag}] if tag in self.nodes else []
        return []

    # ── 하위 verb (ProgrammeService 주입 seam — 실제 서비스와 같은 서명) ──
    def add_node(self, name, node: NodeIn):
        self.pipeline.append('node')
        self.nodes.setdefault(node.tag, {})
        return {'ok': True, 'tag': node.tag}

    def register_prediction(self, name, tag, p: PredictionIn):
        self.pipeline.append('predict')
        if self.fail_at == 'predict':
            raise HTTPException(409, '노드 없음 또는 이미 채점됨 — 사후 예측등록 금지')
        self.nodes[tag]['pred_registered_at'] = 'ts'
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

    fail_at: str | None = None


def _svc(cell: _Cell) -> ProgrammeService:
    return ProgrammeService(
        kg=cell.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {'nodes': [], 'frontier': []}, compute_metrics=lambda td: {},
        add_node=cell.add_node, register_prediction=cell.register_prediction,
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
    client_verbs_note += 1; note_cell.add_node('T', NodeIn(tag='m', comment='note only'))
    client_verbs_note += 1; note_cell.nodes['m']['verdict'] = 'recorded'   # set_verdict(admin) 상당 별도 verb
    assert client_verbs_honest < client_verbs_note, \
        f"정직경로({client_verbs_honest} verb)가 note 경로({client_verbs_note} verb)보다 싸지 않음(P3 역전 실패)"

    # incore trial: dry_run=True → 판정 미리보기(judge 순수)만, 하위 verb 0·노드 0(쓰기 없음).
    dry_cell = _Cell()
    preview = _svc(dry_cell).run_cycle('T', _cycle(dry_run=True))
    assert preview.get('dry_run') is True and 'verdict_preview' in preview
    assert dry_cell.pipeline == [] and dry_cell.nodes == {}, "dry_run 이 세계를 썼음(incore 위반)"


# ── guard_mechanism (novel축): 실패 시 신규노드 0 — 봉인 트랜잭션 롤백 ─────────────────────
def test_run_cycle_rolls_back_to_zero_nodes_on_any_failure():
    """어느 단계(predict/submit)에서 실패해도 이 사이클이 만든 신규 노드는 0 으로 롤백된다.

    영수증-안전 3종 동시 단언:
      (a) pre-receipt 실패(predict/submit) → 신규노드 0 (고아 예측노드 debris 없음)
      (b) 기존 노드는 실패해도 절대 안 지움(보상 롤백은 이 사이클 생성분만)
      (c) 영수증 착륙 *후* 실패(critique)는 롤백 금지 — 영수증 파괴는 G1/G9 위반; 롤백 Cypher 는
          verdict_source IS NULL ∧ NOT HAS_RECEIPT 가드를 방출(revert-민감)."""
    # (a) pre-receipt 실패 각 단계 → 신규노드 0
    for stage in ('predict', 'submit'):
        cell = _Cell()
        cell.fail_at = stage
        with pytest.raises(HTTPException):
            _svc(cell).run_cycle('T', _cycle())
        assert cell.nodes == {}, f"{stage} 실패 후 debris 잔류: {cell.nodes} (롤백 미발동)"
        assert cell.rollback_queries, f"{stage} 실패에 롤백 쿼리 미방출"
        assert all('verdict_source IS NULL' in q and 'HAS_RECEIPT' in q
                   for q in cell.rollback_queries), "롤백이 영수증-안전 가드 없이 방출됨(블랭킷 삭제)"

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
