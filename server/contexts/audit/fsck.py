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
from lakatos.measurement_lock import lock_sha as measurement_lock_content_sha
from lakatos.io.prov import replay_command

# 심각도 서열(단일 정본 — audit·boundary 가 공유). FATAL > ERROR > WARN > INFO.
FATAL, ERROR, WARN, INFO = "FATAL", "ERROR", "WARN", "INFO"
_ORDER = {INFO: 0, WARN: 1, ERROR: 2, FATAL: 3}

# check-id → 심각도. 새 check 는 여기서만(H9 스타일 SSOT). 열거되지 않은 부패는 존재하지 않는 것처럼 다루지 않는다.
_SEVERITY = {
    "SOURCE_TRUST_NULL": WARN,          # 인터넷 source 가 실재하는데 trust 없음 → 외부증거 가중 불능
    "MIXED_JUDGED_AT_TYPE": WARN,       # judged_at 이 dict/epoch/ISO 혼재 → 읽기 표류
    "VERDICT_WITHOUT_PREREG": ERROR,    # scripted 판결인데 사전등록(pred_registered_at) 없음 = 영수증 사슬 끊김
    "SCRIPTED_WITHOUT_SOURCE": ERROR,   # scripted 어휘인데 verdict_source 가 영수증(FORCEFUL)이 아님 = force_of 오판
    "VERDICT_WRITE_WITHOUT_TIER_RESOLVE": ERROR,   # G6: 판결 write 에 tier resolve 흔적 없음 = 디스패치 우회/G6 이전
    "RECEIPT_CHAIN_MISMATCH": ERROR,    # R5: current_receipt_sha 가 동봉 체인 밖(dangling — 변조/부패). verify 라우트와 공용 어휘
    "FORCEFUL_SOURCE_WITHOUT_RECEIPT": ERROR,   # R6: FORCEFUL 판결인데 원장 포인터 없음(G1 이전/우회 write — skiplist 로만 면제)
    "MEASUREMENT_REFUTED_BUT_STANDING": WARN,   # AG6: replay 가 측정을 반증(mismatch)했는데 standing verdict — 값무결 관측(비차단)
    "REPLAY_DIAGNOSTIC_CACHE_MISMATCH": ERROR,  # v4 head receipt와 node replay 진단 캐시 불일치
    "REPLAY_INPUT_CACHE_MISMATCH": ERROR,       # v5 head receipt와 node replay 입력 캐시 불일치
    "MEASUREMENT_LOCK_CONTENT_MISMATCH": ERROR, # sealed lock SHA와 payload_json 재해시 불일치/부재
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
    # ``source`` is added by TreeKgRepository only for nodes backed by an actual internet
    # ResearchEvent.  Internal/bash-only nodes correctly have no external-source trust score;
    # treating their NULL as corruption tempted migrations that manufactured internet evidence.
    if rec.get("source") and rec.get("source_trust") is None:
        return Finding("SOURCE_TRUST_NULL", _SEVERITY["SOURCE_TRUST_NULL"],
                       "internet ResearchEvent source가 있으나 source_trust 없음 "
                       "(EigenTrust 재도출 필요; 내부 기본값으로 대체 금지)")
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
        heads = [r for r in (rec.get("receipts") or []) if isinstance(r, dict)
                 and r.get("receipt_sha") == rec["current_receipt_sha"]]
        if len(heads) != 1:
            return Finding("RECEIPT_CHAIN_MISMATCH", _SEVERITY["RECEIPT_CHAIN_MISMATCH"],
                           f"current_receipt_sha={rec['current_receipt_sha'][:12]}… head cardinality="
                           f"{len(heads)} (exactly one required; dangling/duplicate)")
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


def _replay_failure_class(reason: str | None) -> str:
    """Persisted producer-replay reason → operator-facing failure class.

    ``mismatch`` is the historical umbrella status: it includes an actual numeric disagreement,
    scorer exit, and missing metric output.  Keep the stable fsck check-id while recovering the
    actionable distinction from the server-generated reason.  Rows minted before reason
    persistence are explicitly unclassified rather than retroactively called a refutation.
    """
    if not reason:
        return "legacy_unclassified"
    if reason == "metric_mismatch":
        return "value_mismatch"
    if reason.startswith("scorer_nonzero_exit:"):
        return "scorer_execution_failure"
    if reason == "no_metric_in_output":
        return "metric_output_missing"
    if reason == "cli_contract_incompatible":
        return "cli_contract_incompatible"
    if reason.startswith("replay_infrastructure_error:"):
        return "replay_infrastructure_failure"
    return "other_replay_failure"


def _valid_replay_head(rec: dict) -> dict | None:
    """Return one content-valid replay-diagnostic head (historical v4 or artifact v5)."""
    head_sha = rec.get("current_receipt_sha")
    if not head_sha or "receipts" not in rec:
        return None
    heads = [r for r in (rec.get("receipts") or []) if isinstance(r, dict)
             and r.get("receipt_sha") == head_sha]
    head = heads[0] if len(heads) == 1 else None
    if (not head or head.get("receipt_kind") == "prediction"
            or not head.get("replay_status")
            or match_receipt_encoding(head, head_sha) != "current"):
        return None
    return head


def valid_replay_head(rec: dict) -> dict | None:
    """Public read-boundary helper for the content-valid v4/v5 replay family."""
    return _valid_replay_head(rec)


_ARTIFACT_RECEIPT_FIELDS = (
    "judge_script_path", "result_path", "result_sha256", "measurement_lock_sha",
    "source_script_path", "source_result_path",
)


def _valid_artifact_head(rec: dict) -> dict | None:
    """Return a content-valid v5 head selected by its sealed artifact-identity presence."""
    head = _valid_replay_head(rec)
    if head is None or not any(head.get(key) is not None for key in _ARTIFACT_RECEIPT_FIELDS):
        return None
    return head


def valid_artifact_head(rec: dict) -> dict | None:
    """Public provenance boundary: only v5 can authorize an executable artifact recipe."""
    return _valid_artifact_head(rec)


def _valid_v4_head(rec: dict) -> dict | None:
    """Compatibility alias for callers that mean the v4-origin replay-diagnostic family."""
    return _valid_replay_head(rec)


def valid_v4_head(rec: dict) -> dict | None:
    """Compatibility alias; new artifact-authority callers must use ``valid_artifact_head``."""
    return _valid_replay_head(rec)


_ARTIFACT_INPUT_CACHE_FIELDS = (
    ("judge_script", "judge_script_path"),
    ("judge_script_sha", "judge_script_sha"),
    ("result_path", "result_path"),
    ("result_sha256", "result_sha256"),
    ("measurement_lock_sha", "measurement_lock_sha"),
    ("source_judge_script_path", "source_script_path"),
    ("source_result_path", "source_result_path"),
)


def _artifact_input_cache_mismatches(rec: dict, head: dict) -> list[str]:
    return [node_key for node_key, receipt_key in _ARTIFACT_INPUT_CACHE_FIELDS
            if rec.get(node_key) != head.get(receipt_key)]


def _sealed_replay_diagnostic(rec: dict) -> tuple[str | None, float | None] | None:
    """Return v4/v5 head diagnostics only when every applicable node cache matches."""
    head = _valid_replay_head(rec)
    if head is None:
        return None  # pre-v4 or invalid receipt: diagnosis is untrusted
    cache = (rec.get("replay_status"), rec.get("replay_reason"), rec.get("regenerated_metric"))
    sealed = (head.get("replay_status"), head.get("replay_reason"), head.get("regenerated_metric"))
    if cache != sealed:
        return None
    artifact_head = _valid_artifact_head(rec)
    if artifact_head is not None and _artifact_input_cache_mismatches(rec, artifact_head):
        return None
    return head.get("replay_reason"), head.get("regenerated_metric")


def _check_replay_diagnostic_cache(rec: dict) -> Finding | None:
    """A v4/v5 receipt is immutable, but its projected node cache also needs parity."""
    head = _valid_replay_head(rec)
    if head is None:
        return None
    cache = (rec.get("replay_status"), rec.get("replay_reason"), rec.get("regenerated_metric"))
    sealed = (head.get("replay_status"), head.get("replay_reason"), head.get("regenerated_metric"))
    if cache != sealed:
        return Finding(
            "REPLAY_DIAGNOSTIC_CACHE_MISMATCH",
            _SEVERITY["REPLAY_DIAGNOSTIC_CACHE_MISMATCH"],
            "node replay diagnostic cache differs from content-addressed v4/v5 head receipt",
        )
    return None


def _check_replay_input_cache(rec: dict) -> Finding | None:
    """A mutable node projection cannot retarget a content-valid v5 replay receipt."""
    head = _valid_artifact_head(rec)
    if head is None:
        return None
    mismatches = _artifact_input_cache_mismatches(rec, head)
    if mismatches:
        return Finding(
            "REPLAY_INPUT_CACHE_MISMATCH",
            _SEVERITY["REPLAY_INPUT_CACHE_MISMATCH"],
            "node replay input cache differs from content-addressed v5 head receipt: "
            + ", ".join(mismatches),
        )
    return None


def measurement_lock_payload_matches_head(head: dict, payload: dict) -> bool:
    """Whether a content-valid lock is semantically the measurement sealed by a v5 receipt.

    The lock hash alone only authenticates the lock object.  This second relation prevents an
    attacker from minting a different, internally valid lock and resealing its SHA into a receipt.
    """
    if not isinstance(payload, dict):
        return False
    deps = payload.get("deps") or []
    if not isinstance(deps, list) or any(not isinstance(dep, dict) for dep in deps):
        return False
    script_path, result_path = head.get("judge_script_path"), head.get("result_path")
    expected_deps = ((script_path, head.get("judge_script_sha")),
                     (result_path, head.get("result_sha256")))
    dep_mismatch = any(
        sum(1 for dep in deps
            if dep.get("path") == path and dep.get("sha256") == sha) != 1
        for path, sha in expected_deps
    )
    expected_outs = [{
        "name": str(head.get("metric_name") or ""),
        "value": head.get("metric_value"),
    }]
    return (
        payload.get("cmd") == replay_command(script_path or "", result_path or "")
        and not dep_mismatch
        and payload.get("outs") == expected_outs
        and payload.get("measurement_grade") == head.get("measurement_grade")
        and payload.get("replay_status") == head.get("replay_status")
    )


def _check_measurement_lock_content(rec: dict) -> Finding | None:
    """Rehash the exact MeasurementLock payload selected by the valid v5 head receipt.

    Like receipt recomputation, this fires only for an enriched read record.  Legacy/base records
    without ``measurement_locks`` remain a deliberate no-op; ops/provenance explicitly enrich v5
    rows and therefore fail closed on a missing, duplicate, malformed, or altered lock payload.
    """
    head = _valid_artifact_head(rec)
    sealed_sha = head.get("measurement_lock_sha") if head is not None else None
    if head is None or not sealed_sha or "measurement_locks" not in rec:
        return None
    matches = [lock for lock in (rec.get("measurement_locks") or [])
               if isinstance(lock, dict) and lock.get("lock_sha") == sealed_sha]
    if len(matches) != 1:
        return Finding(
            "MEASUREMENT_LOCK_CONTENT_MISMATCH",
            _SEVERITY["MEASUREMENT_LOCK_CONTENT_MISMATCH"],
            f"sealed MeasurementLock {str(sealed_sha)[:12]}… has {len(matches)} matching records",
        )
    payload_json = matches[0].get("payload_json")
    try:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else None
        derived = measurement_lock_content_sha(payload) if isinstance(payload, dict) else None
    except (TypeError, ValueError):
        derived = None
    if derived != sealed_sha:
        return Finding(
            "MEASUREMENT_LOCK_CONTENT_MISMATCH",
            _SEVERITY["MEASUREMENT_LOCK_CONTENT_MISMATCH"],
            f"MeasurementLock payload rehash {str(derived)[:12]}… != sealed {str(sealed_sha)[:12]}…",
        )
    if not measurement_lock_payload_matches_head(head, payload):
        return Finding(
            "MEASUREMENT_LOCK_CONTENT_MISMATCH",
            _SEVERITY["MEASUREMENT_LOCK_CONTENT_MISMATCH"],
            "MeasurementLock payload is content-valid but not bound to sealed v5 "
            "command/dependencies/outs/grade/status",
        )
    return None


def _check_measurement_refuted(rec: dict) -> Finding | None:
    """AG6/R-SOV V4 값무결 (측정주권 2026-07-03): producer replay 의 ``mismatch`` umbrella
    상태인데 노드가 여전히 standing verdict 를 든다 → 값무결 WARN(비차단).

    승격 floor(G6)는 CANONICAL 만 막는다 — progressive/partial 로 선 반증된 측정은 조용했다. 이 차원이
    관측화(WARN)해 재실험/분기를 권고하되 write 를 막지 않는다(boundary min ERROR). replay_reason 이
    영속된 신규 행은 실제 값 불일치와 scorer 실행/출력 실패를 detail 에서 분류한다. check-id 는 감사
    소비자 호환을 위해 유지하지만, legacy reason-null 은 반증으로 단정하지 않고 unclassified 로 표기한다. ★dead-σ:
    not_attempted(exec OFF)/not_replayable(CLI 계약 비호환 등 실행 불가 — 2026-07-13 신설)/verified(일치)/
    비-standing verdict 은 무발화(검증 불가·일치·이미 부정 ≠ 반증)."""
    if rec.get("replay_status") != "mismatch":
        return None
    if rec.get("verdict") in _STANDING_VERDICTS:
        sealed = _sealed_replay_diagnostic(rec)
        reason = sealed[0] if sealed is not None else None
        regenerated = sealed[1] if sealed is not None else None
        failure_class = _replay_failure_class(reason)
        prefix = (f"replay_status='mismatch', replay_reason={reason!r}, "
                  f"replay_failure_class='{failure_class}'")
        if failure_class == "value_mismatch":
            diagnosis = (f"재생성 값이 기록값과 다름(recorded={rec.get('metric_value')!r}, "
                         f"regenerated={regenerated!r})")
        elif failure_class == "scorer_execution_failure":
            diagnosis = "scorer 비정상 종료로 값 비교 전 실패(실행/환경 수리 후 재시도 필요)"
        elif failure_class == "metric_output_missing":
            diagnosis = "scorer 출력에 metric 이 없어 값 비교 전 실패(출력 계약 수리 필요)"
        elif failure_class == "legacy_unclassified":
            diagnosis = "구버전 행에 원인 미영속 — 값 불일치/실행 실패를 구분할 수 없어 재채점 필요"
        else:
            diagnosis = "replay 실패 원인을 확인해 값 재실험 또는 scorer 계약 수리 필요"
        return Finding("MEASUREMENT_REFUTED_BUT_STANDING", _SEVERITY["MEASUREMENT_REFUTED_BUT_STANDING"],
                       f"{prefix}: {diagnosis}; verdict='{rec.get('verdict')}' 로 서있음 — "
                       f"값무결 경고(비차단)")
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
           _check_replay_diagnostic_cache, _check_replay_input_cache,
           _check_measurement_lock_content, _check_measurement_refuted, _check_comment_drift)


