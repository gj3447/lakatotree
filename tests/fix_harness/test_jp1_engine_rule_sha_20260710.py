"""jp1-engine-rule-sha — 판관 정체성을 영수증에 봉인 (JP 캠페인 LakatosTree_JudgeProprioception_20260708).

결함(q_judge_identity): RECEIPT_FIELDS 가 판관(엔진 규칙) 정체성을 안 봉인 → '오늘 엔진이면 이걸
여전히 progressive 라 부를까?'가 원장 수준에서 답 불가(통시적 자기정체성 부재 = unreadable green).
봉합: engine_rule_sha(= 규칙표면 lakatos/verdicts.py+verdict/*.py 의 내용주소) 를 v2 봉인 필드로 —
v1 13필드는 RECEIPT_FIELDS_V1 동결(legacy carve-out, 기존 코퍼스 sha-space 바이트 무변경), 버전
판별자는 봉인 *안*(non-null presence — strip/주입 어느 방향 위조도 recompute 가 문다).

  guard_defect    = test_receipt_fields_bind_engine_identity + test_v2_domain_separation_and_strip_forgery
                    (익명 판관 결함 사망: 필드 실재 + 정체성만 다른 두 봉인이 다른 sha)
  guard_mechanism = test_v1_sha_space_byte_stable_golden (carve-out 실증 — 변경 *전* 실측 캡처한 64-hex
                    골든 5종과 바이트 동일) + test_production_submit_seals_identity (프로덕션 mint 가
                    ENGINE_RULE_SHA 실전달 — None-default 뒤에 숨은 v1-조용히-mint 드리프트 보험)
                    + test_stale_canonical_sweep_demotes_and_respects_locks (novel 오라클 기제:
                    stale_canonical_auto_demoted ≥1 실측)

novel_script = judges/jp1_stale_canonical_demo.py. # KG 거울: jp1-engine-rule-sha
"""
from __future__ import annotations

from lakatos.engine_identity import (ENGINE_RULE_SHA, compute_engine_rule_sha,
                                     effective_floor, load_rule_floor, rule_surface_manifest)
from lakatos.verdicts import RECEIPT_FIELDS, RECEIPT_FIELDS_V1, canonical_receipt_blob, receipt_content_sha
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result

_BASE = {"tree": "T", "tag": "n", "target_id": "n", "verdict": "progressive",
         "verdict_source": "scripted", "metric_name": "m", "metric_value": 1.0,
         "novel_confirmed": True, "lakatos_status": "progressive",
         "judged_at": "2026-07-08T00:00:00+00:00", "judge_script_sha": "0" * 64,
         "prev_receipt_sha": None, "measurement_grade": "client_asserted"}

# 변경 *전*(df913cb) 실측 캡처 — legacy carve-out 의 회귀 앵커. 이 값이 흔들리면 기존 KG 코퍼스
# 전체의 재유도/fold/verify 가 무너진다(재채점·마이그레이션 0 이 carve-out 의 약속).
_V1_GOLDENS = {
    "base": "0fc94e9ab94d06bdc5ea857b2d432eb01e45ccfa79ab3e445a89d7f18fcfd2bf",
    "int_metric": "6fffb129c1918340c26eb660a4b357b828840c9b8df4c0a965ad854b19842ecd",
    "none_grade": "2d77fc6ecc5392d3daa0aa2023cbe284c8feaae97b24fb6609336092ba5dc7e5",
    "prev_linked": "727080ac9297d8c20c53233248e35c38b113b30290d8af88f86a49e47cefdee5",
    "unicode": "7af0438cac3762fbd20bbef831c56f83aa52ac392f353abd721c85e3c7f61a7f",
}
_V1_CORPUS = {
    "base": _BASE,
    "int_metric": {**_BASE, "metric_value": 3},
    "none_grade": {**_BASE, "measurement_grade": None},
    "prev_linked": {**_BASE, "prev_receipt_sha": "a" * 64, "verdict": "partial"},
    "unicode": {**_BASE, "metric_name": "재현율_δ", "judged_at": 1720483200},
}


def test_receipt_fields_bind_engine_identity():
    """guard_defect(익명 판관 사망): engine_rule_sha 가 봉인 필드셋에 실재 + v1 13필드 동결."""
    assert "engine_rule_sha" in RECEIPT_FIELDS
    assert RECEIPT_FIELDS == RECEIPT_FIELDS_V1 + ("engine_rule_sha",)
    assert len(RECEIPT_FIELDS_V1) == 13 and "engine_rule_sha" not in RECEIPT_FIELDS_V1


