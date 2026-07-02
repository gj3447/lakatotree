"""R8-MG2 — ManifestoGap 2차 채점의 mechanism 앵커 (후속 PROM 2026-07-03).

각 노드의 novel_script = 이 파일 — 슬라이스 mechanism 이 실재해야 라이브 채점이 progressive(revert-민감).

  S3  writer H9 param-seal   : test_s3_param_seal_preserves_scored_verdict
  P0a replay_status persist  : test_p0a_replay_status_persisted_and_disclosed
  P0b anchored_ratio badge   : test_p0b_anchored_ratio_projector
  P0c line19 footnote        : test_p0c_line19_qualified (doc-honesty)
  P3b notebook-drift alert   : test_p3b_notebook_drift_alert

# KG: LakatosTree_ManifestoGap_20260702 / followup-R8
"""
from __future__ import annotations

from pathlib import Path

from lakatos.quant.metrics import tree_metrics
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import NodeIn, TestResultIn as Result
from server.contexts.tree.writer import TreeKgWriter

ROOT = Path(__file__).resolve().parents[2]


# ── S3: writer 파라미터화 SET 도 scripted verdict 를 보존(H9 스캐너 사각 봉합) ──────────────
class _FakeKg:
    def __init__(self, seed):
        self.store = {k: dict(v) for k, v in seed.items()}

    def __call__(self, ops):
        out = []
        for query, params in ops:
            if 'MERGE (e:LakatosNode' in query and 'e.verdict' in query:
                guarded = 'CASE WHEN coalesce(e.verdict_source' in query
                forceful = params.get('forceful') or []
                for row in (params.get('rows') or [params]):
                    tag = row.get('tag', params.get('tag'))
                    node = self.store.setdefault(f"{params.get('tree')}/{tag}", {})
                    if not (guarded and node.get('verdict_source') in forceful):
                        node['verdict'] = row.get('verdict')
            out.append([{'t': params.get('tree')}])
        return out


def test_s3_param_seal_preserves_scored_verdict():
    # 파라미터화 SET(bulk upsert_nodes)도 scripted 'rejected' 를 draft 'proof' 로 못 덮는다.
    kg = _FakeKg({'T/seam': {'verdict': 'rejected', 'verdict_source': 'scripted'}})
    TreeKgWriter(kg_tx=kg).upsert_nodes('T', [NodeIn(tag='seam', verdict='proof')])
    assert kg.store['T/seam']['verdict'] == 'rejected', 'bulk 파라미터화 SET 이 scripted 봉인 우회(S3)'
    # writer 소스에 파라미터화 SET *양쪽*(add_node·upsert_nodes)이 _PRESERVE_IF_SCORED 를 포함.
    src = (ROOT / 'server/contexts/tree/writer.py').read_text(encoding='utf-8')
    assert src.count('_PRESERVE_IF_SCORED.format') >= 2, 'H9 param-seal 이 한 경로만 가드(비대칭 누수)'


# ── P0a: replay_status persist + 공시 ─────────────────────────────────────────────────────
class _SubmitKg:
    def __init__(self):
        self.captured = []
        self.node = {'current_receipt_sha': None}

    def __call__(self, query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': '',
                     'vsrc': None, 'nmet': None, 'ndir': None, 'nthr': None, 'psha': None,
                     'closes': None, 'n_opened': 0, 'pred_registered_at': '2026-07-03',
                     'node_state': 'PREDICTED', 'judged_at': None, 'existing_metric_value': None,
                     'hard_core': '', 'require_novel_anchor': False, 'assurance_tier': None,
                     'attestor_dids': None, 'prev_receipt_sha': None}]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{'claimed': 'seam'}] for _ in ops]


def _svc(kg, replay):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None,
                            producer_replay_for_node=lambda n, t: replay)


def test_p0a_replay_status_persisted_and_disclosed():
    # replay 미시도(None)/일치(True)/불일치(False) → label persist.
    for replay, expect in [(None, 'not_attempted'), (True, 'verified'), (False, 'mismatch')]:
        kg = _SubmitKg()
        _svc(kg, replay).submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline'))
        _q, params = kg.captured[0][0]
        assert params.get('replay_status') == expect, f"replay={replay} → {params.get('replay_status')}"
        assert 'e.replay_status=$replay_status' in _q, 'SET 절에 replay_status 없음(persist 누락)'
    # 공시: repository RETURN 에 replay_status alias(R1 bijection 가드와 정합).
    repo = (ROOT / 'server/contexts/tree/repository.py').read_text(encoding='utf-8')
    assert 'e.replay_status AS replay_status' in repo, 'replay_status 비공시(read 표면 누락)'


# ── P0b: anchored_ratio projector ─────────────────────────────────────────────────────────
def _n(tag, nsa):
    return dict(tag=tag, verdict='progressive', novel_server_anchored=nsa, parents=[],
                parent_edges=[], node_state='JUDGED_SCRIPTED')


def test_p0b_anchored_ratio_projector():
    m = tree_metrics([_n('a', True), _n('b', False), _n('c', None), _n('d', True)], [])
    a = m['anchored']
    assert a['novel_measured'] == 3 and a['server_anchored'] == 2, a   # None 은 분모 제외
    assert a['anchored_ratio'] == round(2 / 3, 3)
    # novel 판정 노드 0 → None(거짓 0 아님).
    assert tree_metrics([_n('x', None)], [])['anchored']['anchored_ratio'] is None


# ── P3b: notebook-drift alert ─────────────────────────────────────────────────────────────
def test_p3b_notebook_drift_alert():
    m = tree_metrics([_n('a', True), _n('b', False)], [])   # 1/2 서버앵커
    assert any('서버앵커 안 된 novel' in x for x in m['alerts']), m['alerts']
    # 전부 앵커 = 알럿 없음(정상).
    m2 = tree_metrics([_n('a', True), _n('b', True)], [])
    assert not any('서버앵커 안 된 novel' in x for x in m2['alerts'])


# ── P0c: line19 각주(doc-honesty) ─────────────────────────────────────────────────────────
def test_p0c_line19_qualified():
    md = (ROOT / 'TOUCH_THE_SKY.md').read_text(encoding='utf-8')
    line19 = '그래서 우리의 한 칸은 — 단 한 칸이라도 — 결코 가짜가 아니다.'
    assert line19 in md
    # 무단서 현재시제 단언이 아니라 각주로 조건(ManifestoGap 채점·레거시 보존·진행형 목표)을 명시.
    idx = md.index(line19)
    assert md[idx + len(line19):idx + len(line19) + 4].startswith('[^1]'), '19행 각주 마커 부재'
    assert '진행형 목표' in md and 'test_doc_honesty' in md, '각주가 갭의 조건성을 명시하지 않음'
