"""B1 (override 2026-06-16): KG↔PG 발산을 *auditable* 하게 만드는 transactional-outbox + reconcile.

2026-06-16 결정은 hist(PG best-effort) 실패를 *조용히 삼켰다*(이력 유실, 복구=재실행만). 사용자 override
(2026-06-21): KG=truth / PG=best-effort 불변은 유지하되, hist 실패를 잃지 말고 KG OutboxEntry(정본)에 기록하고
reconcile sweep 가 *멱등* 재적용한다. 2PC 아님 — KG 가 진실, PG 는 따라잡되 그 따라잡음이 감사가능해진다.

이 모듈은 io 레이어 *순수* 로직만(드라이버 없음): outbox id 결정성 + 재적용 계획. 실 KG/PG 접촉은
server.container(AppContainer.hist / reconcile_outbox)가 이 함수들을 소비한다.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


_HISTORY_EVENT_DOMAIN = "lakatotree-history-event-v1"


class HistoryPayloadError(ValueError):
    """A history value cannot be represented by PostgreSQL UTF-8/JSONB."""


def _validate_pg_text(value: str, path: str) -> None:
    if "\x00" in value:
        raise HistoryPayloadError(f"NUL is not representable at {path}")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise HistoryPayloadError(f"invalid Unicode at {path}") from exc


def _validate_pg_json(value: Any, path: str = "payload") -> None:
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise HistoryPayloadError(f"non-finite number at {path}")
        return
    if isinstance(value, str):
        _validate_pg_text(value, path)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_pg_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise HistoryPayloadError(f"non-string key at {path}")
            _validate_pg_text(key, f"{path}.<key>")
            _validate_pg_json(item, f"{path}.{key}")
        return
    raise HistoryPayloadError(f"unsupported JSON value at {path}: {type(value).__name__}")


def validate_history_record(
    tree: str,
    op: str,
    node_tag: str | None,
    payload: dict,
    event_id: str | None = None,
) -> str:
    """Return canonical JSON only when every value is PostgreSQL-safe.

    This validator is deliberately shared by the domain mutation, direct history
    appends, reconciliation, and deployment audits.  Neo4j accepts NUL escapes and
    lone surrogates that PostgreSQL JSONB rejects, so validating only at projection
    time would leave a permanently poisoned durable intent.
    """

    for field, value in (("tree", tree), ("op", op)):
        if not isinstance(value, str) or not value:
            raise HistoryPayloadError(f"{field} must be a non-empty string")
        _validate_pg_text(value, field)
    if node_tag is not None:
        if not isinstance(node_tag, str):
            raise HistoryPayloadError("node_tag must be text or null")
        _validate_pg_text(node_tag, "node_tag")
    if event_id is not None:
        if not isinstance(event_id, str) or not event_id:
            raise HistoryPayloadError("event_id must be a non-empty string or null")
        _validate_pg_text(event_id, "event_id")
    if not isinstance(payload, dict):
        raise HistoryPayloadError("payload must be a JSON object")
    _validate_pg_json(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_history_payload(payload: dict) -> str:
    """Canonical JSON shared by the stable event key, Neo4j intent, and PG row."""
    if not isinstance(payload, dict):
        raise HistoryPayloadError("payload must be a JSON object")
    _validate_pg_json(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def history_event_id(
    tree: str,
    op: str,
    subject_id: str,
) -> str:
    """Stable key for one logical event; immutable content is verified separately."""
    raw = json.dumps(
        [_HISTORY_EVENT_DOMAIN, tree, op, subject_id],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "he-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def history_advisory_lock_keys(
    event_id: str,
    tree: str,
    op: str,
    node_tag: str | None,
    payload_json: str,
) -> tuple[int, ...]:
    """Signed PostgreSQL advisory keys serializing both identity and exact content."""

    def lock_key(domain: str, value: object) -> int:
        raw = json.dumps(
            ["lakatotree-history-lock-v1", domain, value],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return int.from_bytes(
            hashlib.sha256(raw.encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )

    keys = {
        lock_key("event", event_id),
        lock_key("content", [tree, op, node_tag, payload_json]),
    }
    return tuple(sorted(keys))


def outbox_id(tree: str, op: str, node_tag: str | None, payload: dict, ts: str) -> str:
    """결정적 OutboxEntry id — 같은 hist 실패가 중복 pending 을 안 만들게(MERGE 키) + PG ON CONFLICT 키.
    ts 포함: 같은 (tree,op,tag,payload) 의 *다른 시점* 이벤트는 구분(append-only 이력 의미 보존)."""
    raw = json.dumps([tree, op, node_tag, payload, ts], ensure_ascii=False, sort_keys=True, default=str)
    return 'ob-' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def plan_reconcile(pending: list, applied_ids=()) -> dict:
    """pending OutboxEntry(KG 정본) + 이미 적용된 id → 재적용 계획. 순수(테스트 가능).

    to_replay = pending ∧ ¬applied (멱등: 이미 적용된 건 건너뜀). already_applied = 교집합.
    """
    applied = set(applied_ids or ())
    to_replay = [e for e in pending if e.get('id') not in applied]
    return {
        'to_replay': to_replay,
        'already_applied': [e['id'] for e in pending if e.get('id') in applied],
        'pending_total': len(pending),
        'replay_count': len(to_replay),
    }
