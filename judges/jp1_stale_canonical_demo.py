"""jp1 novel 오라클 실측 — stale_canonical_auto_demoted (JP 캠페인, bare-path 제출용 judge 스크립트).

v1(익명 판관) head-receipt 를 든 CANONICAL 1그루를 fake KG 에 구성하고 실
JudgementService.demote_stale_canonical(dry_run=False)을 구동 — 강등 수를 출력한다.
개선 metric(receipt_binds_engine_rule_sha)과 *다른 metric* 의 독립 실측(judge.py same-metric
독립성 게이트 밖). KG 실접속 0(fail-safe 규율).

출력: metric=<demoted 수>  (stale_canonical_auto_demoted, novel_threshold ≥ 1.0)
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if _REPO.as_posix() not in sys.path:
    sys.path.insert(0, _REPO.as_posix())

from server.contexts.tree.judgement_service import JudgementService  # noqa: E402


class _SweepKg:
    """v1 익명 판관의 CANONICAL 1그루 — CAS 충실 적용형 fake."""

    def __init__(self):
        self.rows = [{"tag": "legacy_v1", "prev_rsha": "p1", "ers": None, "vur": True}]
        self.demoted = []

    def __call__(self, query, **p):
        if "verdict:'CANONICAL'" in query and "RETURN e.tag AS tag" in query:
            return [dict(r) for r in self.rows]
        if "SET e.verdict='former_canonical'" in query:
            if (self.rows[0].get("prev_rsha") or "") != (p.get("prev") or ""):
                return []
            self.demoted.append(p["tag"])
            return [{"tag": p["tag"]}]
        return []


def main() -> int:
    kg = _SweepKg()
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [], hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    run = svc.demote_stale_canonical("T", dry_run=False)
    demoted = len(run["demoted"])
    print(f"stale_canonical_auto_demoted: 익명(v1) CANONICAL {demoted}그루 재심 강등 "
          f"(floor_size={run['floor_size']}, skipped_locked={run['skipped_locked']})")
    print(f"metric={demoted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