def test_v1_sha_space_byte_stable_golden():
    """guard_mechanism(carve-out): engine_rule_sha 부재/None 입력은 변경 전 캡처 골든과 바이트 동일."""
    for name, fields in _V1_CORPUS.items():
        assert receipt_content_sha(fields) == _V1_GOLDENS[name], f"v1 sha-space 이동: {name}"
        # 명시 None 도 v1 경로(presence-dispatch: None = 부재)
        assert receipt_content_sha(dict(fields, engine_rule_sha=None)) == _V1_GOLDENS[name]
    assert canonical_receipt_blob(_BASE).startswith(b"verdict-receipt\x00v1\n")


def test_v2_domain_separation_and_strip_forgery():
    """v2 는 별도 sha-space(헤더+필드) — strip(v2→v1 재유도)·주입(v1→v2 재유도) 어느 방향도 stored 와 불일치."""
    v2f = dict(_BASE, engine_rule_sha=ENGINE_RULE_SHA)
    v2sha = receipt_content_sha(v2f)
    assert v2sha != _V1_GOLDENS["base"]                       # 도메인 분리
    assert canonical_receipt_blob(v2f).startswith(b"verdict-receipt\x00v2\n")
    # strip-forgery: 저장된 v2 에서 정체성을 떼면 v1-추론 재유도 ≠ stored v2 sha
    assert receipt_content_sha(dict(v2f, engine_rule_sha=None)) != v2sha
    # 주입-forgery: v1 stored 에 가짜 정체성 주입 → v2-추론 재유도 ≠ stored v1 sha
    assert receipt_content_sha(dict(_BASE, engine_rule_sha="f" * 64)) != _V1_GOLDENS["base"]
    # 정체성 값만 달라도 다른 봉인(판관이 sha 를 가른다 — ag3 grade 봉인 동형)
    assert receipt_content_sha(dict(_BASE, engine_rule_sha="a" * 64)) \
        != receipt_content_sha(dict(_BASE, engine_rule_sha="b" * 64))


def test_engine_rule_sha_is_content_derived():
    """정체성이 진짜 content-addressing(상수 문자열 게임 불가): manifest 결정론 + 1엔트리 변조 → 발산."""
    m1 = rule_surface_manifest()
    assert m1 and all(len(v) == 64 for v in m1.values())
    assert compute_engine_rule_sha(m1) == ENGINE_RULE_SHA == compute_engine_rule_sha(rule_surface_manifest())
    k = sorted(m1)[0]
    mutated = dict(m1, **{k: "0" * 64})
    assert compute_engine_rule_sha(mutated) != ENGINE_RULE_SHA
    # 규칙 표면에 판결 커널이 실재(디렉토리 규칙 — 신규 규칙파일 자동 포함의 최소 증인)
    assert "verdicts.py" in m1 and any(p.startswith("verdict/") for p in m1)


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


def _svc(kg):
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)


def test_production_submit_seals_identity():
    """드리프트 보험: 프로덕션 submit mint 가 engine_rule_sha=ENGINE_RULE_SHA 를 *실전달*(v2).

    build_receipt_fields 의 None-default(봉인 스크립트 하위호환) 뒤에서 프로덕션 사이트가 조용히
    v1 로 퇴행하면 여기가 RED — required-kwarg 대신 이 가드가 fail-loud 를 담당한다."""
    pred = {"m": "seam", "d": "lower", "b": 10.0, "nb": 0.0, "scale": "ratio", "novel": "",
            "vsrc": None, "nmet": None, "ndir": None, "nthr": None, "psha": None, "closes": None,
            "n_opened": 0, "pred_registered_at": "2026-07-10", "node_state": "PREDICTED",
            "judged_at": None, "existing_metric_value": None, "hard_core": "",
            "require_novel_anchor": False, "assurance_tier": "anchored", "attestor_dids": None}
    kg = _SubmitKg(pred)
    _svc(kg).submit_test_result("T", "seam", Result(metric_value=1.0, script="inline"))
    _q, params = kg.captured[0][0]
    assert params.get("engine_rule_sha") == ENGINE_RULE_SHA, "프로덕션 mint 가 판관 정체성을 안 봉인(v1 퇴행)"
    # rsha 가 실제로 v2 봉인값(파라미터로 실려간 필드들의 presence-dispatch 재유도와 일치)
    refields = dict(tree="T", tag="seam", target_id=params.get("target_id"), verdict=params["v"],
                    verdict_source="scripted", metric_name=params["mn"], metric_value=params["mv"],
                    novel_confirmed=params["novel"], lakatos_status=params["lstat"],
                    judged_at=params["ts"], judge_script_sha=params["sha"],
                    prev_receipt_sha=params["prev_rsha"], measurement_grade=params["mg"],
                    engine_rule_sha=params["engine_rule_sha"])
    assert receipt_content_sha(refields) == params["rsha"]


