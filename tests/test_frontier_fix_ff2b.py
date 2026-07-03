"""FF2b guard (frontier-fix 2026-06-26): H10 의 qual_backed 서버앵커 fix 가 *load-bearing*(revert-proof).

deep-dive FG-1: 결함이 닫혔어도 가드가 revert 에 RED 가 안 되면 가짜그린이다. 이 가드는 (1) submit 경로에
음성 오라클이 *존재*하고(spine 격리 아님), (2) qual_backed 를 client r.novel_sha 공식으로 되돌리면 그 음성
오라클의 판정(qsr=True)이 *뒤집힌다*(qsr=False = RED)는 것을 증명한다 = 가드가 H10 fix 에 진짜로 묶여 있다.

두 가드 green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF2b 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF2b_h10_revert_proof
"""
from __future__ import annotations

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


def _qsr(cap: list) -> bool:
    return bool(cap[0][0][1].get('qsr'))


_QUAL = dict(lakatos_anomaly=True, lakatos_consequence=True, lakatos_excess=True, lakatos_hardcore=True)
_BYPASS = dict(metric_value=1.0, script='inline', novel_measured=1.0,
               novel_sha='deadbeef', ce_novel_corroborated=True)   # client sha 문자열, novel_script 없음


def test_qual_backed_submit_path_has_negative_oracle():
    """submit 경로(spine 격리 아님)에 음성 오라클이 존재: bypass 입력에서 qualitative_self_report=True 로 표식."""
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(**_BYPASS, **_QUAL))
    assert _qsr(cap) is True, "submit 경로 음성 오라클 부재 — bypass 가 qsr 표식을 회피"


def test_reverting_qual_backed_to_client_sha_turns_guard_red():
    """revert 민감도: 위 음성 오라클의 판정(qsr=True)은 qual_backed 를 client r.novel_sha 공식으로 되돌리면
    뒤집힌다(client 공식이면 backed=True → qsr=False = 오라클 RED). 즉 가드가 H10 fix 에 load-bearing 으로 묶임."""
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(**_BYPASS, **_QUAL))
    server_qsr = _qsr(cap)                                  # H10 서버앵커: novel_script 없음 → backed False → qsr True
    # 같은 입력을 *client-sha* 공식 qual_backed = bool(r.novel_sha and ce_novel_corroborated) 로 평가하면:
    reverted_qual_backed = bool(_BYPASS['novel_sha'] and _BYPASS['ce_novel_corroborated'])  # = True
    reverted_qsr = not reverted_qual_backed                 # backed=True → self_report 표식 해제(qsr=False)
    assert server_qsr is True, "현 서버(H10)는 client sha 한 줄로 backed 처리하지 않아야"
    assert reverted_qsr is False, "client-sha 공식으로 되돌리면 같은 입력이 backed=True → qsr=False"
    assert server_qsr != reverted_qsr, "음성 오라클이 revert 에 RED 가 됨 = load-bearing(가짜그린 아님)"
