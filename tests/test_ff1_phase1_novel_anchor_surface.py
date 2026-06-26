"""FF1 Phase 1 (frontier-fix 2026-06-26, NON-breaking 가시성): cross-metric novel 의 *서버앵커 여부* 를
노드에 영속(novel_server_anchored) + CLI/MCP 가 novel_script 를 받아 실-에이전트가 서버앵커 novel 을
*제공할 수 있게* 한다(이전엔 surface 가 novel_measured client float 만 노출 → 서버앵커 불가능).

★점수(verdict)는 *불변* — 데모트(unbacked cross-metric novel → partial)는 Phase 2(트리-레벨 정책 플래그)로
미룬다. 그래서 이 파일은 FF1 의 guard(test_cross_metric_novel_*)가 아니다 — FF1 노드는 Phase 2 까지 pending.
# KG: LakatosTree_FrontierFix_20260626 / FF1 (phase 1 enabling)
"""
from __future__ import annotations

import inspect
import pathlib

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result


def _svc(captured: list) -> JudgementService:
    def kg(query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': None,
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0,
                     'psha': None, 'closes': None, 'n_opened': 0}]
        return []
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _verdict_params(cap: list) -> dict:
    """판결 SET op(첫 op)의 cypher 파라미터."""
    return cap[0][0][1]


def test_unanchored_cross_metric_novel_keeps_progressive_but_flags_not_anchored():
    """Phase1 비파괴: novel_script 없는 cross-metric novel(client float 만)은 *여전히 progressive*(점수 불변)
    이되 novel_server_anchored=False 로 표식(가시성 — Phase2 데모트의 대상이 KG 쿼리로 드러난다)."""
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    p = _verdict_params(cap)
    assert p['v'] == 'progressive'          # 데모트 없음(Phase1)
    assert p['nsa'] is False                # 서버앵커 아님 = FF1 구멍 인스턴스로 가시화


def test_server_anchored_novel_is_flagged_anchored(tmp_path):
    """novel_script(서버 재계산 가능)을 제공하면 novel_server_anchored=True."""
    m = tmp_path / "novel_measure.py"
    m.write_bytes(b"print('independent novel: 1.0')\n")
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, novel_script=str(m)))
    assert _verdict_params(cap)['nsa'] is True


def test_cli_and_mcp_expose_novel_script():
    """실-에이전트 surface 가 novel_script 를 받는다(이전엔 novel_measured client float 만 → 서버앵커 불가)."""
    from lakatos import cli, mcp_server
    assert 'novel_script' in inspect.signature(mcp_server.submit_result).parameters
    assert "--novel-script" in pathlib.Path(cli.__file__).read_text()
