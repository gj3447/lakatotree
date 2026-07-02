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

from dataclasses import dataclass

from lakatos.verdicts import FORCEFUL_SOURCES, is_scripted_verdict

# 심각도 서열(단일 정본 — audit·boundary 가 공유). FATAL > ERROR > WARN > INFO.
FATAL, ERROR, WARN, INFO = "FATAL", "ERROR", "WARN", "INFO"
_ORDER = {INFO: 0, WARN: 1, ERROR: 2, FATAL: 3}

# check-id → 심각도. 새 check 는 여기서만(H9 스타일 SSOT). 열거되지 않은 부패는 존재하지 않는 것처럼 다루지 않는다.
_SEVERITY = {
    "SOURCE_TRUST_NULL": WARN,          # present-but-None trust → tree_metrics 500 유발(크래시-안전은 evidence_weight 가, 감사는 여기)
    "MIXED_JUDGED_AT_TYPE": WARN,       # judged_at 이 dict/epoch/ISO 혼재 → 읽기 표류
    "VERDICT_WITHOUT_PREREG": ERROR,    # scripted 판결인데 사전등록(pred_registered_at) 없음 = 영수증 사슬 끊김
    "SCRIPTED_WITHOUT_SOURCE": ERROR,   # scripted 어휘인데 verdict_source 가 영수증(FORCEFUL)이 아님 = force_of 오판
}


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
    if is_scripted_verdict(rec.get("verdict", "")) and not rec.get("pred_registered_at"):
        return Finding("VERDICT_WITHOUT_PREREG", _SEVERITY["VERDICT_WITHOUT_PREREG"],
                       f"scripted verdict '{rec.get('verdict')}' 인데 pred_registered_at 없음 (영수증 사슬 끊김)")
    return None


def _check_scripted_source(rec: dict) -> Finding | None:
    v, src = rec.get("verdict", ""), rec.get("verdict_source")
    if is_scripted_verdict(v) and src is not None and src not in FORCEFUL_SOURCES:
        return Finding("SCRIPTED_WITHOUT_SOURCE", _SEVERITY["SCRIPTED_WITHOUT_SOURCE"],
                       f"scripted '{v}' 인데 verdict_source='{src}' 가 영수증(FORCEFUL) 아님 (force_of 오판)")
    return None


_CHECKS = (_check_source_trust, _check_judged_at_type, _check_prereg, _check_scripted_source)


def fsck_node(rec: dict) -> list[Finding]:
    """단일 노드 record → findings(열거된 check-id 만). 순수·결정론 — 감사와 경계가 공유하는 유일 체커."""
    return [f for chk in _CHECKS if (f := chk(rec)) is not None]


def fsck_records(records: list[dict]) -> list[Finding]:
    """감사 스윕 — 전 노드에 fsck_node 를 돌려 findings 를 모은다(오프라인 전수 감사)."""
    return [f for rec in records for f in fsck_node(rec)]


def boundary_fsck(rec: dict, *, min_severity: str = ERROR) -> list[Finding]:
    """쓰기 경계 게이트 — *동일* fsck_node 를 쓰되 min_severity 이상만 반환(거부 후보).

    audit==ingest: 같은 체커·같은 _SEVERITY 테이블. min_severity 는 '무엇을 *거부*하나'의 임계일 뿐,
    *판정*(check_id·severity)은 감사와 바이트동일(양방향). 기본 ERROR: WARN(부패지만 치명 아님)은 통과+기록.
    """
    thr = _ORDER[min_severity]
    return [f for f in fsck_node(rec) if _ORDER[f.severity] >= thr]
