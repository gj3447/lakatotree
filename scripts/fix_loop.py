#!/usr/bin/env python3
"""fix_loop — 2026-06-27 감사 수정의 *재실행 가능한 conjecture→measure→judge 루프*.

정적 영수증 묶음이 아니라, 프로젝트 독트린(conjecture/verification 역할분리 · receipts-not-claims ·
eureka felt-vs-true)을 감사 수정 자체에 적용한 *루프 드라이버*. 한 번 실행 = 한 사이클:

  ① measure   tests/fix_harness(+h9) pytest 영수증을 돌려 {test: passed} 수집 (외부 측정, self-report 아님)
  ② judge     examples/audit_20260627_programme.py 가 발견당 독립 이중가드를 judge() 에 먹여 verdict 생성(손입력 0)
  ③ eureka    완료라 *주장(felt)* 한 수정 중 엔진이 progressive 로 *확증(true)* 한 비율 — 나머지는 환각(미검증)
  ④ ratchet   fix_harness 정규 스위트가 green 이어야(착륙한 fix 가 회귀하면 xpass-strict/RED → exit 1)
  ⑤ frontier  다음 RED(OPEN) + 환각(felt-but-not-true) 을 다음 사이클의 작업으로 출력

exit 0 = 회귀 없음(루프 건강). exit 1 = 착륙한 수정이 회귀(영수증 RED) → 즉시 고칠 것.

사용:  python scripts/fix_loop.py        # 한 사이클(보드 + eureka + frontier)
       LAKATOS_IT=1 python scripts/fix_loop.py   # #16/#17 race 영수증까지(실 Neo4j)
"""
from __future__ import annotations

import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from examples import audit_20260627_programme as prog   # noqa: E402

# defect 가드가 실-Neo4j(LAKATOS_IT)를 요구해 로컬에선 skip 되는 노드(회귀 아님 — 미검증).
_GATED = {"FIX16_17_nonatomic_cas"}


def _green_ratchet() -> tuple[bool, str]:
    """fix_harness 정규 스위트(xfail 존중)가 green 인가 — 착륙한 fix 의 회귀(xpass-strict/RED) 차단."""
    cmd = (f"cd {_ROOT} && . .venv/bin/activate 2>/dev/null; "
           f"python -m pytest tests/fix_harness -q -p no:randomly 2>&1")
    r = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
    tail = (r.stdout or r.stderr).strip().splitlines()[-1:] or [""]
    return r.returncode == 0, tail[0]


def main() -> int:
    print("═" * 78)
    print("  fix_loop — LakatoTree 2026-06-27 감사 수정 루프 (measure→judge→eureka→ratchet)")
    print("═" * 78)

    # ① measure  ② judge
    rc = prog.receipt()
    landed = sum(1 for ok in rc.values() if ok)
    rows = prog.run(rc)
    print(f"\n① measure: {landed}/{len(rc)} 영수증 green ({prog._RECEIPT_PATHS})")
    print("② judge (verdict 전부 엔진 judge() 생성 — 손입력 0):\n")

    findings = [r for r in rows if r.get("verdict") != "canonical_stage"]
    claimed = [r for r in findings if r.get("claimed")]
    openrows = [r for r in findings if not r.get("claimed")]
    for r in sorted(findings, key=lambda x: (not x.get("claimed"), x["severity"], x["tag"])):
        v = r["verdict"]
        mark = {"progressive": "✓", "partial": "~"}.get(v, "·")
        flag = "claimed" if r.get("claimed") else "open"
        gated = "  [gated: LAKATOS_IT]" if r["tag"] in _GATED else ""
        print(f"   {mark} [{r['severity']:3}] {flag:7} {r['tag']:34} → {v:18} {r['status']}{gated}")

    n_prog = sum(1 for r in findings if r["verdict"] == "progressive")
    n_part = sum(1 for r in findings if r["verdict"] == "partial")
    print(f"\n   = {len(findings)} 결함: progressive {n_prog} · partial {n_part} · OPEN {len(findings)-n_prog-n_part}")

    # ③ eureka
    eb = prog.eureka_board(rows)
    print(f"\n③ eureka (완료 주장한 수정의 외부확증): "
          f"felt {eb['felt']} · true {eb['true']} · hallucinated {eb['hallucinated']} "
          f"→ true_rate {eb['true_rate']}  halluc_rate {eb['hallucination_rate']}")
    halluc = [(t, vd, why) for (t, vd, kind, why) in eb["detail"] if kind != "true"]
    if halluc:
        print("   환각(felt-but-not-true — 독립 mechanism 오라클/실-Neo4j 검증 필요):")
        for t, vd, why in halluc:
            gated = "  [gated: LAKATOS_IT 로 race 검증]" if t in _GATED else "  [mechanism 오라클 추가 → progressive]"
            print(f"     ✗ {t:34} {vd:14}{gated}")

    # ④ ratchet
    green, summary = _green_ratchet()
    print(f"\n④ ratchet (fix_harness 정규 스위트 green = 착륙 fix 회귀 없음): "
          f"{'GREEN' if green else 'RED'}  — {summary}")

    # ⑤ frontier
    frontier = [r for r in openrows if r["status"] == "OPEN"]
    print(f"\n⑤ frontier (다음 사이클 작업 — OPEN {len(frontier)}건, 우선순위 순):")
    for r in sorted(frontier, key=lambda x: (x["severity"], x["tag"]))[:6]:
        print(f"     • [{r['severity']:3}] {r['tag']}")
    if len(frontier) > 6:
        print(f"     … 외 {len(frontier)-6}건")

    # 회귀 게이트: 착륙(claimed·비-gated) 수정이 CLOSED 아래로 떨어지면 RED.
    regressed = [r for r in claimed if r["tag"] not in _GATED and r["status"] == "OPEN"]
    ok = green and not regressed
    print("\n" + "═" * 78)
    if regressed:
        print("  ✗ 회귀: 착륙했던 수정이 OPEN 으로 — " + ", ".join(r["tag"] for r in regressed))
    print(f"  루프 상태: {'✓ 건강(회귀 없음)' if ok else '✗ 회귀 — 즉시 고칠 것'}  "
          f"| 착륙 {n_prog+n_part}/{len(claimed)} claimed · frontier {len(frontier)} · 환각 {eb['hallucinated']}")
    print("═" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
