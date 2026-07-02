"""R1-READ — 읽기표면↔원장 동기화 가드 (후속 PROM 2026-07-02, '판독 불가 green' 봉합).

  guard_defect(음성)     : test_scored_node_ledger_fields_are_readable
        — 실 register→submit 후 실 load_tree_data 행에 원장 필드(current_receipt_sha·lakatos_status·
          novel_server_anchored·assurance_tier_resolved·attested_by_did·eureka_*·judge_script_sha 등)가
          실재하고 graph 노드패널 eureka 가 non-null. 라이브 CONFIRMED 모순(graph 패널 eureka=null vs
          전용 /eureka endpoint true — 26-06-26 유일-HIGH 동일클래스)의 테스트 재현.
  guard_mechanism(양성)  : test_every_node_set_field_is_disclosed_in_return
        — 'SET 필드 ⊆ RETURN alias' 단방향 포함 소스스캔(범위: server/contexts/tree/*.py + server/app.py,
          노드 alias e|cur|old, allowlist _cas) + 'graph_view 소비필드 ⊆ RETURN'. 미래의 어떤 SET 추가도
          공시 없이는 CI 에서 즉사 — 표류 재발의 구조적 박멸(G5 소스스캔 계약 장르).

fake 는 faithful-projection: 저장 노드 props 를 *쿼리의 `e.<prop> AS <alias>` 쌍대로* 투영하므로
RETURN 에 없는 필드는 fake 로도 안 나온다(revert-민감 — alias 지우면 defect 가드 RED).

# KG: LakatosTree_GitAbsorption_20260702 / followup-R1-read-surface
"""
from __future__ import annotations

import re
from pathlib import Path

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.repository import TreeKgRepository
from server.contexts.tree.schemas import PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result
from server.graph_view import tree_graph
from server.read_models import compute_tree_metrics

ROOT = Path(__file__).resolve().parents[2]
_SRV_TREE = ROOT / 'server' / 'contexts' / 'tree'

# 노드/트리 프로퍼티 SET 검출: alias.<field> = (비교 ==/<>/>= 제외). 노드 alias = e|cur|old(LakatosNode),
# 트리 alias = t. q/rec/bel/el/fr/rt/a/p 등 타 노드타입 alias 는 의도적으로 제외.
_NODE_SET_RE = re.compile(r"\b(?:e|cur|old)\.([a-z_][a-z0-9_]*)\s*=(?!=)")
_TREE_SET_RE = re.compile(r"\bt\.([a-z_][a-z0-9_]*)\s*=(?!=)")
_NODE_RETURN_RE = re.compile(r"\be\.([a-z_][a-z0-9_]*)\s+AS\s+")
_TREE_RETURN_RE = re.compile(r"\bt\.([a-z_][a-z0-9_]*)\s+AS\s+")
_ALLOW_NODE = frozenset({'_cas'})          # CAS 더미 — 원장 필드 아님
_ALLOW_TREE = frozenset()
# graph_view 가 소비하나 RETURN 밖에서 합성되는 키(post-normalize 주입/계산).
_COMPUTED_ROW_KEYS = frozenset({'source', 'tag', 'parent', 'parents', 'parent_edges', 'questions'})


def _scan(pattern: re.Pattern, files) -> set:
    out: set = set()
    for f in files:
        out |= set(pattern.findall(f.read_text(encoding='utf-8')))
    return out


def _repo_return_props() -> tuple[set, set]:
    src = (_SRV_TREE / 'repository.py').read_text(encoding='utf-8')
    return set(_NODE_RETURN_RE.findall(src)), set(_TREE_RETURN_RE.findall(src))


# ── guard_mechanism (양성): SET ⊆ RETURN 소스스캔 — 표류의 구조적 봉쇄 ─────────────────────
def test_every_node_set_field_is_disclosed_in_return():
    files = sorted(_SRV_TREE.glob('*.py')) + [ROOT / 'server' / 'app.py']
    node_set = _scan(_NODE_SET_RE, files) - _ALLOW_NODE
    tree_set = _scan(_TREE_SET_RE, files) - _ALLOW_TREE
    node_ret, tree_ret = _repo_return_props()
    missing_node = node_set - node_ret
    missing_tree = tree_set - tree_ret
    assert not missing_node, (
        f"노드 원장 SET 필드가 read-model RETURN 에 비공시: {sorted(missing_node)} — "
        f"repository.py 노드 RETURN 에 alias 추가(판독 불가 green 금지)")
    assert not missing_tree, (
        f"트리 SET 필드 비공시: {sorted(missing_tree)}")
    # 비진공: 스캔이 실제로 원장 필드를 보고 있다(핵심 필드 표본이 SET 집합에 실재).
    assert {'verdict', 'current_receipt_sha', 'lakatos_status', 'canonical_scope'} <= node_set


def test_graph_view_consumes_only_disclosed_fields():
    src = (ROOT / 'server' / 'graph_view.py').read_text(encoding='utf-8')
    consumed = set(re.findall(r"\br\.get\('([a-z_][a-z0-9_]*)'\)", src)) | \
               set(re.findall(r"\br\['([a-z_][a-z0-9_]*)'\]", src))
    node_ret, _ = _repo_return_props()
    undisclosed = consumed - node_ret - _COMPUTED_ROW_KEYS
    assert not undisclosed, (
        f"graph_view 가 RETURN 밖 필드를 소비(항상 null 렌더 — 표면간 모순 장르): {sorted(undisclosed)}")


