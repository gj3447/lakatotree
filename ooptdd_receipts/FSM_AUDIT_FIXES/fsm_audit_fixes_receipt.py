"""FSM/in-toto 감사 수리 영수증 — PROM16 검증 팬아웃(2026-07-28) DEFECT 4건의 봉인.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 node_state/fsck/writer/
layout_gate 불변). 재구현 금지 — tests/test_fsm_audit_fixes_20260728.py ·
tests/test_layout_fail_closed_20260728.py 의 픽스처/호출을 그대로 차용한다.

음성 오라클(no-fake-green): ①정상 DRAFT→PREDICTED 전이가 막히면 죽는다(과잉 차단)
②정렬된 노드에서 NODE_STATE_DRIFT 가 발화하면 죽는다 ③미선언 layout 트리가 422 를 맞으면
죽는다(라이브 대다수 무회귀 계약). 수리 전 코드였다면 양성 3개가 전부 assert 에서 깨진다.
# KG: prom16-lakatotree-advancement-20260728
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

import json  # noqa: E402
import os  # noqa: E402

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from fastapi import HTTPException  # noqa: E402

from lakatos import layout as layout_mod  # noqa: E402
from lakatos.node_state import NodeState, derive_node_state, transition_allowed  # noqa: E402
from lakatos.verdicts import FORCEFUL_SOURCES  # noqa: E402
from lakatos.write_cert import did_key_encode, ed25519_public_key, ed25519_sign  # noqa: E402
from server.contexts.audit.fsck import fsck_node  # noqa: E402
from server.contexts.tree.layout_gate import resolve_role_layout  # noqa: E402
from server.contexts.tree.writer import _FORCEFUL  # noqa: E402

_S = bytes([11]) * 32
DID = did_key_encode(ed25519_public_key(_S))


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.fsm.audit_fixes", "event": name, **attrs}


def _signed_layout(expires=None, break_sig=False):
    lo = {"layout_version": 1,
          "steps": [{"verb": "register_prediction", "pubkeys": [DID], "threshold": 1}]}
    if expires:
        lo["expires"] = expires
    sig = 'ff' * 64 if break_sig else ed25519_sign(_S, layout_mod.canonical_layout_blob(lo)).hex()
    return dict(research_layout=json.dumps(lo, ensure_ascii=False),
                layout_owner_did=DID, layout_sig=sig)


def verify(backend, cid):
    """FSM 전이·상태정합·layout fail-closed 를 실코드로 구동."""
    # (1) 강등 세탁 차단 — 전체 row 파생은 FORMER_CANONICAL 이고 재채점 전이는 불법.
    demoted = dict(tag='n', verdict='former_canonical', verdict_source='engine',
                   pred_registered_at='2026-07-01', pred_metric='m',
                   metric_value=1.0, judged_at='2026-07-02')
    full = derive_node_state(demoted)
    partial = derive_node_state({k: v for k, v in demoted.items() if k != 'verdict'})
    assert full == NodeState.FORMER_CANONICAL and partial == NodeState.JUDGED_SCRIPTED
    assert not transition_allowed(full, NodeState.JUDGED_SCRIPTED), '강등 세탁 전이가 허용됨'
    assert transition_allowed(NodeState.DRAFT, NodeState.PREDICTED), '정상 전이 과잉 차단'
    import inspect
    from server.contexts.tree import judgement_service as js
    src = inspect.getsource(js.JudgementService.submit_test_result)
    assert "'verdict': pr.get('existing_verdict')" in src, 'before-row 에 verdict 미포함'
    assert 'FORCEFUL_SOURCES' in src, '재채점 게이트가 scripted 만 봄'
    backend.ship([_ev(cid, "demotion_laundering_blocked",
                      full_state=str(full), partial_state=str(partial),
                      illegal_transition_rejected=True, normal_transition_ok=True)])

    # (2a) writer 클로버 가드 — admin 보존 + FORCEFUL 무회귀.
    assert 'admin' in _FORCEFUL and set(FORCEFUL_SOURCES) <= set(_FORCEFUL), _FORCEFUL
    backend.ship([_ev(cid, "canonical_clobber_guarded", preserve_set=sorted(_FORCEFUL))])

    # (2b) fsck node_state 드리프트 — 발화 + 정렬 시 무발화(음성 오라클).
    drifted = dict(tag='n', verdict='former_canonical', verdict_source='engine',
                   node_state='CANONICAL', judged_at='2026-07-02', metric_value=1.0,
                   pred_registered_at='2026-07-01', pred_metric='m',
                   current_receipt_sha='a' * 64, assurance_tier_resolved='legacy')
    drift_codes = [f.check_id for f in fsck_node(drifted)]
    aligned_codes = [f.check_id for f in fsck_node(dict(drifted, node_state='FORMER_CANONICAL'))]
    assert 'NODE_STATE_DRIFT' in drift_codes, drift_codes
    assert 'NODE_STATE_DRIFT' not in aligned_codes, f'정렬 노드 오발화: {aligned_codes}'
    backend.ship([_ev(cid, "node_state_drift_detected_and_silent_when_aligned",
                      drifted=drift_codes, aligned=aligned_codes)])

    # (3) layout fail-closed — 만료/서명무효/형식위반 422, 유효 통과, 미선언 무회귀.
    rejected = {}
    for name, rec in (("expired", _signed_layout(expires="2020-01-01T00:00:00+00:00")),
                      ("bad_sig", _signed_layout(break_sig=True)),
                      ("malformed", dict(research_layout='{"layout_version": 99, "steps": "no"}',
                                         layout_owner_did=DID, layout_sig='00' * 64))):
        try:
            resolve_role_layout(rec)
            rejected[name] = None
        except HTTPException as exc:
            rejected[name] = exc.status_code
    assert all(v == 422 for v in rejected.values()), f'fail-open 잔존: {rejected}'
    assert resolve_role_layout(_signed_layout()) is not None, '유효 layout 이 거부됨'
    assert resolve_role_layout({}) is None, '미선언 트리 무회귀 위반(라이브 대다수)'
    backend.ship([_ev(cid, "layout_fail_closed_enforced", rejected=rejected,
                      valid_resolves=True, undeclared_falls_back=True)])
