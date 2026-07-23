#!/usr/bin/env python3
"""temporal-witness 라이브 프로브 novel 채점기 — 2-of-2 정족수 시간증인 성립 (baseline 0 → 목표 1).

주 메트릭(적대 차단)과 독립인 별도 실측 — *양의 능력*: happy 시나리오 노드에
pred_anchor_quorum==2 ∧ temporal_witness_verified==True 가 라이브 persist 됐는가.
novel_threshold 1(higher): 정족수 시간증인이 실제로 열리면 1, 아니면 0.
stdout `metric=<int>` + exit 0. 결정론 — LLM 무관, 커밋 증거만 읽음(replay 안전).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-extaudit-temporal-witness-20260722
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "ooptdd_receipts" / "temporal_witness_probe_20260723" / "probe_evidence.json"


def witness_established() -> int:
    try:
        ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    for sc in ev.get("scenarios", []):
        if sc.get("name") != "happy_2of2":
            continue
        guards = {g["guard"]: g["actual"] for g in sc.get("guards", [])}
        if (guards.get("node.pred_anchor_quorum") == 2
                and guards.get("node.temporal_witness_verified") is True):
            return 1
    return 0


if __name__ == '__main__':
    print(f"metric={witness_established()}")
    sys.exit(0)