# ── guard_defect (음성): 실 경로 왕복 — 채점 원장이 read 표면에서 판독된다 ───────────────────
class _ParityKg:
    """faithful-projection 더블: 쓰기는 쿼리의 `e.<f>=$p` 쌍대로 적용, 읽기는 쿼리의
    `e.<f> AS <alias>`/`t.<f> AS <alias>` 쌍대로 투영 — RETURN 에 없으면 저장돼 있어도 안 보인다."""

    _ASSIGN = re.compile(r"\be\.([a-z_][a-z0-9_]*)\s*=\s*\$([a-z_][a-z0-9_]*)")

    def __init__(self, tag: str):
        self.tag = tag
        self.node: dict = {'tag': tag, 'verdict': 'proof', 'node_state': 'DRAFT'}
        self.tree: dict = {'title': 'T', 'hard_core': '', 'require_novel_anchor': False}

    def _apply(self, query: str, params: dict) -> None:
        for field, pname in self._ASSIGN.findall(query):
            if pname in params:
                self.node[field] = params[pname]

    def _project(self, query: str) -> dict:
        row: dict = {}
        for prop, alias in re.findall(r"\be\.([a-z_0-9]+)\s+AS\s+([a-z_0-9]+)", query):
            row[alias] = self.node.get(prop)
        for prop, alias in re.findall(r"\bt\.([a-z_0-9]+)\s+AS\s+([a-z_0-9]+)", query):
            row[alias] = self.tree.get(prop)
        return row

    def __call__(self, query, **params):   # KgQuery — 읽기 + register 의 가드된 SET
        if 'SET' in query and 'HAS_NODE' in query:
            self._apply(query, params)
            return [{'tag': self.tag}]
        if 'HAS_FRONTIER' in query or 'ResearchEvent' in query:
            return []
        row = self._project(query)
        return [row] if row else []

    def tx(self, ops):   # KgTx — submit #M5(판결 SET + receipt MERGE)
        for query, params in ops:
            if 'HAS_NODE' in query and 'SET' in query:
                self._apply(query, params)
        return [[{'claimed': self.tag}] for _ in ops]


def test_scored_node_ledger_fields_are_readable():
    kg = _ParityKg('seam')
    svc = JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    # 실 사전등록(cross-metric novel) → 실 채점: legacy 트리(FF1 off) → progressive + eureka felt.
    svc.register_prediction('T', 'seam', PredictionIn(
        metric_name='p95', direction='lower', baseline_value=10.0, noise_band=0.0,
        novel_prediction='novel claim', novel_metric='novelaxis', novel_direction='higher',
        novel_threshold=1.0, closes_question='q-x'))
    out = svc.submit_test_result('T', 'seam', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    assert out['verdict'] == 'progressive', out

    td = TreeKgRepository(kg).load_tree_data('T')
    row = next(r for r in td['nodes'] if r['tag'] == 'seam')
    # 원장 13필드 판독 — RETURN 에서 alias 를 지우면(revert) 여기서 RED.
    assert row.get('current_receipt_sha'), 'G1 체인 머리 비공시'
    assert row.get('lakatos_status') is not None, '강등/판정 사유(lakatos_status) 비공시 — partial 원인 판독 불가'
    assert row.get('assurance_tier_resolved') == 'legacy', 'G6 tier 스탬프 비공시'
    assert row.get('novel_server_anchored') is not None, 'FF1 앵커 여부 비공시'
    assert row.get('judge_script_sha') is not None, '채점 스크립트 sha 비공시'
    assert row.get('eureka_felt') is True and row.get('eureka_hallucinated') is not None, 'eureka 원장 비공시'
    assert 'attested_by_did' in row, 'G10 authorship 스탬프 alias 부재'   # 무cert=None 도 키는 실재
    assert row.get('qualitative_self_report') is not None
    # 예측측 novel 타깃 판독(F4): 무엇을 novel 로 걸었는지 API 로 재구성 가능해야.
    assert row.get('pred_novel_metric') == 'novelaxis' and row.get('pred_novel_threshold') == 1.0
    # 미채점 센티널 보존(tri-state): 신규 draft 의 eureka_felt 는 None 이어야(bool 강제 금지).
    kg2 = _ParityKg('draft')
    td2 = TreeKgRepository(kg2).load_tree_data('T')
    row2 = next(r for r in td2['nodes'] if r['tag'] == 'draft')
    assert row2.get('eureka_felt') is None and row2.get('novel_server_anchored') is None

    # graph 노드패널 — 라이브 모순의 재현: 채점 노드의 패널 eureka 가 non-null 이어야.
    panel_graph = tree_graph(td, compute_tree_metrics(td))
    node = next(n for n in panel_graph['nodes'] if n.get('tag') == 'seam' or n.get('id') == 'seam')
    eureka = node['panel']['eureka']
    assert eureka['felt'] is not None, 'graph 패널 eureka=null — 표면간 모순(라이브 CONFIRMED) 재현'


def test_tree_policy_fields_are_readable():
    """제출 전에 '이 트리는 어떤 게이트가 발동하나'(FF1/G10)를 API 로 알 수 있다 — 놀라게 하는 403/partial 방지."""
    kg = _ParityKg('x')
    kg.tree.update(require_novel_anchor=True, attestor_dids=['did:key:zTest'], assurance_tier='anchored')
    td = TreeKgRepository(kg).load_tree_data('T')
    assert td.get('require_novel_anchor') is True, 'FF1 정책 비공시'
    assert td.get('attestor_dids') == ['did:key:zTest'], 'G10 attestor allow-list 비공시'
