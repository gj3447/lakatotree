"""jp3-fsck-recompute — read-time recompute-and-reject (JP 캠페인 LakatosTree_JudgeProprioception_20260708).

결함(q_tamper_evidence): 어떤 읽기경로도 receipt_sha==recompute(content) 를 검증 안 함 — 원장우회
위조행·in-place 변조가 fold/verify/fsck 에 불가시(하네스 demo_tamper_invisible 이 running proof).
봉합: fsck 순수 체커 2종 — 어느 알려진 인코딩과도 불일치=RECEIPT_SHA_CONTENT_MISMATCH(ERROR, 변조),
미선언 구-인코딩(pre-ag3) 일치=RECEIPT_ENCODING_STALE(WARN, 필드드리프트). **fold 는 불변**(AG1
pointer-walk ADR 경계 — 검증 좌석 신설이지 fold 개조가 아님). 프로드 도달=ops_fsck?include_receipts=1
(opt-in, 기본 경로 바이트동일; skiplist 는 비동봉 base-sha 로 선-단락 — census FREEZE 존중).

  guard_defect    = test_inplace_tamper_surfaces_as_error_while_fold_stays_blind
  guard_mechanism = 봉인필드 단일변조 전수 검출 + 정직체인 0 발견 + pre-ag3 STALE 구별 +
                    음성오라클(match_receipt_encoding 절제 시 변조 slip = recompute 가 load-bearing)

novel_script = 이 파일 (tampered_receipt_detected 실측). # KG 거울: jp3-fsck-recompute
"""
from __future__ import annotations

import pytest

import lakatos.verdicts as V
from lakatos.engine_identity import ENGINE_RULE_SHA
from server.contexts.audit import fsck as F

_H = {"tree": "T", "tag": "n", "target_id": None, "verdict": "progressive",
      "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
      "novel_confirmed": True, "lakatos_status": "p", "judged_at": "2026-07-10T00:00:00Z",
      "judge_script_sha": "0" * 64, "prev_receipt_sha": None, "measurement_grade": "client_asserted"}


def _chain(base=None):
    """실 mint 2-영수증 체인(genesis→head) — 하네스 demo_tamper_invisible 동형."""
    f = dict(base or _H)
    genesis = {**f, "receipt_sha": V.receipt_content_sha(f)}
    head_f = {**f, "tag": "head", "prev_receipt_sha": genesis["receipt_sha"]}
    head = {**head_f, "receipt_sha": V.receipt_content_sha(head_f)}
    return genesis, head


def _rec(receipts, head_sha):
    return {"verdict": "proof", "current_receipt_sha": head_sha, "receipts": receipts}


def test_inplace_tamper_surfaces_as_error_while_fold_stays_blind():
    """guard_defect: head verdict in-place 변조(sha 유지) → fsck ERROR *그리고* fold 는 여전히
    예외 없이 변조값 반환(검출 좌석=fsck, AG1 fold 경계 무변경을 같은 테스트가 핀)."""
    genesis, head = _chain()
    head["verdict"] = "CANONICAL"                     # 변조: sha 는 그대로
    ids = {f.check_id for f in F.fsck_node(_rec([genesis, head], head["receipt_sha"]))}
    assert "RECEIPT_SHA_CONTENT_MISMATCH" in ids
    # fold 는 불변 — pointer-walk 라 변조에 blind(그게 AG1 경계; 검출은 fsck 몫)
    folded = V.fold_receipt_chain([genesis, head], head["receipt_sha"])
    assert folded["verdict"] == "CANONICAL" and folded["from_receipt"]


def test_honest_chain_clean():
    """반-진공: 정직 mint 체인(v1)은 발견 0 — recompute 가 전 코퍼스 오탐 폭발을 안 낸다."""
    genesis, head = _chain()
    assert F.fsck_node(_rec([genesis, head], head["receipt_sha"])) == []


def test_honest_v2_chain_clean():
    """jp1 정합: v2(engine_rule_sha 봉인) 정직 mint 도 'current' 가족 — 발견 0."""
    genesis, head = _chain(dict(_H, engine_rule_sha=ENGINE_RULE_SHA))
    assert F.fsck_node(_rec([genesis, head], head["receipt_sha"])) == []


@pytest.mark.parametrize("field,value", [
    ("verdict", "CANONICAL"), ("metric_value", 9.9), ("measurement_grade", "server_regenerated"),
    ("judged_at", "2001-01-01T00:00:00Z"), ("prev_receipt_sha", "e" * 64),
    ("engine_rule_sha", "f" * 64),   # jp1 v2 필드 변조/주입도 문다
])
def test_any_sealed_field_mutation_detected(field, value):
    """recompute 실재: 봉인필드 단일변조 전수 검출('sha 형식 검사' 아님)."""
    genesis, head = _chain()
    head[field] = value
    ids = {f.check_id for f in F.fsck_node(_rec([genesis, head], head["receipt_sha"]))}
    assert "RECEIPT_SHA_CONTENT_MISMATCH" in ids, f"{field} 변조 미검출"


