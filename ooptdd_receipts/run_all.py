#!/usr/bin/env python3
"""LakatoTree 설계감사 13건 ooptdd-loop 영수증 일괄 재검증 (CI 엔트리).

각 finding 의 emit-adapter(`<F>/<f>_receipt.py:verify`)가 *실제 고쳐진 lakatos/server 코드*를
in-process 구동하고 구조화 이벤트를 ship → ooptdd-loop 이 R02(이벤트 trace 도착) + R10(Longinus
바인딩)으로 채점. 영수증은 pytest 가 아니라 LTDD 영수증이다(엔진 자체 dogfood 와 *이중* 검증).

실행 (ooptdd_loop + fastapi 가 있는 env 필요 — 예: ooptdd-loop 의 .venv):
    /path/to/ooptdd-loop/.venv/bin/python ooptdd_receipts/run_all.py
하나라도 green 이 아니면 exit 1.

규율: 이벤트 리터럴은 adapter 에만(엔진 코드 불변). 각 adapter 는 실모듈을 import 해 구동(재구현
금지)하고 음성 오라클(결함 주입 시 RED)을 포함한다. root 는 런타임에 절대경로로 오버라이드돼 cwd 와
무관(이식성). lakatos 는 repo 루트를 sys.path 에 넣어 import.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))   # lakatos / server import 가능하게
import lakatos.io  # noqa: F401,E402 — _vendor 를 sys.path 에 올리는 부트스트랩(import ooptdd / ooptdd_loop 해석)

try:   # ooptdd_loop = _vendor/ooptdd_loop (loop runner subset) — private repo·시크릿 불요(self-contained)
    from ooptdd_loop.spec import load_spec
    from ooptdd_loop.runner import run_loop
    from ooptdd_loop.tools import _run_payload
except ModuleNotFoundError as e:
    sys.exit(f"ooptdd_loop 미해석 — _vendor/ooptdd_loop 벤더 누락? ({e}).")

FINDINGS = ["H1", "H2", "H3", "H4", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]


def _run_one(finding: str) -> tuple[int, int, bool, str]:
    spec_path = HERE / finding / "requirements.yaml"
    if not spec_path.exists():
        return 0, 0, False, "spec 없음"
    try:
        spec = load_spec(str(spec_path))
        spec.target.root = str((HERE / finding).resolve())   # 절대 root 오버라이드(이식성)
        payload = _run_payload(run_loop(spec))
    except Exception as ex:   # import/실행 예외도 정직하게 RED 로
        return 0, 0, False, f"{type(ex).__name__}: {str(ex)[:70]}"
    done, total = payload.get("done", 0), payload.get("total", 0)
    green = bool(payload.get("complete") and payload.get("methodology_ok")
                 and total > 0 and done == total)
    return done, total, green, "" if green else "RED"


def main() -> int:
    rows = [(f, *_run_one(f)) for f in FINDINGS]
    print("LakatoTree 설계감사 ooptdd-loop 영수증 재검증 (R02 trace + R10 Longinus)")
    print("-" * 60)
    greens = 0
    for finding, done, total, green, note in rows:
        greens += green
        print(f"  {finding:3} {'GREEN' if green else 'RED  '}  {done}/{total}  {note}")
    print("-" * 60)
    print(f"  {greens}/{len(FINDINGS)} green")
    return 0 if greens == len(FINDINGS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
