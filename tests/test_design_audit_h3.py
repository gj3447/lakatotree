"""H3 design-audit guard: judge_script_sha 를 서버가 *파일 내용에서* 재계산.

결함(감사 H3): submit_test_result 가 사전등록 psha 와 제출 r.script_sha 를 비교(둘 다 client 값,
동어반복) 하고, 저장도 client r.script_sha 로 한다 — '어느 스크립트가 채점했나' 영수증이 문자열 신뢰.
수정: r.script 가 읽을 수 있는 파일이면 서버가 그 내용으로 hashlib.sha256 을 *재유도*하고
  - client 제출 r.script_sha 와 불일치 → 422 (날조 sha 봉쇄)
  - 사전등록 psha 와 불일치 → 409
  - 저장(judge_script_sha)·prov 는 server_sha 로.
재계산 불가(inline/미존재 파일)면 정직 fallback: client 값 유지 + script_sha_server_verified=False.

이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 H3 를 progressive 로 자동 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as _TestResultIn  # noqa: N814 (pytest collection 회피)


def _kg_tx(captured):
    """원자 CAS 가 이기는 KG 트랜잭션 모킹 — per-op shape, 첫 op(claim) [{tag}](점유 성공)."""
    def kg_tx(ops):
        ops = list(ops)
        captured.append(ops)
        return [[{"claimed": "v"}]] + [[] for _ in ops[1:]]
    return kg_tx


def _judge(kg, captured):
    return JudgementService(kg=kg, kg_tx=_kg_tx(captured),
                            hist=lambda *a, **k: None,
                            foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def _pred_kg(psha):
    """사전등록 prediction(psha) 을 들고 vsrc=None(미채점) 인 노드. 그 외 쿼리는 빈 결과."""
    def kg(q, **kw):
        if "RETURN e.pred_metric" in q:
            return [dict(m="p95", d="lower", b=0.5, nb=0.05, novel=None, vsrc=None,
                         nmet=None, ndir=None, nthr=None, psha=psha,
                         closes=None, n_opened=0)]
        return []
    return kg


def test_judge_script_sha_recomputed_server_side(tmp_path):
    """실제 judge 스크립트를 tmp 에 쓰고 *거짓* r.script_sha 로 submit → 서버가 파일에서 재계산해 422."""
    script = tmp_path / "judge.py"
    body = b"print('measured: 0.4')\n"
    script.write_bytes(body)
    server_sha = hashlib.sha256(body).hexdigest()
    forged = "0" * 64

    # ★행동적: client 가 거짓 sha 를 제출하면 서버 재계산값과 불일치 → 422 (psha 와의 client-vs-client 비교가 아님)
    cap: list = []
    with pytest.raises(HTTPException) as e:
        _judge(_pred_kg(psha=server_sha), cap).submit_test_result(
            "T", "v", _TestResultIn(metric_value=0.4, script=str(script), script_sha=forged))
    assert e.value.status_code == 422

    # ★올바른 sha 면 통과 + 서버 *재계산값* 을 저장(client 값 신뢰 아님)
    cap2: list = []
    out = _judge(_pred_kg(psha=server_sha), cap2).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.4, script=str(script), script_sha=server_sha))
    assert out["ok"] is True
    # 판결 SET op 의 sha 파라미터가 server_sha 여야 한다(client 가 server_sha 를 제출했어도, 출처는 파일이어야 함)
    set_ops = [p for ops in cap2 for (c, p) in ops if "e.judge_script_sha=$sha" in c]
    assert set_ops and set_ops[0]["sha"] == server_sha


def test_forged_psha_blocked_by_server_recompute(tmp_path):
    """사전등록 psha 가 거짓(파일과 불일치)이면, client 가 그 거짓 psha 로 sha 를 맞춰 와도 409."""
    script = tmp_path / "judge.py"
    body = b"print('x')\n"
    script.write_bytes(body)
    server_sha = hashlib.sha256(body).hexdigest()
    forged_psha = "f" * 64

    # client 는 *올바른* server_sha 를 제출(422 통과) 하지만, 사전등록 psha 가 파일내용과 불일치 → 409.
    cap: list = []
    with pytest.raises(HTTPException) as e:
        _judge(_pred_kg(psha=forged_psha), cap).submit_test_result(
            "T", "v", _TestResultIn(metric_value=0.4, script=str(script), script_sha=server_sha))
    # server_sha != forged_psha (사전등록) → 409 (server-vs-registered, client-vs-client 아님)
    assert e.value.status_code == 409


def test_inline_or_missing_script_honest_fallback():
    """재계산 불가(미존재 파일/inline)면 정직 fallback — client sha 유지하되 server_verified=False 노출."""
    cap: list = []
    out = _judge(_pred_kg(psha=None), cap).submit_test_result(
        "T", "v", _TestResultIn(metric_value=0.4, script="inline", script_sha="a" * 64))
    assert out["ok"] is True
    # 영수증에 server-검증 실패 플래그가 정직하게 노출(동어반복 위험 숨기지 않음)
    assert out.get("script_sha_server_verified") is False
