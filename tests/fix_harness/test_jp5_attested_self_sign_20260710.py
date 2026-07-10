"""jp5-attested-self-sign — 자기서명(무-attestor fallback)은 attestation 이 아니다 (JP 캠페인 2026-07-08).

결함(q_attestation_authority): 무-attestor 트리에서 자발적 write-cert 가 fallback
allowlist=[signer_did](judgement_service :654 — authorship 검증으로는 정당)로 통과한 뒤,
:785 의 `attested=attested_by_did is not None` 이 그 자기서명을 **attested 등급으로 승격** →
버리는 키페어 self-sign 이 G6(measurement_owned) PASS 를 사는 인센티브 역전(정직한 무서명
운영자는 client_asserted 로 G6 FAIL). 봉합: 권위(attested)는 *트리가 선언한* non-empty
allow-list 대비 서명만 — 자기서명은 신설 grade 'authored'(authorship 증명, OWNED_GRADES 밖
→ G6 fail-closed by-construction). 사다리 4단:

    server_regenerated  >  attested  >  authored  >  client_asserted

★비파괴: attested kwarg 의미 보존(기존 ag5 진리표 무변경 green), authored 는 opt-in kwarg —
무-attestor·무서명(대다수 + JP 캠페인 자기채점 경로)은 그대로 client_asserted.

  guard_defect    = test_self_signed_no_attestor_not_attested (fix 전 RED: mg=='attested' 결함 재현)
  guard_mechanism = test_authored_ladder_and_g6_teeth (사다리 진리표 + G6 이빨 + sha 봉인 분리)

novel_script = 이 파일. # KG 거울: LakatosTree_JudgeProprioception_20260708 / jp5-attested-self-sign
"""
from __future__ import annotations

from datetime import datetime, timezone

from lakatos import write_cert as W
from lakatos.io.replay import ProducerReplayVerdict
from lakatos.verdict.certify import MEASUREMENT_GRADES, OWNED_GRADES, is_measurement_owned
from lakatos.verdicts import receipt_content_sha
from server.contexts.tree.judgement_policy import resolve_measurement
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import CertCommandIn, TestResultIn as Result, WriteCertIn

_SK_A = bytes(range(32))
_DID_A = W.did_key_encode(W.ed25519_public_key(_SK_A))
_NOW = datetime.now(timezone.utc).isoformat()


# ── (A) 순수 사다리 + G6 이빨 ─────────────────────────────────────────────────────
def test_authored_ladder_and_g6_teeth():
    """guard_mechanism: authored 등급 실재 + 사다리 순서 + OWNED_GRADES 배제(G6 fail-closed) + sha 봉인."""
    ok = ProducerReplayVerdict(verified=True, regenerated=0.7, recorded=0.7, reason="externally_verified")
    # authored 생성: 서명은 있으나 트리 선언 allow-list 부재 → authorship 등급.
    assert resolve_measurement(None, 0.5, authored=True) == (0.5, "authored", "not_attempted")
    # server_regenerated(값소유)가 authored 를 이긴다.
    assert resolve_measurement(ok, 0.5, authored=True) == (0.7, "server_regenerated", "verified")
    # attested 는 authored 보다 우선(호출부가 상호배타 구성 — allow-list 존재가 분기).
    assert resolve_measurement(None, 0.5, attested=True) == (0.5, "attested", "not_attempted")
    # 기존 2단 무변경(ag5 진리표 보존).
    assert resolve_measurement(None, 0.5) == (0.5, "client_asserted", "not_attempted")
    # G6 이빨: authored 는 OWNED 가 아니다 — membership fail-closed by-construction.
    assert is_measurement_owned("authored", True) is False
    assert "authored" not in OWNED_GRADES
    assert "authored" in MEASUREMENT_GRADES   # 어휘 정본에는 공개(미지 grade 아님)
    # 신원등급이 receipt_sha 에 봉인 — 등급만 달라도 다른 영수증(위조 표현 불가).
    base = dict(tree="T", tag="n", target_id=None, verdict="progressive", verdict_source="scripted",
                metric_name="m", metric_value=0.5, novel_confirmed=True, lakatos_status="ok",
                judged_at="2026-07-10T00:00:00Z", judge_script_sha="x", prev_receipt_sha=None)
    shas = {g: receipt_content_sha(dict(base, measurement_grade=g))
            for g in ("attested", "authored", "client_asserted")}
    assert len(set(shas.values())) == 3, f"등급이 receipt_sha 를 안 가름: {shas}"


# ── (B) submit 배선: 실 ed25519 자기서명 → authored (attested 아님) ───────────────────
class _SubmitKg:
    def __init__(self, pred):
        self.pred = pred
        self.node = {"current_receipt_sha": None}
        self.captured = []

    def __call__(self, query, **p):
        if "pred_metric AS m" in query:
            return [dict(self.pred, prev_receipt_sha=self.node["current_receipt_sha"])]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{"claimed": params.get("tag")}] for _q, params in ops]


def _svc(tree_props):
    pred = {"m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio", "novel": "",
            "vsrc": None, "nmet": None, "ndir": None, "nthr": None, "psha": None, "closes": None,
            "n_opened": 0, "pred_registered_at": "2026-07-10", "node_state": "PREDICTED",
            "judged_at": None, "existing_metric_value": None, "hard_core": "",
            "require_novel_anchor": False, **tree_props}
    kg = _SubmitKg(pred)
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None), kg


def _cert(metric_value=1.0):
    command = dict(tree="T", tag="seam", prev_receipt_sha=None, metric_value=metric_value, script_sha="",
                   verb="submit_test_result")
    sig = W.ed25519_sign(_SK_A, W.canonical_cert_blob(command, _NOW))
    return WriteCertIn(signer_did=_DID_A, signature=sig.hex(), issued_at=_NOW,
                       command=CertCommandIn(**command))


def test_self_signed_no_attestor_not_attested():
    """guard_defect: 무-attestor 트리 + 유효 자발적 self-sign cert → grade 는 authored(attested 아님).

    fix 전 RED-first: 현행 :785 는 attested_by_did 존재만으로 attested 를 찍는다(결함 재현).
    fix 후 결함 사망; authored 분기 또는 호출부 bool(attestors) 분기를 revert 하면 다시 RED."""
    svc, kg = _svc({"assurance_tier": "anchored", "attestor_dids": None})
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline", write_cert=_cert()))
    _q, params = kg.captured[0][0]
    assert params["mg"] == "authored", \
        f"자기서명이 권위를 샀다 — grade={params.get('mg')} (attested 는 트리 선언 allow-list 전용)"


def test_allowlist_attested_preserved():
    """비파괴 경계: attestor 선언 트리의 allow-list 서명은 여전히 attested(오강등 0) — ag5 시나리오 보존."""
    svc, kg = _svc({"assurance_tier": "anchored", "attestor_dids": [_DID_A]})
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline", write_cert=_cert()))
    _q, params = kg.captured[0][0]
    assert params["mg"] == "attested", f"allow-list 서명이 오강등 — grade={params.get('mg')}"


def test_unsigned_no_cert_unchanged():
    """비파괴 경계: 무-attestor 트리 무서명 제출 → client_asserted 그대로(JP 캠페인 자기채점 경로 동형)."""
    svc, kg = _svc({"assurance_tier": "anchored", "attestor_dids": None})
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline"))
    _q, params = kg.captured[0][0]
    assert params["mg"] == "client_asserted", f"무서명인데 grade={params.get('mg')}"


guard_defect = "test_self_signed_no_attestor_not_attested"
guard_mechanism = "test_authored_ladder_and_g6_teeth"
