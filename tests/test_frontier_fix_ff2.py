"""FF2 guard (frontier-fix 2026-06-26): H10(1dc0e3f)이 qual_backed 를 *서버앵커* novel_server_sha 로 닫았음을
submit 경로에서 검증 — client novel_sha 문자열 + ce_corroborated 만으로는 질적 self-report 표식을 못 끈다.

deep-dive FG-1: 기존 H1 가드는 spine.synthesize_promotion *격리* 만 운동해 submit-측 유도(qual_backed)를
안 봤다. 이 가드는 JudgementService.submit_test_result 의 qual_backed/qualitative_self_report 유도를 직접
운동한다(revert-sensitive: qual_backed 가 client r.novel_sha 로 되돌아가면 RED — FF2b 참고).

두 가드 green 착륙 시 examples/frontier_fix_20260626_programme.py 가 FF2 를 progressive 로 자동 채점.
# KG: LakatosTree_FrontierFix_20260626 / FF2_h1_qual_backed_client_hatch
"""
from __future__ import annotations

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result   # 별칭: pytest Test* 수집 경고 회피


def _svc(captured: list) -> JudgementService:
    """사전등록 novel target 을 든 미채점 노드 + 원자 CAS 성공 KG (test_design_audit_h1 패턴)."""
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
    """캡처된 판결 SET op 의 qualitative_self_report 파라미터($qsr)."""
    return bool(cap[0][0][1].get('qsr'))


_QUAL = dict(lakatos_anomaly=True, lakatos_consequence=True, lakatos_excess=True, lakatos_hardcore=True)


def test_client_novel_sha_string_does_not_clear_qual_self_report_on_submit():
    """음성 오라클(revert-sensitive): 질적 self-report + client novel_sha 문자열 + ce_corroborated 이되
    *서버앵커* novel_script 가 없으면 qualitative_self_report 표식이 *유지*(True). client 한 줄로 못 끈다."""
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, novel_sha='beef',   # client sha 문자열
        ce_novel_corroborated=True, **_QUAL))                                       # novel_script 없음 → 서버앵커 부재
    assert _qsr(cap) is True


def test_qual_backing_requires_server_recomputed_sha(tmp_path):
    """양성: 질적 backing 이 *서버 재계산* novel_script 영수증 + ce_corroborated 이면 표식 해제(False) — 과잉차단 아님."""
    measure = tmp_path / "novel_measure.py"
    measure.write_bytes(b"print('independent excess: 1.0')\n")
    cap: list = []
    _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script='inline', novel_measured=1.0, novel_sha='beef',
        novel_script=str(measure),                                                  # 서버앵커 novel 영수증
        ce_novel_corroborated=True, **_QUAL))
    assert _qsr(cap) is False
