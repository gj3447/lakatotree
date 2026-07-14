"""novel-anchor freshen (Task#2 Phase B, 2026-07-03): novel_not_server_anchored 로 partial 에 묶인
scripted 노드를 *동일 측정의 서버앵커 재제출* 로 승급하는 유일한 좁은 통로.

배경: FF1/G6 이후 cross-metric novel 은 서버앵커(novel_script 파일 재유도) 없이 progressive 를 못
빚는다(정당). 그런데 앵커 실패의 흔한 원인이 *운영*(주석 섞인 커맨드 문자열 제출, LAKATOS_SCRIPT_ROOTS
루트 밖)이라, 측정 자체는 정직했던 노드들이 partial 에 영구히 묶인다 — vsrc=='scripted' 409 가
모든 재제출을 막기 때문. G1 정전은 "바이트동일 재제출 = freshen"이다: 측정값이 한 글자도 안 바뀐
재제출은 re-roll 이 아니다.

freshen 통로의 전 조건(전부 AND — 하나라도 빠지면 기존 409 유지):
  1. 기존 verdict == 'partial' AND lakatos_status == 'novel_not_server_anchored' (앵커-데모트 계급만)
  2. 제출 metric_value == 저장된 metric_value (값 동일 = freshen; 다르면 re-roll → 409)
  3. 이번 제출의 script *와* novel_script 가 둘 다 서버앵커됨 (아니면 freshen 자격 없음 → 409)
기존 sha 가드(사전등록 psha vs 서버재계산)는 그대로 통과해야 한다 — 다른 스크립트로 바꿔치기 불가.
승급은 덮어쓰기가 아니라 *새 VerdictReceipt 를 체인에 append* (G1 append-only, prev 포인터 전진).

# KG: LakatosTree_NovelAnchorProbe_20260703 (Phase A 프로브), LakatosTree_FrontierFix_20260626/FF1
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result


def _svc(captured: list, *, existing_verdict: str = 'partial',
         existing_lstat: str = 'novel_not_server_anchored',
         existing_metric_value: float = 1.0) -> JudgementService:
    """이미 scripted 로 채점된(vsrc='scripted') cross-metric novel 노드 + anchored-tier 트리 fake KG."""
    def kg(query, **p):
        if 'pred_metric AS m' in query:
            return [{'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio',
                     'novel': 'novel claim', 'vsrc': 'scripted',
                     'nmet': 'novelaxis', 'ndir': 'higher', 'nthr': 1.0,
                     'psha': None, 'closes': None, 'n_opened': 0,
                     'pred_registered_at': '2026-07-02T00:00:00+00:00',
                     'node_state': 'JUDGED_SCRIPTED', 'judged_at': '2026-07-02T01:00:00+00:00',
                     'existing_metric_value': existing_metric_value,
                     'existing_verdict': existing_verdict, 'existing_lstat': existing_lstat,
                     'prev_receipt_sha': 'aa' * 32,
                     'hard_core': None, 'require_novel_anchor': True,
                     'assurance_tier': None, 'attestor_dids': None}]
        return []
    def kg_tx(ops):
        captured.append(ops)
        return [[{'claimed': 'n'}] for _ in ops]
    return JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def _params(cap: list) -> dict:
    return cap[0][0][1]


def test_freshen_upgrades_anchor_demoted_partial(tmp_path):
    """양성(freshen 통로): partial(novel_not_server_anchored) 노드에 동일 metric_value + 서버앵커
    script/novel_script 재제출 → progressive 승급 + 새 receipt append (prev 포인터 = 기존 head)."""
    j = tmp_path / "judge.py"
    j.write_bytes(b"print('measure: 1.0')\n")
    cap: list = []
    out = _svc(cap).submit_test_result('T', 'n', Result(
        metric_value=1.0, script=str(j), novel_measured=1.0, novel_script=str(j)))
    p = _params(cap)
    assert p['v'] == 'progressive_unverified', p
    assert p['novel'] is True, p
    assert p['prev_rsha'] == 'aa' * 32, 'receipt 는 기존 체인 head 에 append 되어야 한다'
    assert out.get('freshen') is True, out


def test_freshen_refuses_changed_metric_value(tmp_path):
    """음성(re-roll 차단): metric_value 가 저장값과 다르면 freshen 이 아니라 re-roll — 409 유지."""
    j = tmp_path / "judge.py"
    j.write_bytes(b"print('measure')\n")
    with pytest.raises(HTTPException) as e:
        _svc([]).submit_test_result('T', 'n', Result(
            metric_value=2.0, script=str(j), novel_measured=1.0, novel_script=str(j)))
    assert e.value.status_code == 409


def test_freshen_refuses_unanchored_resubmission():
    """음성(앵커 필수): 서버앵커 없는 재제출(script inline / novel_script 부재)은 freshen 자격이 없다
    — client 문자열 재제출로 승급을 살 수 없다(FF1 봉합 유지)."""
    with pytest.raises(HTTPException) as e:
        _svc([]).submit_test_result('T', 'n', Result(
            metric_value=1.0, script='inline', novel_measured=1.0))
    assert e.value.status_code == 409


def test_non_anchor_demoted_scripted_nodes_stay_locked(tmp_path):
    """회귀가드: 앵커-데모트 계급이 아닌 scripted 노드(예: 이미 progressive)는 앵커 재제출이어도
    409 그대로 — freshen 은 novel_not_server_anchored partial *전용* 좁은 통로다."""
    j = tmp_path / "judge.py"
    j.write_bytes(b"print('measure')\n")
    with pytest.raises(HTTPException) as e:
        _svc([], existing_verdict='progressive', existing_lstat='unverified').submit_test_result(
            'T', 'n', Result(metric_value=1.0, script=str(j), novel_measured=1.0, novel_script=str(j)))
    assert e.value.status_code == 409
