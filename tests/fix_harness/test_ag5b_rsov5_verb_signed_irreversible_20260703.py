"""AG5-IDENT/R-SOV V3 — 비가역 verb 서명강제 + cert verb-판별자(sign-X-execute-Y) (측정주권 2026-07-03).

AG5-V3 는 attested *grade*(값 provenance 사다리)를 닫았다. IDENT 는 *enforcement*: 비가역 verb
(CANONICAL 승격)에 서명(write-cert)을 강제하고, cert 를 **verb 에 바인딩**해 submit 용 cert 를 canonical
승격에 재생(sign-X-execute-Y)하지 못하게 봉인한다. FE5(auth_posture 관측화)가 명시적 선행조건이었다.

★dead-σ 안전(확정결정 open-but-observable): cert 강제는 트리가 attestor(attestor_dids)를 선언했을 때만 —
무-attestor 트리는 무인증 CANONICAL 유지(무회귀). 키 없는 배포를 잠그지 않는다.

  guard_defect    = test_canonical_requires_cert_on_attestor_tree (음성: 게이트 떼면 무서명 CANONICAL 통과 → RED)
  guard_mechanism = test_cert_is_verb_bound_sign_x_execute_y       (양성: submit-cert 를 canonical 에 못 씀)

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag5b_verb_signed_irreversible
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from lakatos import assurance
from lakatos import write_cert as W
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import CertCommandIn, VerdictIn, WriteCertIn

_SK = bytes(range(32))
_DID = W.did_key_encode(W.ed25519_public_key(_SK))
_NOW = datetime.now(timezone.utc).isoformat()


def _cert(verb, *, prev=None, metric_value=None, script_sha=None):
    command = dict(tree="T", tag="n", prev_receipt_sha=prev, metric_value=metric_value,
                   script_sha=script_sha, verb=verb)
    sig = W.ed25519_sign(_SK, W.canonical_cert_blob(command, _NOW))
    return WriteCertIn(signer_did=_DID, signature=sig.hex(), issued_at=_NOW,
                       command=CertCommandIn(**command))


def _canon_svc(*, attestors):
    """CANONICAL 승격 경로 fake — attestor 선언 여부만 달리한다(_canon_svc g6 계승 + attestor_dids)."""
    def kg(query, **p):
        if "cur.verdict AS verdict" in query:
            return [{"verdict": "progressive", "verdict_source": "scripted", "node_state": None,
                     "source_trust": 1.0, "novel_confirmed": True, "qualitative_self_report": False,
                     "author": "", "args": [], "assurance_tier": "anchored",
                     "attestor_dids": attestors, "prev_receipt_sha": None}]
        if "cur.verdict='CANONICAL'" in query:
            return [{"tag": p.get("tag")}]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: [[] for _ in ops], hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None,
                            producer_replay_for_node=lambda n, t: None)


# ── (A) assurance 게이트 + cert verb 필드 ───────────────────────────────────────────
def test_canonical_verb_gate_and_command_has_verb():
    assert assurance.GATE_WRITE_CERT in assurance.gates_for("set_verdict_canonical", "anchored")
    assert "verb" in W.COMMAND_FIELDS, "cert 명령에 verb 판별자 부재(sign-X-execute-Y 미봉인)"


# ── (B) enforcement: attestor 트리는 서명강제 ─────────────────────────────────────────
def test_canonical_requires_cert_on_attestor_tree():
    """guard_defect: attestor 선언 anchored 트리 → 무서명 CANONICAL 승격 403, verb-바인딩 유효 cert 통과.

    set_verdict_canonical 의 GATE_WRITE_CERT 를 떼면 무서명이 통과 → 이 가드 RED(revert-민감)."""
    with pytest.raises(HTTPException) as ei:
        _canon_svc(attestors=[_DID]).set_verdict("T", "n", VerdictIn(verdict="CANONICAL"))
    assert ei.value.status_code == 403, ei.value.status_code
    ok = _canon_svc(attestors=[_DID]).set_verdict(
        "T", "n", VerdictIn(verdict="CANONICAL", write_cert=_cert("set_verdict_canonical")))
    assert ok["ok"] is True


def test_no_attestor_tree_canonical_stays_open():
    """dead-σ 무회귀: attestor 미선언 트리는 무서명 CANONICAL 유지(키 없는 배포 안 잠금)."""
    assert _canon_svc(attestors=None).set_verdict(
        "T", "n", VerdictIn(verdict="CANONICAL"))["ok"] is True


# ── (C) verb 판별자: submit-cert 를 canonical 에 못 쓴다 ─────────────────────────────
def test_cert_is_verb_bound_sign_x_execute_y():
    """guard_mechanism: submit_test_result 로 서명한 cert 를 CANONICAL 승격에 재생 → verb 불일치 거부."""
    submit_cert = _cert("submit_test_result")           # verb=submit 로 서명
    with pytest.raises(HTTPException) as ei:
        _canon_svc(attestors=[_DID]).set_verdict(
            "T", "n", VerdictIn(verdict="CANONICAL", write_cert=submit_cert))
    assert ei.value.status_code == 403, ei.value.status_code
    # 대조: 같은 verb(set_verdict_canonical) 면 통과.
    assert _canon_svc(attestors=[_DID]).set_verdict(
        "T", "n", VerdictIn(verdict="CANONICAL", write_cert=_cert("set_verdict_canonical")))["ok"] is True


guard_defect = "test_canonical_requires_cert_on_attestor_tree"
guard_mechanism = "test_cert_is_verb_bound_sign_x_execute_y"