def test_prediction_receipt_domain_dispatch():
    """prediction 영수증(receipt_kind 봉인)은 자기 도메인 단일 대조 — 정직 통과 / 변조 검출."""
    pf = {"receipt_kind": "prediction", "tree": "T", "tag": "n", "metric_name": "m",
          "direction": "higher", "baseline_value": 0.0, "noise_band": 0.0, "scale_type": "ratio",
          "novel_prediction": "", "novel_metric": None, "novel_direction": None,
          "novel_threshold": None, "judge_script_sha": None, "closes_question": "q",
          "credence": 0.7, "baseline_lineage": "no_prior",
          "registered_at": "2026-07-10T00:00:00Z", "prev_receipt_sha": None}
    honest = {**pf, "receipt_sha": V.prediction_content_sha(pf)}
    assert F.fsck_node(_rec([honest], honest["receipt_sha"])) == []
    tampered = dict(honest, credence=0.99)            # spec 사후 수정(back-fit) — sha 가 문다
    ids = {f.check_id for f in F.fsck_node(_rec([tampered], tampered["receipt_sha"]))}
    assert "RECEIPT_SHA_CONTENT_MISMATCH" in ids


def test_pre_ag3_encoding_is_stale_warn_not_mismatch_error():
    """계보 정직성: pre-ag3(12필드, 미선언 드리프트) 정직 mint = WARN 단독 — ERROR 오탐 0(64 poison
    census 대리·FREEZE 무오탐) + 이중 발화 금지(신호 순도)."""
    sf = {k: _H[k] for k in V.RECEIPT_FIELDS_PRE_AG3}
    stale = {**sf, "receipt_sha": V.receipt_content_sha(sf, fieldset=V.RECEIPT_FIELDS_PRE_AG3)}
    findings = F.fsck_node(_rec([stale], stale["receipt_sha"]))
    ids = {f.check_id for f in findings}
    assert ids == {"RECEIPT_ENCODING_STALE"}, findings
    assert all(f.severity == F.WARN for f in findings)


def test_unenriched_record_no_fire():
    """비동봉 레코드 판단 보류(R5 동형) — record-level 계약 비파괴."""
    assert F.fsck_node({"verdict": "proof", "current_receipt_sha": "a" * 64}) == []


def test_negative_oracle_recompute_is_load_bearing(monkeypatch):
    """음성오라클: match_receipt_encoding 을 상수 'current' 로 절제하면 같은 변조가 clean 통과(slip)
    — 검출이 recompute 호출에 인과적으로 매달림(문자열 프록시/진공 green 게임 불가)."""
    genesis, head = _chain()
    head["verdict"] = "CANONICAL"
    rec = _rec([genesis, head], head["receipt_sha"])
    assert any(f.check_id == "RECEIPT_SHA_CONTENT_MISMATCH" for f in F.fsck_node(rec))
    monkeypatch.setattr(F, "match_receipt_encoding", lambda r, s: "current")   # 소비 사이트 절제
    assert F.fsck_node(rec) == [], "절제된 recompute 에도 검출 — 검사가 다른 곳에 위장돼 있음"


def test_ops_fsck_include_receipts_wiring(monkeypatch):
    """프로드 도달: ?include_receipts=1 이 배치 동봉으로 finding 표면화, 기본 off 는 현행 산출 동일,
    skiplist 는 비동봉 base-sha 로 선-단락(면제 의미 보존 — total 은 계속 집계)."""
    from server import app

    genesis, head = _chain()
    head["verdict"] = "CANONICAL"                     # in-place 변조

    def _kg(q, **p):
        if "HAS_RECEIPT" in q:                        # 트리당 배치 collect
            return [{"tag": "n1", "receipts": [genesis, head]}]
        return [{"name": "T1"}]                       # 트리 목록

    base_row = {"tag": "n1", "verdict": "proof", "current_receipt_sha": head["receipt_sha"]}
    monkeypatch.setattr(app, "kg", _kg)
    monkeypatch.setattr(app, "tree_data", lambda n: {"nodes": [dict(base_row)]})
    # 기본 off: recompute 체커 미발화(비동봉) — 현행 산출 동일
    off = app.ops_fsck()
    assert off["total_records"] == 1 and off["counts"].get("RECEIPT_SHA_CONTENT_MISMATCH") is None
    # opt-in: 변조 표면화
    on = app.ops_fsck(include_receipts=True)
    assert on["counts"].get("RECEIPT_SHA_CONTENT_MISMATCH") == 1
    # skiplist(비동봉 base-sha 열거)면 enriched 검사도 선-단락, total 은 여전히 집계
    import json as _json
    sha = F.record_content_sha(base_row)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        _json.dump({"entries": [{"sha": sha}]}, fh)
        skpath = fh.name
    monkeypatch.setenv("LAKATOS_FSCK_SKIPLIST", skpath)
    skipped = app.ops_fsck(include_receipts=True)
    assert skipped["total_records"] == 1 and skipped["findings_count"] == 0


guard_defect = "test_inplace_tamper_surfaces_as_error_while_fold_stays_blind"
guard_mechanism = "test_any_sealed_field_mutation_detected"