class _SweepKg:
    """demote_stale_canonical 전용 상태형 fake — CANONICAL 3그루: v1 legacy(ers=None),
    타 판관(ers=옛 sha), 잠금(vur=False). CAS write 를 충실 적용(revert-민감)."""

    def __init__(self):
        self.rows = [
            {"tag": "legacy_v1", "prev_rsha": "p1", "ers": None, "vur": True},
            {"tag": "old_judge", "prev_rsha": "p2", "ers": "e" * 64, "vur": True},
            {"tag": "locked", "prev_rsha": "p3", "ers": None, "vur": False},
        ]
        self.demoted, self.receipts = [], []

    def __call__(self, query, **p):
        if "verdict:'CANONICAL'" in query and "RETURN e.tag AS tag" in query:
            return [dict(r) for r in self.rows]
        if "SET e.verdict='former_canonical'" in query:
            row = next(r for r in self.rows if r["tag"] == p["tag"])
            if (row.get("prev_rsha") or "") != (p.get("prev") or ""):
                return []                       # CAS 불일치
            self.demoted.append(p["tag"])
            self.receipts.append({"receipt_sha": p["rsha"], "engine_rule_sha": p["engine_rule_sha"]})
            return [{"tag": p["tag"]}]
        return []


def test_stale_canonical_sweep_demotes_and_respects_locks(tmp_path, monkeypatch):
    """novel 오라클 기제: floor 밖(v1 익명 포함) CANONICAL 강등 ≥1 + dry_run 열거 + 인간잠금 존중."""
    hist_events = []
    kg = _SweepKg()
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [], hist=lambda *a, **k: hist_events.append(a),
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    # floor 파일 부재 = 선언분 0 → 유효 floor = {현 ENGINE_RULE_SHA} 단독
    monkeypatch.setenv("LAKATOS_ENGINE_RULE_FLOOR", str(tmp_path / "absent.json"))
    assert load_rule_floor() == set() and effective_floor() == {ENGINE_RULE_SHA}
    # dry_run(기본): 열거만, 쓰기 0
    dry = svc.demote_stale_canonical("T")
    assert dry["dry_run"] is True and kg.demoted == []
    assert {c["tag"] for c in dry["candidates"]} == {"legacy_v1", "old_judge"}
    assert dry["skipped_locked"] == ["locked"]
    # 실행: 후보 2 강등(novel 오라클 stale_canonical_auto_demoted=2 ≥ 1), 잠금 무접촉,
    #   mint 영수증은 현 판관 정체성으로 서명된 v2.
    run = svc.demote_stale_canonical("T", dry_run=False)
    assert run["demoted"] == ["legacy_v1", "old_judge"] and kg.demoted == ["legacy_v1", "old_judge"]
    assert "locked" not in kg.demoted
    assert all(r["engine_rule_sha"] == ENGINE_RULE_SHA for r in kg.receipts)
    assert [e[1] for e in hist_events] == ["stale_engine_demotion"] * 2
    # 선언 floor 에 옛 판관을 등재하면 그 판관의 CANONICAL 은 재심 대상에서 빠진다(정직 floor 의미론)
    (tmp_path / "floor.json").write_text('{"entries": [{"sha": "' + "e" * 64 + '"}]}', encoding="utf-8")
    monkeypatch.setenv("LAKATOS_ENGINE_RULE_FLOOR", str(tmp_path / "floor.json"))
    kg2 = _SweepKg()
    svc2 = JudgementService(kg=kg2, kg_tx=lambda ops: [], hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    dry2 = svc2.demote_stale_canonical("T")
    assert {c["tag"] for c in dry2["candidates"]} == {"legacy_v1"}


guard_defect = "test_receipt_fields_bind_engine_identity"
guard_mechanism = "test_v1_sha_space_byte_stable_golden"
