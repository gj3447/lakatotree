#!/usr/bin/env python3
"""AG1/R-SOV-0 채점기 — 정본 문서 표면의 '확정 과대표현'(2026-07-03 정찰 3건) 잔존 수.

측정주권 PROM first_move: 서버는 오늘 measured float 를 소유하지 않는다(재현확인이지 값소유 아님).
그러므로 무단서 현재시제 '외부 측정/위조 닫힘/거짓말 불가'는 과대표현 — 이 채점기가 그 잔존을 센다.

metric = 잔존 과대표현 수 (baseline 3 → 목표 0). stdout `metric=<int>` + exit 0 (harness 계약).
판정은 결정론 substring/각주-마커 검사 — LLM 무관. 검사 목록은 사전등록 후 동결
(script_sha 로 서버 앵커 — 목록 완화가 곧 sha 변경 = 409).
# KG 거울: LakatosTree_MeasurementSovereignty_20260703 / ag1_rsov0_doc_honesty
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def count() -> int:
    tts = (ROOT / "TOUCH_THE_SKY.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    n = 0
    # ① TTS:427 — 미구현 G-Web 재fetch 를 현재시제 '닫는다'로 서술(lakatos/trust.py 자인과 모순)
    if "잔여 위조(특정 출판사 URL 을 사칭)는 재fetch 가 닫는다" in tts:
        n += 1
    # ② TTS:301 — '거짓말할 수 없는'은 측정층 한계 각주 없이는 무단서 현재시제([^1] 선례)
    sent = "이 DNA는 거짓말할 수 없는 채로 오른다."
    n += sum(1 for m in re.finditer(re.escape(sent), tts)
             if tts[m.end():m.end() + 2] != "[^")
    # ③ README 헤드라인 — 'an external measurement' 무단서(verdict/spine.py 자인: 외부성 미강제)
    if "and an external measurement" in readme:
        n += 1
    return n


if __name__ == "__main__":
    print(f"metric={count()}")
    sys.exit(0)
