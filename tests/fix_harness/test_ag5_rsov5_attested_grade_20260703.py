"""AG5/R-SOV V3 attested 측정등급 — 신원이 measurement_grade 로 올라온다 (측정주권 PROM 2026-07-03).

테제 후속(선행 [[measurement-sovereignty-prom-20260703]] AG3/AG4): AG3 는 measurement_grade 를
server_regenerated(서버 재유도) vs client_asserted(무서명 client float) 2단으로 봉인했다. 그러나
비평 재프레이밍이 지목한 **신원(open-write)이 co-fundamental** — 서명(write-cert)으로 *신원에 묶인*
값은 익명 client float 보다 강하나, AG3 는 둘을 같은 client_asserted 로 뭉갰다. AG5 V3 는 3단
provenance 사다리로 정직화한다:

    server_regenerated (서버가 값 재유도)  >  attested (allow-list 신원 서명)  >  client_asserted (무서명)

★dead-σ 안전: attested 는 트리가 attestor 를 선언하고 유효 write-cert 가 붙을 때만 — 무-attestor 트리
(대다수)는 그대로 client_asserted(무회귀). 값소유(server_regenerated)는 여전히 사다리 최상.

  guard_defect    = test_attested_cert_yields_attested_grade (음성: attested 분기 제거 시 client_asserted → RED)
  guard_mechanism = test_grade_ladder_truth_table            (양성: attested 생성 + server_regenerated>attested 순서)
                    (+ test_grade_ladder_sealed_and_ordered  : 3등급이 다른 receipt_sha — 신원이 sha 에 봉인)

★스코프 정직: IDENT 의 '비가역 verb(canonical/delete) 서명강제'와 cert verb-판별자는 **미착륙** —
FE5 auth_posture 관측화 선행(q-rsov5 open). 본 슬라이스는 attested *grade* 사다리만.

novel_script = 이 파일. # KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag5_attested_grade
"""
from __future__ import annotations

from datetime import datetime, timezone

from lakatos import write_cert as W
from lakatos.io.replay import ProducerReplayVerdict
from lakatos.verdicts import receipt_content_sha
from server.contexts.tree.judgement_policy import resolve_measurement
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import CertCommandIn, TestResultIn as Result, WriteCertIn

_SK_A = bytes(range(32))
_DID_A = W.did_key_encode(W.ed25519_public_key(_SK_A))
_NOW = datetime.now(timezone.utc).isoformat()


# ── (A) 순수 사다리: resolve_measurement(attested=) 진리표 ───────────────────────────
def test_grade_ladder_truth_table():
    ok = ProducerReplayVerdict(verified=True, regenerated=0.7, recorded=0.7, reason="externally_verified")
    bad = ProducerReplayVerdict(verified=False, regenerated=9.9, recorded=0.5, reason="mismatch")
    # 서명만(재유도 아님) → attested, 값은 client 보존.
    assert resolve_measurement(None, 0.5, attested=True) == (0.5, "attested", "not_attempted")
    # 무서명 → client_asserted(AG3 그대로).
    assert resolve_measurement(None, 0.5, attested=False) == (0.5, "client_asserted", "not_attempted")
    # server_regenerated 가 attested 보다 최상 — 서명돼 있어도 재유도값 소유가 이긴다.
    assert resolve_measurement(ok, 0.5, attested=True) == (0.7, "server_regenerated", "verified")
    # 서명값이 replay 불일치 → 신원은 여전히 묶여있으니 attested(값 보존, status=mismatch).
    assert resolve_measurement(bad, 0.5, attested=True) == (0.5, "attested", "mismatch")
    # 무서명 불일치 → client_asserted.
    assert resolve_measurement(bad, 0.5, attested=False) == (0.5, "client_asserted", "mismatch")


def test_grade_ladder_sealed_and_ordered():
    """guard_mechanism: 3등급이 *서로 다른 receipt_sha* 를 든다(봉인 — 신원이 sha 에 인코딩) + 사다리 순서."""
    base = dict(tree="T", tag="n", target_id=None, verdict="progressive", verdict_source="scripted",
                metric_name="m", metric_value=0.5, novel_confirmed=True, lakatos_status="ok",
                judged_at="2026-07-03T00:00:00Z", judge_script_sha="x", prev_receipt_sha=None)
    shas = {g: receipt_content_sha(dict(base, measurement_grade=g))
            for g in ("server_regenerated", "attested", "client_asserted")}
    assert len(set(shas.values())) == 3, f"등급이 receipt_sha 를 안 가름(신원 미봉인): {shas}"
    # 사다리: 서명은 client 보다 강한 신원바인딩(같은 값이라도 다른 등급 → 다른 sha).
    assert shas["attested"] != shas["client_asserted"]


# ── (B) submit 배선: 실 ed25519 write-cert → attested grade 봉인 ─────────────────────
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
            "n_opened": 0, "pred_registered_at": "2026-07-03", "node_state": "PREDICTED",
            "judged_at": None, "existing_metric_value": None, "hard_core": "",
            "require_novel_anchor": False, **tree_props}
    kg = _SubmitKg(pred)
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None), kg


def _cert(metric_value=1.0):
    command = dict(tree="T", tag="seam", prev_receipt_sha=None, metric_value=metric_value, script_sha="",
                   verb="submit_test_result")   # AG5-IDENT: submit cert 는 verb 바인딩 필수
    sig = W.ed25519_sign(_SK_A, W.canonical_cert_blob(command, _NOW))
    return WriteCertIn(signer_did=_DID_A, signature=sig.hex(), issued_at=_NOW,
                       command=CertCommandIn(**command))


def test_attested_cert_yields_attested_grade():
    """guard_defect: attestor anchored 트리 + 유효 서명 → measurement_grade='attested'(client_asserted 아님).

    attested 분기를 resolve_measurement 에서 떼면 grade='client_asserted' → 이 가드 RED(revert-민감)."""
    svc, kg = _svc({"assurance_tier": "anchored", "attestor_dids": [_DID_A]})
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline", write_cert=_cert()))
    _q, params = kg.captured[0][0]
    assert params["mg"] == "attested", f"신원 서명값이 attested 로 안 봉인됨 — grade={params.get('mg')}"


def test_unsigned_stays_client_asserted_no_regression():
    """무-attestor 트리(무서명)는 그대로 client_asserted — 무회귀(대다수 트리)."""
    svc, kg = _svc({"assurance_tier": "anchored", "attestor_dids": None})
    svc.submit_test_result("T", "seam", Result(metric_value=1.0, script="inline"))
    _q, params = kg.captured[0][0]
    assert params["mg"] == "client_asserted", f"무서명인데 grade={params.get('mg')}"


guard_defect = "test_attested_cert_yields_attested_grade"
guard_mechanism = "test_grade_ladder_truth_table"
