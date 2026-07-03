"""FF1 guard (frontier-fix 2026-06-26, THESIS 머리): cross-metric novel 이 *서버앵커 영수증* 없이는
progressive 를 빚지 못한다(opt-in tree policy require_novel_anchor=True). client float 한 줄로 '진보'를
사는 구멍(judge.py:134 noindep 가 same-metric 만 게이트)을 server 경계에서 닫는다.

데모트는 server submit_test_result 에서만 — judge() 는 순수 유지(run() 도그푸드/직접 judge 무영향).
정책은 opt-in(기본 off=비파괴): 플래그 off 면 기존 동작 그대로(회귀가드로 고정).

두 가드(defect/mechanism) green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF1 을 progressive
로 자동 채점. # KG: LakatosTree_FrontierFix_20260626 / FF1_cross_metric_novel_client_float
"""
from __future__ import annotations

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result


def _svc(captured: list, *, require_anchor: bool) -> JudgementService:
    """cross-metric novel(nmet='novelaxis' ≠ m='seam') 사전등록 노드 + 트리 정책 플래그를 단 fake KG."""
    def kg(query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': None,
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0,
                     'psha': None, 'closes': None, 'n_opened': 0,
                     'require_novel_anchor': require_anchor}]
        return []
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _params(cap: list) -> dict:
    """판결 SET op(첫 op)의 cypher 파라미터."""
    return cap[0][0][1]


def test_cross_metric_novel_bare_client_float_cannot_mint_progressive():
    """음성 오라클: 정책 on + cross-metric novel(nmet≠m) + 서버앵커 없음(novel_script 미제공, client float 만)
    → progressive 가 *아니라* partial. 영수증 없는 client 숫자 하나로 '진보'를 못 산다(thesis 머리 봉합)."""
    cap: list = []
    _svc(cap, require_anchor=True).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))   # novel_script 없음 = 서버앵커 부재
    p = _params(cap)
    assert p['v'] == 'partial', p
    assert p['novel'] is False, p                                  # 독립 confirmed 아님
    assert p['lstat'] == 'novel_not_server_anchored', p


def test_cross_metric_novel_requires_server_readback_or_sha(tmp_path):
    """양성: cross-metric novel 도 *서버 재유도* novel_script 영수증이 있으면 progressive 로 인정(과잉차단 아님)."""
    m = tmp_path / "novel_measure.py"
    m.write_bytes(b"print('independent novel: 1.0')\n")
    cap: list = []
    _svc(cap, require_anchor=True).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, novel_script=str(m)))
    p = _params(cap)
    assert p['v'] == 'progressive', p
    assert p['novel'] is True, p


def test_policy_is_opt_in_off_by_default_non_breaking():
    """회귀가드(비파괴): 정책 off(기본)면 같은 unbacked cross-metric novel 이 *여전히* progressive — 데모트 없음.
    기존 트리/테스트는 플래그를 안 켜므로 행동 불변(마이그레이션 불요)."""
    cap: list = []
    _svc(cap, require_anchor=False).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0))
    assert _params(cap)['v'] == 'progressive'
