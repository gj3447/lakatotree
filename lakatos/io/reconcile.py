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
