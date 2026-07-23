#!/usr/bin/env python3
"""temporal-witness 라이브 프로브 채점기 — 적대 가드 실패 수 (baseline 4 → 목표 0).

측정: 커밋된 라이브 증거(ooptdd_receipts/temporal_witness_probe_20260723/probe_evidence.json)의
적대 시나리오(sybil·outsider·digest_mismatch·future_gen_time) 가드 실패 수를 센다.
baseline 4 근거: S7b/D1 메커니즘 부재 시 이 4 공격은 409 DB-락만으로는 전부 묵인됐다(질문 본문:
run-first-register-second 가 완벽한 novel 적중이 됐던 구조). 구현 후 0 이어야 차단 실증.
stdout `metric=<int>` + exit 0 (harness 계약, ag1 장르). 결정론 — LLM 무관, 커밋 증거만 읽음(replay 안전).
사전등록 후 이 파일 동결 (script_sha 서버 앵커).
# KG 거울: LakatosTree_LakatoTree_SelfDev_20260612 / q-extaudit-temporal-witness-20260722
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "ooptdd_receipts" / "temporal_witness_probe_20260723" / "probe_evidence.json"
ADVERSARIAL = ("sybil_same_witness", "outsider_witness", "digest_mismatch", "future_gen_time")


def count_failures() -> int:
    try:
        ev = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 99   # 증거 부재/파손 = 최악값 (fail-closed)
    failed = 0
    for sc in ev.get("scenarios", []):
        if sc.get("name") in ADVERSARIAL and not sc.get("ok"):
            failed += 1
    return failed


if __name__ == '__main__':
    print(f"metric={count_failures()}")
    sys.exit(0)
