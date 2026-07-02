"""git-흡수 G8 landed guards — lakatos fsck 단일 체커(경계=감사) + tolerant-reader 크래시 봉합.

  guard_defect(개선축)     : test_corrupt_node_state_yields_finding_not_500
        — source_trust=None(부패 상태)이 evidence_weight/bayes_factor 를 crash 시키지 않고(fail-safe),
          fsck 가 SOURCE_TRUST_NULL 로 *감사 발견* 표면화(500 → finding). ✅
  guard_mechanism(novel축) : test_same_checker_runs_at_boundary_and_audit_bidirectional
        — 주입된 부패를 각 check-id 별로 fsck 가 검출(ratio=1.0) + 감사와 경계가 *동일 callable·동일 심각도*
          (audit==ingest 양방향, git ingest⊇audit 비대칭보다 강함). ✅

# KG: LakatosTree_GitAbsorption_20260702 / G8_lakatos_fsck
"""
from __future__ import annotations

from lakatos.quant.bayes import bayes_factor
from lakatos.trust import evidence_weight
from server.contexts.audit import fsck as F


# ── guard_defect (개선축) — 착륙 ─────────────────────────────────────────────────────────
def test_corrupt_node_state_yields_finding_not_500():
    """source_trust=None: (1) evidence_weight/bayes_factor 가 crash 대신 fail-safe(무가중), (2) fsck 가 발견으로 표면화."""
    # (1) 크래시-안전: min(1.0, None) TypeError 재현 봉합 — None = 무신뢰(0.0 floor).
    assert evidence_weight(None) == 0.0
    bf = bayes_factor("progressive", 0.5, 0.05, None)   # 전엔 여기서 500(TypeError) 났다
    assert bf == 1.0, bf                                  # 무신뢰 출처 → BF 1(무정보), credence 불변

    # (2) 부패를 감사 발견으로: 500 이 아니라 열거된 check-id.
    findings = F.fsck_node({"verdict": "progressive", "source_trust": None})
    ids = {f.check_id for f in findings}
    assert "SOURCE_TRUST_NULL" in ids, findings


# ── guard_mechanism (novel축) — 착륙 ─────────────────────────────────────────────────────
# 각 check-id 를 발동시키는 최소 부패 레코드(주입 코퍼스).
_CORRUPT = {
    # 'proof'(비-scripted)로 두어 SOURCE_TRUST_NULL 만 단독 발동(순수 WARN 케이스 — prereg 검사 안 걸림).
    "SOURCE_TRUST_NULL": {"verdict": "proof", "source_trust": None},
    "MIXED_JUDGED_AT_TYPE": {"verdict": "proof", "judged_at": {"epoch": 1}},   # dict = 비-ISO
    "VERDICT_WITHOUT_PREREG": {"verdict": "rejected", "assurance_tier_resolved": "legacy"},   # scripted 인데 prereg 없음
    "SCRIPTED_WITHOUT_SOURCE": {"verdict": "progressive", "verdict_source": "conjecture",
                                "pred_registered_at": "2026-07-02",
                                "assurance_tier_resolved": "legacy"},          # scripted 인데 비-영수증 source
    # G6: scripted 판결 write 인데 tier-resolve 스탬프 없음(디스패치 우회/G6 이전 — skiplist 로만 면제)
    "VERDICT_WRITE_WITHOUT_TIER_RESOLVE": {"verdict": "progressive", "verdict_source": "scripted",
                                           "pred_registered_at": "2026-07-02"},
    # R5: head 포인터가 동봉 체인 밖(dangling — 변조/부패). 비동봉 레코드는 발화 없음(enriched 전용).
    "RECEIPT_CHAIN_MISMATCH": {"verdict": "proof", "current_receipt_sha": "d" * 64,
                               "receipts": []},
}


def test_same_checker_runs_at_boundary_and_audit_bidirectional():
    # (1) 주입 검출률 1.0 — 등록된 모든 check-id 가 제 부패를 잡는다(비진공: 코퍼스가 테이블 전수).
    assert set(_CORRUPT) == set(F._SEVERITY), "부패 코퍼스가 심각도 테이블과 불일치(누락 check-id)"
    detected = 0
    for cid, rec in _CORRUPT.items():
        if cid in {f.check_id for f in F.fsck_node(rec)}:
            detected += 1
    assert detected == len(_CORRUPT), f"검출 {detected}/{len(_CORRUPT)} — 일부 부패 미검출"

    # (2) audit==ingest 양방향: 같은 record 는 감사·경계가 *동일 판정*(check_id·severity 바이트동일).
    clean = {"verdict": "proof", "judged_at": "2026-07-02T00:00:00Z"}
    corrupt = _CORRUPT["VERDICT_WITHOUT_PREREG"]         # ERROR 급(경계 기본 임계 통과)
    for rec in (clean, corrupt):
        audit = F.fsck_node(rec)
        boundary_all = F.boundary_fsck(rec, min_severity=F.INFO)   # 임계 최저 = 감사와 동일 집합
        assert audit == boundary_all, (rec, audit, boundary_all)   # 동일 체커·동일 판정

    # (3) 경계 임계는 *거부 후보*만 거른다(판정 자체는 불변) — WARN 부패는 경계 기본(ERROR)에서 통과+기록.
    warn_rec = _CORRUPT["SOURCE_TRUST_NULL"]             # WARN 급
    assert F.fsck_node(warn_rec)                         # 감사는 잡고
    assert F.boundary_fsck(warn_rec, min_severity=F.ERROR) == []  # 경계 기본(ERROR)은 거부 안 함(치명 아님)
    assert F.boundary_fsck(warn_rec, min_severity=F.WARN)        # 임계 낮추면 거부 후보


def test_fsck_is_structural_not_verdict_authority():
    """fsck-clean ≠ epistemically blessed — 판결이 progressive 여도 fsck 는 구조만 본다(판결 축복 아님)."""
    # 구조가 온전하면(prereg+영수증 source) progressive 여도 findings 0 — 하지만 이는 '판결이 옳다'가 아님.
    sound = {"verdict": "progressive", "verdict_source": "scripted", "pred_registered_at": "2026-07-02",
             "judged_at": "2026-07-02T00:00:00Z", "source_trust": 0.9,
             "assurance_tier_resolved": "anchored"}   # G6 이후 sound shape: tier-resolve 스탬프 포함
    assert F.fsck_node(sound) == []   # 구조 clean — 판결 진위는 judge 층 소관(fsck 범위 밖)
