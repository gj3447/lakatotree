"""R2-NOVEL — run_cycle novel_script 관통 + CycleIn extra=forbid + dry_run 정책 미리보기 가드.

라이브 GitAbsorption 11×partial 사고의 기전 봉합: 봉인 1-verb(run_cycle)에 novel_script(cross-metric
novel 의 서버앵커 소스, FF1) 입력 필드 자체가 없었고 — CycleIn 만 pydantic 기본 extra=ignore 라
오타/구서버 필드까지 *무음드롭* = partial 재생산(TestResultIn 은 이미 forbid, schemas.py 상단 주석이
함정을 명문화) — 응답이 FF1 강등사유(lakatos)를 삼켰으며, dry_run 이 강등을 예고하지 못했다.

  guard_defect(음성 오라클 — 결함 죽음):
    ① test_cycle_in_rejects_unknown_fields — CycleIn(오타/서버전용 필드) → pydantic ValidationError
       (forbid). 현행 extra=ignore 무음드롭이면 RED.
    ② test_demotion_reason_and_advice_surface_in_response — novel_script 누락 + require_novel_anchor
       트리에서 실 run_cycle 응답에 verdict=partial + lakatos 사유 + advice(suggest-only) 실림.
       현행은 응답에 lakatos/advice 필드 부재 = RED.
  guard_mechanism(양성 오라클 — 메커니즘 실재, revert-민감):
    ① test_novel_script_passes_through_to_submit_and_anchors — novel_script(실파일) 동봉 실 run_cycle
       이 submit_test_result 까지 관통(fake 가 받은 Result.novel_script == 보낸 경로) → progressive +
       novel_server_anchored=True. programme_service 의 novel_script= 관통을 되돌리면 fake 가 None 을
       받아 partial = RED.
    ② test_dry_run_previews_demotion_with_zero_writes — dry_run 이 would_demote_to_partial 을 사전
       예고하되 쓰기 0(하위 verb 콜 기록 0·노드 0).
    ③ test_dry_run_survives_policy_read_failure — 정책 조회 실패 fake 에서도 dry_run 이 죽지 않고
       힌트만 생략(fail-safe: 불확실한 정책으로 힌트를 지어내지 않는다).

fake 는 ProgrammeService 주입 콜러블(tests/test_git_absorption_g3.py 의 _Cell 계승) — submit fake 가
judgement_service 의 FF1 데모트 경계(require_novel_anchor ∧ cross-metric ∧ novel_script 실파일 미앵커
→ partial/'novel_not_server_anchored')를 충실 재현한다.

# KG: LakatosTree_GitAbsorption_20260702 / followup-R2-novel-cycle
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.contexts.tree.programme_service import ProgrammeService
from server.contexts.tree.schemas import CritiqueIn, CycleIn, NodeIn, PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result

_REPO = Path(__file__).resolve().parents[2]
NOVEL_SCRIPT = 'tests/test_git_absorption_g2.py'   # 실재 파일 — 서버가 sha 재유도 가능한 novel 소스
assert (_REPO / NOVEL_SCRIPT).is_file(), 'harness 전제 위반: NOVEL_SCRIPT 는 실파일이어야 한다'


class _World:
    """fake 세계(G3 _Cell 계승) — kg(정책 1-read/존재확인/롤백) + 하위 verb 기록 + FF1 데모트 재현.

    submit fake 는 judgement_service FF1 경계를 미러: 트리 정책 무장(require_novel_anchor 플래그
    또는 receipted+ tier) ∧ cross-metric novel ∧ novel_script 가 *실파일* 로 앵커되지 않으면
    partial/'novel_not_server_anchored'. 앵커 성립이면 progressive + novel_server_anchored=True.
    """

    def __init__(self, require_novel_anchor: bool = False, tier: str = 'notebook',
                 policy_read_fails: bool = False):
        self.require_novel_anchor = require_novel_anchor
        self.tier = tier
        self.policy_read_fails = policy_read_fails
        self.nodes: dict[str, dict] = {}
        self.pipeline: list[str] = []   # run_cycle 이 실제 부른 하위 verb 기록(쓰기 0 단언용)
        self.policy_reads = 0
        self.submitted: list[Result] = []

    # ── kg — dry_run 정책 read 는 여기로만 온다(HAS_NODE 존재확인/DETACH 롤백과 구분) ──
    def kg(self, query, **p):
        if 'require_novel_anchor' in query:   # s3: 트리 정책 1-read
            self.policy_reads += 1
            if self.policy_read_fails:
                raise RuntimeError('kg unavailable — 정책 조회 실패(운영 neo4j 단절 시뮬레이션)')
            return [{'require_novel_anchor': self.require_novel_anchor,
                     'assurance_tier': self.tier}]
        tag = p.get('tag')
        if 'DETACH DELETE' in query:
            node = self.nodes.get(tag)
            if node is not None and not node.get('has_receipt'):
                del self.nodes[tag]
            return []
        if 'HAS_NODE' in query and tag is not None:
            return [{'tag': tag}] if tag in self.nodes else []
        return []

    # ── 하위 verb (ProgrammeService 주입 seam — 실제 서비스와 같은 서명) ──
    def add_node(self, name, node: NodeIn):
        self.pipeline.append('node')
        self.nodes.setdefault(node.tag, {})
        return {'ok': True, 'tag': node.tag}

    def register_prediction(self, name, tag, p: PredictionIn):
        self.pipeline.append('predict')
        self.nodes[tag]['pred'] = p
        return {'ok': True}

    def submit_test_result(self, name, tag, r: Result):
        self.pipeline.append('submit')
        self.submitted.append(r)
        pred: PredictionIn = self.nodes[tag]['pred']
        cross = bool(pred.novel_metric and pred.novel_metric != pred.metric_name)
        anchored = bool(r.novel_script) and (_REPO / str(r.novel_script)).is_file()
        armed = self.require_novel_anchor or self.tier in ('receipted', 'anchored')
        verdict, lakatos = 'progressive', 'clean'
        if armed and cross and r.novel_measured is not None and not anchored:
            verdict, lakatos = 'partial', 'novel_not_server_anchored'
        self.nodes[tag]['has_receipt'] = True
        return {'ok': True, 'verdict': verdict, 'lakatos': lakatos, 'delta': -0.9,
                'novel': r.novel_measured is not None, 'novel_server_anchored': anchored}

    def add_critique(self, name, tag, c: CritiqueIn):
        self.pipeline.append('critique')
        return {'ok': True}


def _svc(world: _World) -> ProgrammeService:
    return ProgrammeService(
        kg=world.kg, hist=lambda *a, **k: None, pg=lambda: None,
        tree_data=lambda n: {'nodes': [], 'frontier': []}, compute_metrics=lambda td: {},
        add_node=world.add_node, register_prediction=world.register_prediction,
        submit_test_result=world.submit_test_result, add_critique=world.add_critique,
        standing=lambda n, t: {'stands': True}, insert_artifact=lambda a: None)


def _cycle(**kw) -> CycleIn:
    """cross-metric novel(예측 metric=seam ≠ novel_metric=downstream)이 충족되는 기본 사이클."""
    return CycleIn(**{'tag': 'n', 'metric_name': 'seam', 'baseline': 10.0, 'direction': 'lower',
                      'measured': 1.0, 'script': 'inline',
                      'novel_metric': 'downstream', 'novel_direction': 'lower',
                      'novel_threshold': 5.0, 'novel_measured': 1.0, **kw})


# ── guard_defect ① — CycleIn 무음드롭 죽음(extra=forbid) ─────────────────────────────────
def test_cycle_in_rejects_unknown_fields():
    """오타(novel_scirpt)/구서버 필드가 무음드롭되지 않고 ValidationError 로 죽는다.

    무음드롭의 실사고: novel_script 오타 → 앵커 미성립 → 11×partial 이 *조용히* 재생산."""
    with pytest.raises(ValidationError):
        CycleIn(tag='n', metric_name='seam', baseline=10.0, measured=1.0,
                novel_scirpt='typo.py')   # 오타 필드 — ignore 면 조용히 사라진다(RED)
    # server-set 경계도 동일(TestResultIn 과 같은 _SERVER_SET_ONLY): client 가 서버 전용 필드 못 실음.
    with pytest.raises(ValidationError):
        CycleIn(tag='n', metric_name='seam', baseline=10.0, measured=1.0,
                verdict_source='scripted')


# ── guard_defect ② — 강등사유가 응답에 실린다(삼킴 죽음) ────────────────────────────────
def test_demotion_reason_and_advice_surface_in_response():
    """novel_script 누락 + require_novel_anchor 트리 → partial + lakatos 사유 + advice 동봉.

    advice 는 suggest-only(200 응답 필드 — 상태코드/verdict 불변, 게이트 우회 수단 아님)."""
    world = _World(require_novel_anchor=True)
    out = _svc(world).run_cycle('T', _cycle())   # novel_script 미동봉
    assert out['verdict'] == 'partial'
    assert out.get('lakatos') == 'novel_not_server_anchored', f'강등사유 삼킴: {out}'
    assert 'novel_script' in str(out.get('advice', '')), f'advice 미동봉(다음 수 안내 없음): {out}'
    assert out.get('advice_mode') == 'suggest-only'
    assert out.get('novel_server_anchored') is False


# ── guard_mechanism ① — novel_script 관통 + 서버앵커 성립(revert-민감) ──────────────────
def test_novel_script_passes_through_to_submit_and_anchors():
    world = _World(require_novel_anchor=True)
    out = _svc(world).run_cycle('T', _cycle(novel_script=NOVEL_SCRIPT))
    assert world.submitted and world.submitted[-1].novel_script == NOVEL_SCRIPT, \
        'run_cycle 이 novel_script 를 submit_test_result 까지 관통시키지 않음(s1 회귀)'
    assert out['verdict'] == 'progressive'
    assert out.get('novel_server_anchored') is True
    assert 'advice' not in out, f'앵커 성립인데 강등 advice 가 실림: {out}'


# ── guard_mechanism ② — dry_run 이 FF1 강등을 사전 예고(쓰기 0) ─────────────────────────
def test_dry_run_previews_demotion_with_zero_writes():
    world = _World(require_novel_anchor=True)
    out = _svc(world).run_cycle('T', _cycle(dry_run=True))
    assert out.get('dry_run') is True and 'verdict_preview' in out
    assert out.get('would_demote_to_partial') is True, f'dry_run 이 FF1 강등을 예고하지 않음: {out}'
    assert world.pipeline == [] and world.nodes == {}, 'dry_run 이 세계를 씀(incore 위반)'
    assert world.policy_reads >= 1, '정책 1-read 미발생(예고가 정책과 무관하게 지어짐)'
    # novel_script 동봉 → 예고 해제. 정책 off(notebook + 플래그 없음) → 예고 없음.
    assert _svc(world).run_cycle('T', _cycle(dry_run=True, novel_script=NOVEL_SCRIPT))[
        'would_demote_to_partial'] is False
    off = _World(require_novel_anchor=False)
    assert _svc(off).run_cycle('T', _cycle(dry_run=True))['would_demote_to_partial'] is False
    # tier 무장(receipted/anchored)은 opt-in 플래그 없이도 예고(G6 tier 정책 = FF1 의 tier 화).
    tiered = _World(require_novel_anchor=False, tier='anchored')
    assert _svc(tiered).run_cycle('T', _cycle(dry_run=True))['would_demote_to_partial'] is True
    assert world.pipeline == [] and off.pipeline == [] and tiered.pipeline == []


# ── guard_mechanism ③ — 정책 조회 실패에도 dry_run 은 산다(fail-safe: 힌트 생략) ─────────
def test_dry_run_survives_policy_read_failure():
    world = _World(require_novel_anchor=True, policy_read_fails=True)
    out = _svc(world).run_cycle('T', _cycle(dry_run=True))
    assert out.get('dry_run') is True and 'verdict_preview' in out, f'dry_run 이 죽음: {out}'
    assert 'would_demote_to_partial' not in out, \
        '정책 불확실인데 힌트를 지어냄(fail-safe 위반 — 조회 실패=힌트 생략)'
    assert world.pipeline == [] and world.nodes == {}


# ── guard_mechanism (s4) — CLI cycle-dry 가 REST /cycle 에 dry_run=true 로 직행 ──────────
def test_cli_cycle_dry_posts_rest_dry_run(monkeypatch, tmp_path, capsys):
    """cycle-dry 는 lakatos/harness_run(CycleSpec bash 실행기) 경유 금지 — REST POST 직행."""
    import lakatos.cli as cli
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps({'tag': 'n', 'metric_name': 'seam', 'baseline': 10.0,
                                'measured': 1.0}), encoding='utf-8')
    seen = {}

    def fake_call(method, path, body=None):
        seen.update(method=method, path=path, body=body)
        return {'dry_run': True, 'verdict_preview': 'progressive', 'would_demote_to_partial': False}

    monkeypatch.setattr(cli, 'call', fake_call)
    cli.main(['cycle-dry', 'T', str(spec)])
    assert seen.get('method') == 'POST' and seen.get('path') == '/api/tree/T/cycle', seen
    assert seen['body'].get('dry_run') is True, f'dry_run=true 미강제: {seen}'
    printed = json.loads(capsys.readouterr().out)
    assert printed.get('dry_run') is True   # 서버 응답 JSON 을 그대로 출력
