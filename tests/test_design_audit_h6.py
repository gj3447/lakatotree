"""설계감사 H6(완성-후 적대감사 2026-06-26) — novel 독립성 게이트가 client 측정출처를 신뢰.

결함: judge() 의 novel 독립성은 measured_sha≠novel_sha 로 판정하는데(같은 metric 의 epsilon 우회 봉쇄),
submit_test_result(judgement_service.py:364)가 그 두 sha 로 *client* 값 r.script_sha / r.novel_sha 를
넘긴다. novel 측은 서버가 한 번도 재계산하지 않으므로, 동기부여된 client 는 novel_sha 를 measured 와 다른
임의 문자열로 보내 '독립'을 위조 → partial 을 progressive 로 승격한다. H3('서버가 sha 의 판관')의 교리가
정작 progressive 를 빚는 게이트에서 뚫린다.

수정: 독립성을 *양측 서버앵커* 에만 인정 — 예측측=H3 stored_sha(sha_verified), novel측=r.novel_script 본문
재유도(novel_server_sha). 둘 다 서버앵커이고 서로 다를 때만 독립. 한쪽이라도 client-only(novel_script
미제공/재계산불가, 또는 예측 script inline)면 '' 로 넘겨 같은-metric novel 을 비독립 demote. 독립은 *두 개의
서로 다른 실재 산출물* 로 증명해야 인정 — client novel_sha 한 줄로 못 산다. 다른 metric novel 은 게이트 밖.

이 guard 가 green 으로 착륙하면 design_audit_20260625_programme.py 가 H6 를 progressive 로 자동 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import hashlib

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as _TestResultIn  # noqa: N814 (pytest 수집 회피)


def _kg_tx(captured):
    def kg_tx(ops):
        ops = list(ops)
        captured.append(ops)
        return [[{"claimed": "v"}]] + [[] for _ in ops[1:]]   # 원자 CAS claim 승리
    return kg_tx


def _svc(kg, captured):
    return JudgementService(kg=kg, kg_tx=_kg_tx(captured), hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None)


def _pred_kg(*, novel_metric: str):
    """사전등록: 예측 metric='acc' + novel_target(metric=novel_metric). novel_metric=='acc' 면 같은-metric
    독립성 게이트 발동. vsrc=None(미채점), psha=None(H3 psha 체크 skip)."""
    def kg(q, **kw):
        if "RETURN e.pred_metric" in q:
            return [dict(m="acc", d="higher", b=0.5, nb=0.0, novel="새 acc 초과경험내용", vsrc=None,
                         nmet=novel_metric, ndir="higher", nthr=0.8, psha=None, closes=None, n_opened=0)]
        return []
    return kg


def _verdict_op(captured):
    """판결 SET op(원자 CAS) 파라미터 — v.novel 이 e.novel_confirmed=$novel 로 실린다."""
    for ops in captured:
        for (c, p) in ops:
            if "e.verdict_source='scripted'" in c and "RETURN e.tag AS claimed" in c:
                return p
    return None


def _scripts(tmp_path):
    pred = tmp_path / "predict.py"; pred.write_bytes(b"print('acc: 0.9')\n")
    measure = tmp_path / "measure.py"; measure.write_bytes(b"print('independent acc: 0.9')\n")
    return str(pred), str(measure)


def test_client_novel_sha_string_does_not_buy_independence(tmp_path):
    """★핵심: 같은-metric novel 에 novel_script 없이 client novel_sha 문자열만 보내면 독립 위조 불가 → demote.

    forge 시나리오: real script(script_sha=server값=H3 통과) + novel_sha=measured 와 *다른* 임의 문자열.
    수정 전엔 measured_sha(server)≠novel_sha(client 문자열)라 독립 인정(novel=True, 버그). 수정 후엔 novel
    측이 server 재계산(novel_script 미제공→'')이라 비독립 demote(novel=False).
    """
    pred, _ = _scripts(tmp_path)
    pred_sha = hashlib.sha256(open(pred, "rb").read()).hexdigest()   # H3 서버재계산 통과용 정직 sha
    cap: list = []
    _svc(_pred_kg(novel_metric="acc"), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.9, script=pred, script_sha=pred_sha, novel_measured=0.9,
                                novel_sha="d" * 64))   # novel_script 미제공 + measured 와 다른 임의 novel_sha
    op = _verdict_op(cap)
    assert op is not None, "판결 SET op 미발생"
    assert op["novel"] is False, "client novel_sha 문자열만으로 novel 독립 인정됨 → 위조 미봉쇄(H6 결함)"
    assert op["v"] == "partial", "improved 인데 novel 비독립 → partial 이어야"


def test_distinct_server_anchored_novel_script_is_independent(tmp_path):
    """novel_script 가 예측 script 와 다른 *실재 파일* → 서버가 둘 다 재계산, 서로 달라 독립 → progressive."""
    pred, measure = _scripts(tmp_path)
    cap: list = []
    out = _svc(_pred_kg(novel_metric="acc"), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.9, script=pred, novel_measured=0.9,
                                novel_script=measure))   # 독립 측정 소스 서버앵커
    assert out["ok"] is True
    op = _verdict_op(cap)
    assert op["novel"] is True, "양측 서버앵커 + 서로 다른 sha 인데 독립 불인정 → 과잉차단"
    assert op["v"] == "progressive_unverified"


def test_same_script_for_novel_is_not_independent(tmp_path):
    """novel_script == 예측 script → 서버 재계산 sha 동일 → 같은 측정 재활용 = 비독립 demote(epsilon 우회 봉쇄)."""
    pred, _ = _scripts(tmp_path)
    cap: list = []
    _svc(_pred_kg(novel_metric="acc"), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.9, script=pred, novel_measured=0.9,
                                novel_script=pred))   # 같은 산출물 — 독립 아님
    op = _verdict_op(cap)
    assert op["novel"] is False, "예측과 동일 script 인데 독립 인정됨 → epsilon 우회 미봉쇄"


def test_different_metric_novel_unaffected_by_anchor(tmp_path):
    """과잉차단 회귀가드: 다른 metric novel 은 그 자체로 독립 사실 → 독립성 게이트 밖, novel_script 불요."""
    pred, _ = _scripts(tmp_path)
    cap: list = []
    out = _svc(_pred_kg(novel_metric="recall"), cap).submit_test_result(   # 예측 metric(acc)과 다른 축
        "T", "v", _TestResultIn(metric_value=0.9, script=pred, novel_measured=0.9))
    assert out["ok"] is True
    op = _verdict_op(cap)
    assert op["novel"] is True, "다른 metric novel 이 anchor 부재로 차단됨 → 과잉차단(게이트 밖이어야)"
