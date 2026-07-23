"""lakatos fsck — 노드/영수증 레코드의 구조 무결성 체커(git-흡수 G8).

git fsck(fsck.c:1254-1280)의 핵심: *단일 체커*(fsck_object)를 오프라인 감사·pack ingest·loose ingest 에 동일
컴파일해, 경계에서 거부하지 나중에 발견하지 않는다. 이식: 노드 record 에 대한 순수 체커(fsck_node)를 감사
스윕(fsck_records)과 쓰기 경계(boundary_fsck)가 *동일 callable·동일 심각도 테이블*로 공유 → audit==ingest.

★git 대비 강화(deep-dive OVERSTATED 교정): git 은 ingest⊇audit(strict-bit 비대칭). 우리는 심각도를 한
테이블(_SEVERITY)에 직렬화해 audit==ingest *양방향*(같은 record 는 어디서 검사하든 같은 findings).

★fsck 는 *구조*만 본다 — 판결/정체성은 범위 밖. fsck-clean ≠ 'epistemically blessed'(판결은 judge 층).

라이브 동기: source_trust=None 이 tree_metrics 를 500 냈다(333v2·ice-orca-dragon). tolerant reader 의 무음
불완전을 열거된 감사 발견(SOURCE_TRUST_NULL)으로 전환한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from lakatos.verdicts import (FORCEFUL_SOURCES,
                              SCRIPTED_DIALECTICAL_VERDICTS as _SCRIPTED_DIALECTICAL_VERDICTS,
                              STANDING_VERDICTS as _STANDING_VERDICTS,
                              comment_drift, is_scripted_verdict,
                              match_receipt_encoding, receipt_content_sha)

# 심각도 서열(단일 정본 — audit·boundary 가 공유). FATAL > ERROR > WARN > INFO.
FATAL, ERROR, WARN, INFO = "FATAL", "ERROR", "WARN", "INFO"
_ORDER = {INFO: 0, WARN: 1, ERROR: 2, FATAL: 3}

# check-id → 심각도. 새 check 는 여기서만(H9 스타일 SSOT). 열거되지 않은 부패는 존재하지 않는 것처럼 다루지 않는다.
_SEVERITY = {
    "SOURCE_TRUST_NULL": WARN,          # present-but-None trust → tree_metrics 500 유발(크래시-안전은 evidence_weight 가, 감사는 여기)
    "MIXED_JUDGED_AT_TYPE": WARN,       # judged_at 이 dict/epoch/ISO 혼재 → 읽기 표류
    "VERDICT_WITHOUT_PREREG": ERROR,    # scripted 판결인데 사전등록(pred_registered_at) 없음 = 영수증 사슬 끊김
    "SCRIPTED_WITHOUT_SOURCE": ERROR,   # scripted 어휘인데 verdict_source 가 영수증(FORCEFUL)이 아님 = force_of 오판
    "VERDICT_WRITE_WITHOUT_TIER_RESOLVE": ERROR,   # G6: 판결 write 에 tier resolve 흔적 없음 = 디스패치 우회/G6 이전
    "RECEIPT_CHAIN_MISMATCH": ERROR,    # R5: current_receipt_sha 가 동봉 체인 밖(dangling — 변조/부패). verify 라우트와 공용 어휘
    "FORCEFUL_SOURCE_WITHOUT_RECEIPT": ERROR,   # R6: FORCEFUL 판결인데 원장 포인터 없음(G1 이전/우회 write — skiplist 로만 면제)
    "MEASUREMENT_REFUTED_BUT_STANDING": WARN,   # AG6: replay 가 측정을 반증(mismatch)했는데 standing verdict — 값무결 관측(비차단)
    "RECEIPT_SHA_CONTENT_MISMATCH": ERROR,      # jp3: stored receipt_sha ≠ recompute(content) — 어느 인코딩과도 불일치(in-place 변조/원장우회 위조)
    "RECEIPT_ENCODING_STALE": WARN,             # jp3: 미선언 구-인코딩(pre-ag3) 정직 mint — 필드드리프트 가시화(변조 아님, 비차단)
    "COMMENT_DRIFT_AFTER_VERDICT": WARN,        # S4: 판정 이후 comment 개서(c6 사후 승리 에세이 장르) — 서사는 자유, 침묵은 불가(비차단)
}

# 어휘 집합은 verdicts.py 정본에서 import (engine-unify 2026-07-23):
#   _STANDING_VERDICTS(AG6 값무결 positive-claim) / _SCRIPTED_DIALECTICAL_VERDICTS(변증법 그림자).


def _is_scripted_judgement(rec: dict) -> bool:
    """Whether a row must carry the preregistration/source/tier structure of a scripted write."""
    verdict = rec.get("verdict", "")
    return (is_scripted_verdict(verdict)
            or verdict in _SCRIPTED_DIALECTICAL_VERDICTS
            or rec.get("verdict_source") == "scripted")


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: str
    detail: str


def _check_source_trust(rec: dict) -> Finding | None:
    if "source_trust" in rec and rec["source_trust"] is None:
        return Finding("SOURCE_TRUST_NULL", _SEVERITY["SOURCE_TRUST_NULL"],
                       "source_trust present-but-None (evidence_weight fail-safe; 읽기 표면 500 위험)")
    return None


def _check_judged_at_type(rec: dict) -> Finding | None:
    ja = rec.get("judged_at")
    if ja is not None and not isinstance(ja, str):
        return Finding("MIXED_JUDGED_AT_TYPE", _SEVERITY["MIXED_JUDGED_AT_TYPE"],
                       f"judged_at 타입 {type(ja).__name__} (정본=ISO str)")
    return None


def _check_prereg(rec: dict) -> Finding | None:
    if _is_scripted_judgement(rec) and not rec.get("pred_registered_at"):
        return Finding("VERDICT_WITHOUT_PREREG", _SEVERITY["VERDICT_WITHOUT_PREREG"],
                       f"scripted verdict '{rec.get('verdict')}' 인데 pred_registered_at 없음 (영수증 사슬 끊김)")
    return None


def _check_scripted_source(rec: dict) -> Finding | None:
    v, src = rec.get("verdict", ""), rec.get("verdict_source")
    # Legacy scripted rows may predate source stamping, but a dialectical shadow is a new
    # managed-write shape: accepting a missing source here would let an offline-corrupted PU
    # evade both this check and the source-conditioned receipt-pointer check below.
    dialectical_source_missing = v in _SCRIPTED_DIALECTICAL_VERDICTS and src is None
    invalid_present_source = src is not None and src not in FORCEFUL_SOURCES
    if _is_scripted_judgement(rec) and (dialectical_source_missing or invalid_present_source):
        if dialectical_source_missing:
            return Finding("SCRIPTED_WITHOUT_SOURCE", _SEVERITY["SCRIPTED_WITHOUT_SOURCE"],
                           f"scripted dialectical '{v}' 인데 verdict_source 없음 "
                           f"(오프라인 손상 — managed write 는 FORCEFUL source 를 스탬프함)")
        return Finding("SCRIPTED_WITHOUT_SOURCE", _SEVERITY["SCRIPTED_WITHOUT_SOURCE"],
                       f"scripted '{v}' 인데 verdict_source='{src}' 가 영수증(FORCEFUL) 아님 (force_of 오판)")
    return None


def _check_tier_resolve(rec: dict) -> Finding | None:
    # G6(git-흡수): scripted 판결 write 는 단일 디스패치가 tier 를 resolve 해 스탬프한다
    # (judgement_service e.assurance_tier_resolved). 스탬프 없는 scripted 판결 = G6 이전 write(legacy —
    # skiplist 로만 면제) 또는 디스패치 우회(진짜 부패). git fsck 의 FATAL 비강등 규율: 규칙은 못 깎는다.
    if _is_scripted_judgement(rec) and not rec.get("assurance_tier_resolved"):
        return Finding("VERDICT_WRITE_WITHOUT_TIER_RESOLVE", _SEVERITY["VERDICT_WRITE_WITHOUT_TIER_RESOLVE"],
                       f"scripted verdict '{rec.get('verdict')}' 인데 assurance_tier_resolved 스탬프 없음 "
                       f"(G6 이전 write 는 record content-sha skiplist 로만 면제)")
    return None


def _check_receipt_chain(rec: dict) -> Finding | None:
    """R5: enriched 레코드(감사 스윕이 receipts 동봉) 전용 — head 포인터가 체인 밖이면 dangling.
    비동봉 레코드는 판단 보류(발화 없음 — 기존 record-level 계약 비파괴)."""
    if "receipts" in rec and rec.get("current_receipt_sha"):
        shas = {r.get("receipt_sha") for r in (rec.get("receipts") or [])}
        if rec["current_receipt_sha"] not in shas:
            return Finding("RECEIPT_CHAIN_MISMATCH", _SEVERITY["RECEIPT_CHAIN_MISMATCH"],
                           f"current_receipt_sha={rec['current_receipt_sha'][:12]}… 가 동봉 체인에 없음(dangling)")
    return None


def _check_forceful_receipt(rec: dict) -> Finding | None:
    """R6: FORCEFUL source(scripted/engine/…) 판결인데 :VerdictReceipt 포인터가 없음 — G1 이전 write
    (legacy, skiplist 로만 면제) 또는 원장 우회(진짜 부패). 라이브 159건+333v2 손기록 10건의 장르."""
    if rec.get("verdict_source") in FORCEFUL_SOURCES and not rec.get("current_receipt_sha"):
        return Finding("FORCEFUL_SOURCE_WITHOUT_RECEIPT", _SEVERITY["FORCEFUL_SOURCE_WITHOUT_RECEIPT"],
                       f"verdict_source='{rec.get('verdict_source')}' 인데 current_receipt_sha 없음 "
                       f"(원장 공백 — 레코드 열거 면제만 가능, 규칙 면제 불가)")
    return None


def _check_receipt_sha_content(rec: dict) -> Finding | None:
    """jp3(JP 캠페인): read-time recompute-and-reject — 동봉 영수증마다 stored receipt_sha 를 content
    로부터 재유도(알려진 인코딩 계보 전수: v2/v1 presence-dispatch + pre-ag3, prediction 은 자기 도메인)
    해 대조. 어느 것과도 불일치 = in-place 변조/원장우회 위조행 → ERROR. fold 는 불변(AG1 pointer-walk
    ADR 경계 — 검증 좌석은 fsck/verify, fold 아님). R5 와 같은 enriched-전용 발화(비동봉=판단 보류)."""
    if "receipts" not in rec:
        return None
    bad = [r for r in (rec.get("receipts") or [])
           if r.get("receipt_sha") and match_receipt_encoding(r, r["receipt_sha"]) is None]
    if bad:
        r0 = bad[0]
        return Finding("RECEIPT_SHA_CONTENT_MISMATCH", _SEVERITY["RECEIPT_SHA_CONTENT_MISMATCH"],
                       f"{len(bad)}건: stored={r0['receipt_sha'][:12]}… ≠ recompute={receipt_content_sha(r0)[:12]}… "
                       f"— 어느 알려진 인코딩과도 불일치(in-place 변조/원장우회 위조)")
    return None


def _check_receipt_encoding_stale(rec: dict) -> Finding | None:
    """jp3: 미선언 구-인코딩(계보 일치, 'current' 아님)의 정직 mint — 필드드리프트를 시끄럽게(WARN, 비차단).
    label ∉ (None, 'current') 만: 변조(None)는 MISMATCH ERROR 단독 발화(이중 발화 금지 — 신호 순도)."""
    if "receipts" not in rec:
        return None
    stale = [(r, lbl) for r in (rec.get("receipts") or [])
             if r.get("receipt_sha")
             and (lbl := match_receipt_encoding(r, r["receipt_sha"])) not in (None, "current")]
    if stale:
        return Finding("RECEIPT_ENCODING_STALE", _SEVERITY["RECEIPT_ENCODING_STALE"],
                       f"{len(stale)}건 구-인코딩('{stale[0][1]}') 정직 mint — 미선언 필드드리프트 가시화"
                       f"(변조 아님; 재봉인은 재채점/freshen 경로로)")
    return None


def _check_measurement_refuted(rec: dict) -> Finding | None:
    """AG6/R-SOV V4 값무결 (측정주권 2026-07-03): producer replay 가 *실행되어 측정을 반증*
    (replay_status='mismatch')했는데 노드가 여전히 standing verdict 를 든다 → 값무결 WARN(비차단).

    승격 floor(G6)는 CANONICAL 만 막는다 — progressive/partial 로 선 반증된 측정은 조용했다. 이 차원이
    관측화(WARN)해 재실험/분기를 권고하되 write 를 막지 않는다(boundary min ERROR). ★dead-σ:
    not_attempted(exec OFF)/not_replayable(CLI 계약 비호환 등 실행 불가 — 2026-07-13 신설)/verified(일치)/
    비-standing verdict 은 무발화(검증 불가·일치·이미 부정 ≠ 반증)."""
    if rec.get("replay_status") != "mismatch":
        return None
    if rec.get("verdict") in _STANDING_VERDICTS:
        return Finding("MEASUREMENT_REFUTED_BUT_STANDING", _SEVERITY["MEASUREMENT_REFUTED_BUT_STANDING"],
                       f"replay_status='mismatch'(측정 재실행이 값을 반증)인데 verdict='{rec.get('verdict')}' "
                       f"로 서있음 — 값무결 경고(비차단; 재실험 또는 새 노드로 분기 권고)")
    return None


def _check_comment_drift(rec: dict) -> Finding | None:
    """S4(EXTAUDIT 2026-07-23): 판정 시점 봉인(comment_sha_at_verdict) 대비 현재 comment 가 개서됨 —
    c6 장르(REJECTED/degenerating 노드에 사후 승리 에세이). 봉인 이전 레거시(None)는 판단 보류(부재≠반증).
    차단 아님(WARN): 서사는 자유이되 *판정 이후 바뀌었다는 사실*이 감사 표면에 남는다."""
    if comment_drift(rec) is True:
        return Finding("COMMENT_DRIFT_AFTER_VERDICT", _SEVERITY["COMMENT_DRIFT_AFTER_VERDICT"],
                       f"verdict='{rec.get('verdict')}' 판정 이후 comment 개서 — 봉인 "
                       f"{str(rec.get('comment_sha_at_verdict'))[:12]}… ≠ 현재 comment sha (서사 드리프트)")
    return None


_CHECKS = (_check_source_trust, _check_judged_at_type, _check_prereg, _check_scripted_source,
           _check_tier_resolve, _check_receipt_chain, _check_forceful_receipt,
           _check_receipt_sha_content, _check_receipt_encoding_stale,
           _check_measurement_refuted, _check_comment_drift)


def record_content_sha(rec: dict) -> str:
    """skiplist 키 — record *내용*의 sha256(정렬키 canonical JSON). git per-OID skiplist 이식: 면제는
    이 내용 그대로일 때만 유효하고, 레코드가 한 글자라도 바뀌면 sha 가 달라져 면제가 소멸한다(규칙 면제 불가)."""
    blob = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fsck_node(rec: dict, *, skiplist: frozenset[str] = frozenset()) -> list[Finding]:
    """단일 노드 record → findings(열거된 check-id 만). 순수·결정론 — 감사와 경계가 공유하는 유일 체커.

    skiplist(G6) = record_content_sha 집합 — 열거된 *레코드*만 면제(git per-OID skiplist). 체커/심각도는
    면제 불가: legacy 는 규칙을 깎아서가 아니라 레코드를 열거해서만 지나간다."""
    if skiplist and record_content_sha(rec) in skiplist:
        return []
    return [f for chk in _CHECKS if (f := chk(rec)) is not None]


def fsck_records(records: list[dict], *, skiplist: frozenset[str] = frozenset()) -> list[Finding]:
    """감사 스윕 — 전 노드에 fsck_node 를 돌려 findings 를 모은다(오프라인 전수 감사)."""
    return [f for rec in records for f in fsck_node(rec, skiplist=skiplist)]


def boundary_fsck(rec: dict, *, min_severity: str = ERROR,
                  skiplist: frozenset[str] = frozenset()) -> list[Finding]:
    """쓰기 경계 게이트 — *동일* fsck_node 를 쓰되 min_severity 이상만 반환(거부 후보).

    audit==ingest: 같은 체커·같은 _SEVERITY 테이블·같은 skiplist 의미론. min_severity 는 '무엇을
    *거부*하나'의 임계일 뿐, *판정*(check_id·severity)은 감사와 바이트동일(양방향). 기본 ERROR:
    WARN(부패지만 치명 아님)은 통과+기록.
    """
    thr = _ORDER[min_severity]
    return [f for f in fsck_node(rec, skiplist=skiplist) if _ORDER[f.severity] >= thr]


def load_skiplist(path: str | None = None) -> frozenset[str]:
    """git-추적 skiplist 로드(R6 확정결정: KG 저장 기각 — writer 셀프등재 자기면제 구멍).

    기본 = <repo>/docs/fsck_skiplist.json, env LAKATOS_FSCK_SKIPLIST 로 대체(테스트/운영 오버라이드).
    형식 {"entries": [{"sha": <record_content_sha>, "tree": ..., "tag": ..., "reason": ...}]} —
    sha 외 필드는 사람 검토 기록. 파일 부재 = 빈 면제(fail-safe). 감사·경계가 *같은* 로더를 쓴다."""
    import os
    from pathlib import Path
    p = Path(path or os.environ.get("LAKATOS_FSCK_SKIPLIST")
             or Path(__file__).resolve().parents[3] / "docs" / "fsck_skiplist.json")
    if not p.is_file():
        return frozenset()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return frozenset()   # 부패한 skiplist = 면제 0(fail-safe: 면제가 늘어나는 방향 금지)
    return frozenset(e.get("sha") for e in data.get("entries", []) if e.get("sha"))
