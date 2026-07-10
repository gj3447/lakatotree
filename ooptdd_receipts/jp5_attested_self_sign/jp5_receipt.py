"""OOPTDD emit-adapter — jp5 authored 등급 영수증 (이벤트 리터럴은 이 파일에만).

verify(backend, cid)가 실코드 구동(재구현 금지): 실 ed25519 키로 canonical_cert_blob 서명 →
실 JudgementService.submit_test_result 를 fake KG 로 구동해 captured measurement_grade 를 관측.
  (A) 무-attestor 트리 + 유효 자발적 self-sign → 'authored' (attested 아님)
  (B) 비파괴: attestor 선언 트리 allow-list 서명 → 'attested' 그대로 / 무서명 → 'client_asserted'
  (C) G6 이빨: is_measurement_owned('authored', True)=False + 등급이 receipt_sha 를 가름
  (D) 음성 오라클: 구법 배선(resolve_measurement(attested=True) 직접 호출)은 여전히 attested 를
      찍지만 실 submit seam 은 authored — 차이가 0 이면(둘 다 attested=fix 미착륙 / 둘 다
      authored=진리표 오염) RED

# KG: LakatosTree_JudgeProprioception_20260708 / jp5-attested-self-sign
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

from lakatos import write_cert as W  # noqa: E402
from lakatos.verdict.certify import OWNED_GRADES, is_measurement_owned  # noqa: E402
from lakatos.verdicts import receipt_content_sha  # noqa: E402
from server.contexts.tree.judgement_policy import resolve_measurement  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import CertCommandIn, TestResultIn as Result, WriteCertIn  # noqa: E402

_SK = bytes(range(32))
_DID = W.did_key_encode(W.ed25519_public_key(_SK))
_NOW = datetime.now(timezone.utc).isoformat()


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.jp5.attested_self_sign", "event": name, **attrs}


def _drive(tree_props, with_cert):
    cap = []

    def kg(query, **p):
        if "pred_metric AS m" in query:
            return [{"m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio", "novel": "",
                     "vsrc": None, "nmet": None, "ndir": None, "nthr": None, "psha": None,
                     "closes": None, "n_opened": 0, "pred_registered_at": "2026-07-10",
                     "node_state": "PREDICTED", "judged_at": None, "existing_metric_value": None,
                     "existing_verdict": None, "existing_lstat": None, "prev_receipt_sha": None,
                     "hard_core": "", "require_novel_anchor": False, **tree_props}]
        return []

    svc = JudgementService(kg=kg, kg_tx=lambda ops: (cap.append(ops), [[{"claimed": "n"}] for _ in ops])[1],
                           hist=lambda *a, **k: None, foundation=lambda n: None,
                           reproducible_for_node=lambda n, t: None)
    cert = None
    if with_cert:
        command = dict(tree="T", tag="seam", prev_receipt_sha=None, metric_value=1.0, script_sha="",
                       verb="submit_test_result")
        sig = W.ed25519_sign(_SK, W.canonical_cert_blob(command, _NOW))
        cert = WriteCertIn(signer_did=_DID, signature=sig.hex(), issued_at=_NOW,
                           command=CertCommandIn(**command))
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline", write_cert=cert))
    return cap[0][0][1]


def verify(backend, cid):
    # (A) 무-attestor + 유효 자발적 self-sign → authored
    p = _drive({"assurance_tier": "anchored", "attestor_dids": None}, with_cert=True)
    assert p["mg"] == "authored", f"자기서명이 권위를 삼: {p['mg']}"
    backend.ship([_ev(cid, "jp5_self_sign_downgraded_to_authored", grade=p["mg"])])

    # (B) 비파괴: allow-list 서명 attested 그대로 / 무서명 client_asserted 그대로
    p2 = _drive({"assurance_tier": "anchored", "attestor_dids": [_DID]}, with_cert=True)
    p3 = _drive({"assurance_tier": "anchored", "attestor_dids": None}, with_cert=False)
    assert p2["mg"] == "attested" and p3["mg"] == "client_asserted", (p2["mg"], p3["mg"])
    backend.ship([_ev(cid, "jp5_allowlist_attested_preserved",
                      attested=p2["mg"], unsigned=p3["mg"])])

    # (C) G6 이빨 + sha 봉인 분리
    assert is_measurement_owned("authored", True) is False and "authored" not in OWNED_GRADES
    base = dict(tree="T", tag="n", target_id=None, verdict="progressive", verdict_source="scripted",
                metric_name="m", metric_value=0.5, novel_confirmed=True, lakatos_status="ok",
                judged_at="2026-07-10T00:00:00Z", judge_script_sha="x", prev_receipt_sha=None)
    shas = {g: receipt_content_sha(dict(base, measurement_grade=g))
            for g in ("attested", "authored", "client_asserted")}
    assert len(set(shas.values())) == 3
    backend.ship([_ev(cid, "jp5_authored_not_certifiable", owned=False)])

    # (D) 음성 오라클: 구법(직접 attested=True)은 여전히 attested — seam 의 authored 와 달라야 fix 실재
    legacy_grade = resolve_measurement(None, 1.0, attested=True)[1]
    assert legacy_grade == "attested" and p["mg"] == "authored" and legacy_grade != p["mg"], \
        "구법과 seam 이 같은 등급 — fix 미착륙(둘 다 attested) 또는 진리표 오염(둘 다 authored)"
    backend.ship([_ev(cid, "jp5_negative_oracle", legacy=legacy_grade, seam=p["mg"])])
