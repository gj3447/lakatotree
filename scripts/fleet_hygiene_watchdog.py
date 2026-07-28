#!/usr/bin/env python3
"""fleet hygiene watchdog — GET-only 함대 위생 시계열 + 정체/경보 검출 → ntfy.

결함(finding_ed8257ad6a2e6bf1, PROM16 2026-07-28): 위생 신호(alerts/무영수증 green·close/
tier 분포/abandon)는 per-tree GET 시점 stateless 재계산뿐 — 시계열·delta·push 채널이 없어
remediation ActionPlan 5건의 3일 침묵 정체를 아무 시스템도 감지하지 못했다.

봉합(plan-lktadv-p2-fleet-hygiene-watchdog-20260728): 엔진 코드 변경 0, 읽기 전용 —
  ① /api/trees + per-tree /metrics 스크레이프 → 스냅샷 JSONL append(시계열화)
  ② 직전 스냅샷 delta: 신규 abandon 신호(laudan/e-process) 발화 감지
  ③ 정체 검출: 위생 카운터(무영수증 green/close 합계)가 STALL_SNAPSHOTS 회 연속 불변 & >0
  ④ 경보는 ntfy 토픽으로 POST (건조 실행 --dry-run 은 stdout 만)

★증명 범위 경계: 이 watchdog 은 관측이지 집행이 아니다 — 경보를 사람이/세션이 소비해야
정체가 풀린다. 카운터 불변=미이행의 강한 정황이지 완전 증명은 아니다(실행 후 회귀 가능성).

환경변수:
  LAKATOTREE_URL       기본 http://127.0.0.1:55170
  WATCHDOG_STATE_DIR   기본 <repo>/.runtime/fleet_hygiene
  WATCHDOG_NTFY_URL    기본 https://ntfy.sh/metahumo-alerts-6b23086e (빈 문자열 = 발송 안 함)
  WATCHDOG_STALL_N     기본 3 (연속 불변 스냅샷 수)
크론(LXC301): systemd timer lakatotree-watchdog.timer (매일 04:47) — 설치는 배포 세션 문서 참조.
# KG: plan-lktadv-p2-fleet-hygiene-watchdog-20260728 / finding_ed8257ad6a2e6bf1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("LAKATOTREE_URL", "http://127.0.0.1:55170").rstrip("/")
NTFY = os.environ.get("WATCHDOG_NTFY_URL", "https://ntfy.sh/metahumo-alerts-6b23086e")
STALL_N = int(os.environ.get("WATCHDOG_STALL_N", "3"))

# 정체 감시 대상 카운터 — remediation 이행 여부의 대리 신호(07-25→07-28 침묵 정체의 실측 축).
STALL_KEYS = ("unreceipted_green_total", "unreceipted_close_total")


def _get(path: str, timeout: int = 60) -> dict | list:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
        return json.loads(resp.read())


def scrape_fleet() -> dict:
    """함대 스냅샷 — 실패 트리는 건너뛰되 계수(침묵 누락 금지)."""
    trees = _get("/api/trees")
    tier_dist: dict = {}
    totals = dict(unreceipted_green_total=0, unreceipted_close_total=0,
                  alerts_total=0, laudan_abandon_total=0, eprocess_abandon_trees=[])
    per_tree = {}
    errors = []
    for t in trees:
        name = t["name"]
        tier = t.get("assurance_tier") or "legacy"
        tier_dist[tier] = tier_dist.get(tier, 0) + 1
        try:
            m = _get(f"/api/tree/{name}/metrics")
        except Exception as exc:
            errors.append(f"{name}: {str(exc)[:80]}")
            continue
        row = dict(
            unreceipted_green=int((m.get("provenance") or {}).get("count") or 0),
            unreceipted_close=int((m.get("frontier") or {}).get("unreceipted_closes") or 0),
            alerts=len(m.get("alerts") or []),
            laudan_abandon=len((m.get("laudan") or {}).get("abandon_candidates") or []),
            eprocess_abandon=bool((m.get("eprocess") or {}).get("abandon")),
        )
        per_tree[name] = row
        totals["unreceipted_green_total"] += row["unreceipted_green"]
        totals["unreceipted_close_total"] += row["unreceipted_close"]
        totals["alerts_total"] += row["alerts"]
        totals["laudan_abandon_total"] += row["laudan_abandon"]
        if row["eprocess_abandon"]:
            totals["eprocess_abandon_trees"].append(name)
    return dict(ts=datetime.now(timezone.utc).isoformat(), tree_count=len(trees),
                tier_dist=tier_dist, scrape_errors=errors, **totals, per_tree=per_tree)


def load_history(state_dir: Path, limit: int = 10) -> list:
    p = state_dir / "snapshots.jsonl"
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def detect(snapshot: dict, history: list, stall_n: int = STALL_N) -> list:
    """경보 목록 — ①신규 abandon 발화(delta) ②정체(카운터 stall_n 회 연속 불변 & >0)."""
    findings = []
    prev = history[-1] if history else None
    if prev is not None:
        new_ep = sorted(set(snapshot["eprocess_abandon_trees"])
                        - set(prev.get("eprocess_abandon_trees") or []))
        if new_ep:
            findings.append(f"e-process 폐기 신호 신규 발화: {', '.join(new_ep)}")
        if snapshot["laudan_abandon_total"] > (prev.get("laudan_abandon_total") or 0):
            findings.append(
                f"laudan 폐기 후보 증가: {prev.get('laudan_abandon_total')}→{snapshot['laudan_abandon_total']}")
    window = [*history, snapshot]
    if len(window) >= stall_n:
        tail = window[-stall_n:]
        for key in STALL_KEYS:
            vals = [r.get(key) for r in tail]
            if len(set(vals)) == 1 and (vals[0] or 0) > 0:
                findings.append(
                    f"정체: {key}={vals[0]} 가 {stall_n}회 연속 불변 — remediation 미이행 정황")
    if snapshot["scrape_errors"]:
        findings.append(f"스크레이프 실패 {len(snapshot['scrape_errors'])}건 (침묵 누락 금지 계수)")
    return findings


def notify(findings: list, snapshot: dict, ntfy_url: str = NTFY) -> bool:
    if not findings or not ntfy_url:
        return False
    body = "\n".join(f"- {f}" for f in findings)
    body += f"\n(trees={snapshot['tree_count']}, tier={json.dumps(snapshot['tier_dist'], ensure_ascii=False)})"
    req = urllib.request.Request(
        ntfy_url, data=body.encode("utf-8"), method="POST",
        headers={"Title": "lakatotree fleet hygiene", "Tags": "warning"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status == 200


def run_once(state_dir: Path, *, dry_run: bool = False, stall_n: int = STALL_N,
             ntfy_url: str = NTFY) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    history = load_history(state_dir)
    snapshot = scrape_fleet()
    findings = detect(snapshot, history, stall_n=stall_n)
    with (state_dir / "snapshots.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
    notified = False
    if findings and not dry_run:
        notified = notify(findings, snapshot, ntfy_url=ntfy_url)
    return dict(findings=findings, notified=notified,
                tree_count=snapshot["tree_count"], tier_dist=snapshot["tier_dist"],
                totals={k: snapshot[k] for k in
                        ("unreceipted_green_total", "unreceipted_close_total",
                         "alerts_total", "laudan_abandon_total")})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fleet hygiene watchdog (GET-only)")
    ap.add_argument("--dry-run", action="store_true", help="ntfy 발송 없이 stdout 만")
    args = ap.parse_args(argv)
    state_dir = Path(os.environ.get("WATCHDOG_STATE_DIR", ROOT / ".runtime" / "fleet_hygiene"))
    out = run_once(state_dir, dry_run=args.dry_run)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
