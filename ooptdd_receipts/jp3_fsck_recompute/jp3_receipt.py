"""OOPTDD emit-adapter — jp3 fsck recompute-and-reject 영수증 (이벤트 리터럴은 이 파일에만).

verify(backend, cid)가 실코드 구동(재구현 금지): lakatos.verdicts.receipt_content_sha 로 실 mint 한
체인 + server.contexts.audit.fsck.fsck_node 실호출.
  (A) honest-clean: 정직 체인(v1·v2) 발견 0
  (B) tamper: head in-place 변조(sha 유지) → RECEIPT_SHA_CONTENT_MISMATCH
  (C) lineage: pre-ag3 정직 mint → STALE(WARN)이고 MISMATCH 아님
  (D) 음성 오라클: match_receipt_encoding 절제 → 변조 slip 재현(검사 load-bearing) 후 원복

# KG: LakatosTree_JudgeProprioception_20260708 / jp3-fsck-recompute
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

import lakatos.verdicts as V  # noqa: E402
from lakatos.engine_identity import ENGINE_RULE_SHA  # noqa: E402
from server.contexts.audit import fsck as F  # noqa: E402

_H = {"tree": "T", "tag": "n", "target_id": None, "verdict": "progressive",
      "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
      "novel_confirmed": True, "lakatos_status": "p", "judged_at": "2026-07-10T00:00:00Z",
      "judge_script_sha": "0" * 64, "prev_receipt_sha": None, "measurement_grade": "client_asserted"}


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.jp3.fsck_recompute", "event": name, **attrs}


def _chain(base):
    f = dict(base)
    genesis = {**f, "receipt_sha": V.receipt_content_sha(f)}
    head_f = {**f, "tag": "head", "prev_receipt_sha": genesis["receipt_sha"]}
    return genesis, {**head_f, "receipt_sha": V.receipt_content_sha(head_f)}


def _rec(receipts, head_sha):
    return {"verdict": "proof", "current_receipt_sha": head_sha, "receipts": receipts}


def verify(backend, cid):
    # (A) honest-clean — v1 + v2 정직 체인 발견 0
    g1, h1 = _chain(_H)
    g2, h2 = _chain(dict(_H, engine_rule_sha=ENGINE_RULE_SHA))
    assert F.fsck_node(_rec([g1, h1], h1["receipt_sha"])) == []
    assert F.fsck_node(_rec([g2, h2], h2["receipt_sha"])) == []
    backend.ship([_ev(cid, "jp3_honest_clean", v1=True, v2=True)])

    # (B) tamper — in-place 변조가 ERROR 로 표면화 (novel 오라클 기제)
    h1["verdict"] = "CANONICAL"
    tampered_rec = _rec([g1, h1], h1["receipt_sha"])
    findings = F.fsck_node(tampered_rec)
    assert any(f.check_id == "RECEIPT_SHA_CONTENT_MISMATCH" and f.severity == F.ERROR
               for f in findings), findings
    backend.ship([_ev(cid, "jp3_tamper_detected", detected=1)])

    # (C) lineage-honesty — pre-ag3 정직 mint 는 STALE 단독(WARN), MISMATCH 아님
    sf = {k: _H[k] for k in V.RECEIPT_FIELDS_PRE_AG3}
    stale = {**sf, "receipt_sha": V.receipt_content_sha(sf, fieldset=V.RECEIPT_FIELDS_PRE_AG3)}
    sfindings = F.fsck_node(_rec([stale], stale["receipt_sha"]))
    assert {f.check_id for f in sfindings} == {"RECEIPT_ENCODING_STALE"}, sfindings
    backend.ship([_ev(cid, "jp3_stale_distinguished", label="pre-ag3")])

    # (D) 음성 오라클 — recompute 절제 시 변조 slip(검사 load-bearing), try/finally 원복
    orig = F.match_receipt_encoding
    try:
        F.match_receipt_encoding = lambda r, s: "current"
        slipped = F.fsck_node(tampered_rec) == []
    finally:
        F.match_receipt_encoding = orig
    assert slipped, "절제된 recompute 에도 검출 — 검사가 다른 곳에 위장(음성 오라클 실패)"
    assert any(f.check_id == "RECEIPT_SHA_CONTENT_MISMATCH" for f in F.fsck_node(tampered_rec)), \
        "원복 후 검출 미복원"
    backend.ship([_ev(cid, "jp3_negative_oracle", checks_load_bearing=True)])