def record_content_sha(rec: dict) -> str:
    """skiplist 키 — record *내용*의 sha256(정렬키 canonical JSON). git per-OID skiplist 이식: 면제는
    이 내용 그대로일 때만 유효하고, 레코드가 한 글자라도 바뀌면 sha 가 달라져 면제가 소멸한다(규칙 면제 불가).

    Replay diagnostics/artifact hashes were added to the base projection after the legacy skiplist
    was reviewed. Neo4j projects an absent property as an explicit ``None``; treating those newly
    introduced nulls as absence preserves the reviewed legacy OIDs, while any non-null identity or
    diagnosis still changes the content hash and therefore loses the exemption as intended.
    """
    canonical = dict(rec)
    # engine_rule_sha: P3(2026-07-28) head-receipt 조인으로 projection 에 추가 — 무영수증 legacy
    # 노드는 None 이므로 absence 로 취급해 리뷰된 면제를 보존(비-null 봉인 sha 는 의도대로 sha 변경).
    for optional_key in ("replay_reason", "regenerated_metric", "result_sha256",
                         "source_judge_script_path", "source_result_path",
                         "engine_rule_sha"):
        if canonical.get(optional_key) is None:
            canonical.pop(optional_key, None)
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)
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

    기본 = <repo>/docs/data/fsck_skiplist.json, env LAKATOS_FSCK_SKIPLIST 로 대체(테스트/운영 오버라이드).
    형식 {"entries": [{"sha": <record_content_sha>, "tree": ..., "tag": ..., "reason": ...}]} —
    sha 외 필드는 사람 검토 기록. 파일 부재 = 빈 면제(fail-safe). 감사·경계가 *같은* 로더를 쓴다."""
    import os
    from pathlib import Path
    p = Path(path or os.environ.get("LAKATOS_FSCK_SKIPLIST")
             or Path(__file__).resolve().parents[3] / "docs" / "data" / "fsck_skiplist.json")
    if not p.is_file():
        return frozenset()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return frozenset()   # 부패한 skiplist = 면제 0(fail-safe: 면제가 늘어나는 방향 금지)
    return frozenset(e.get("sha") for e in data.get("entries", []) if e.get("sha"))
