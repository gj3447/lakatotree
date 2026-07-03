"""설계감사 H10(완성-후 로드맵 2026-06-26) — qual_backed 가 client novel_sha 문자열을 영수증으로 신뢰.

client-receipt 클래스의 처치가능 슬라이스: H1 은 질적 self-report(lakatos_*/ce_* bool)가 독립 novel
영수증 없이 progressive 를 떠받치면 표식(qualitative_self_report=True)해 CANONICAL floor 를 막는다. 그런데
그 '독립 영수증 존재' 판정(judgement_service.py:437)이 `qual_backed = bool(r.novel_sha and ce_novel_corroborated)`
— *raw client r.novel_sha* 를 쓴다. H6 가 이미 r.novel_sha 가 임의 문자열로 위조 가능함을 증명했는데, H1 의
backing 체크는 여전히 그 문자열을 신뢰 → client 가 novel_sha="아무거나" + ce_novel_corroborated=True 로
qual_backed=True 를 만들어 self-report 표식을 회피, 영수증 없는 질적 progressive 가 CANONICAL floor 를 연다.

수정: qual_backed 를 H6 의 *서버앵커* novel 영수증(novel_server_sha = _recompute_script_sha(r.novel_script))
으로 바인딩. client 문자열 한 줄로 질적-backing 을 못 산다(H1↔H6 사이 잔여 봉합). ce_novel_corroborated
자체(이 측정이 초과내용을 corroborate 하는가)는 construct-validity 라 client 판단으로 남음(천장).
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as _TestResultIn  # noqa: N814


def _kg_tx(captured):
    def kg_tx(ops):
        ops = list(ops)
        captured.append(ops)
        return [[{"claimed": "v"}]] + [[] for _ in ops[1:]]
    return kg_tx


def _svc(kg, captured):
    return JudgementService(kg=kg, kg_tx=_kg_tx(captured), hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None)


def _pred_kg():
    """예측 metric=acc + novel_target metric=recall(다른 축 → 독립성 게이트 밖, novel 그대로 선다)."""
    def kg(q, **kw):
        if "RETURN e.pred_metric" in q:
            return [dict(m="acc", d="higher", b=0.5, nb=0.0, novel="새 recall 초과경험내용", vsrc=None,
                         nmet="recall", ndir="higher", nthr=0.8, psha=None, closes=None, n_opened=0)]
        return []
    return kg


def _qsr_param(captured):
    """판결 SET op 의 qualitative_self_report 파라미터($qsr)."""
    for ops in captured:
        for (c, p) in ops:
            if "e.verdict_source='scripted'" in c and "RETURN e.tag AS claimed" in c:
                return p.get("qsr")
    return None


_QUAL = dict(lakatos_anomaly=True, lakatos_consequence=True, lakatos_excess=True, lakatos_hardcore=True)


def test_client_novel_sha_string_does_not_back_qualitative_claim(tmp_path):
    """★핵심: novel_script 없이 client novel_sha 문자열 + ce_novel_corroborated 만으론 질적-backing 불가
    → qualitative_self_report=True 표식(영수증 없는 질적 progressive 가 floor 를 못 연다)."""
    pred = tmp_path / "p.py"; pred.write_bytes(b"print('acc: 0.9')\n")
    import hashlib
    pred_sha = hashlib.sha256(pred.read_bytes()).hexdigest()
    cap: list = []
    _svc(_pred_kg(), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.9, script=str(pred), script_sha=pred_sha,
                                novel_measured=0.9, novel_sha="d" * 64,   # client 문자열만(서버앵커 아님)
                                ce_novel_corroborated=True, **_QUAL))
    assert _qsr_param(cap) is True, \
        "client novel_sha 문자열만으로 질적 claim 이 backed 처리됨 → self-report 표식 회피(H10 결함)"


def test_server_anchored_novel_script_backs_qualitative_claim(tmp_path):
    """과잉차단 회귀가드: 실 novel_script(서버 재계산 가능) + ce_novel_corroborated 면 질적 claim 이 정당히
    backed → qualitative_self_report=False(표식 안 함)."""
    pred = tmp_path / "p.py"; pred.write_bytes(b"print('acc: 0.9')\n")
    measure = tmp_path / "m.py"; measure.write_bytes(b"print('independent recall: 0.9')\n")
    cap: list = []
    _svc(_pred_kg(), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.9, script=str(pred), novel_measured=0.9,
                                novel_script=str(measure),   # 서버앵커 novel 영수증
                                ce_novel_corroborated=True, **_QUAL))
    assert _qsr_param(cap) is False, \
        "서버앵커 novel 영수증이 있는데 질적 claim 이 self-report 로 표식됨 → 과잉차단"
